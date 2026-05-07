"""
Update Coding question test case evaluation metrics in Django admin from JSON.

Admin changelist path is configurable (model URL may use singular/plural or underscores).
Default changelist matches beta admin URL slug (typo in backend: "evalution"):
  .../admin/nkb_question/codingquestiontestcaseevalutionmetrics/

Input file shape (from generate_input_evaluation_metrics.py):
{
  "evaluation_metrics_by_question": {
    "<question_uuid>": [
      {"language": "CPP", "time_limit_to_execute_in_seconds": 1.0},
      ...
    ]
  }
}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import quote, urljoin

from playwright.sync_api import sync_playwright

from admin_playwright_util import (
    chromium_launch_args,
    django_admin_can_relogin_or_session,
    django_admin_login_credentials,
    goto_or_fail,
    new_admin_browser_context,
)

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith("/"):
    ADMIN_URL += "/"

# Primary path + optional comma-separated alternates in DJANGO_EVAL_METRICS_MODEL_PATH_ALTERNATES
def _list_url_bases() -> list[str]:
    primary = os.environ.get(
        "DJANGO_EVAL_METRICS_MODEL_PATH",
        "nkb_question/codingquestiontestcaseevalutionmetrics/",
    )
    extra = os.environ.get("DJANGO_EVAL_METRICS_MODEL_PATH_ALTERNATES", "")
    paths: list[str] = []
    for p in [primary] + [x.strip() for x in extra.split(",") if x.strip()]:
        if not p.endswith("/"):
            p += "/"
        if p not in paths:
            paths.append(p)
    # Fallbacks if primary 404s (correct spelling "evaluation", singular, underscores, coding_core)
    for alt in (
        "nkb_question/codingquestiontestcaseevaluationmetrics/",
        "nkb_question/codingquestiontestcaseevaluationmetric/",
        "nkb_question/coding_question_test_case_evaluation_metric/",
        "nkb_question/coding_question_test_case_evaluation_metrics/",
        "nkb_coding_core/codingquestiontestcaseevalutionmetrics/",
        "nkb_coding_core/codingquestiontestcaseevaluationmetric/",
        "nkb_coding_core/coding_question_test_case_evaluation_metric/",
        "nkb_coding_core/codingquestiontestcaseevaluationmetrics/",
    ):
        if alt not in paths:
            paths.append(alt)
    seen_u: set[str] = set()
    out: list[str] = []
    for p in paths:
        u = ADMIN_URL + p
        if u not in seen_u:
            seen_u.add(u)
            out.append(u)
    return out

SESSION_FILE = os.environ.get("SESSION_FILE", "admin_session.json")

GOTO_TIMEOUT_MS = int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000"))

def _norm_lang(s: str) -> str:
    return (s or "").strip().upper().replace(" ", "_")


def _collect_change_hrefs(page) -> list[str]:
    """Collect /change/ links from changelist (supports default Django admin + common themes)."""
    return page.evaluate(
        """() => {
        const seen = new Set();
        const out = [];
        const add = (h) => {
          if (!h || h.includes("/add/") || !h.includes("/change/")) return;
          if (seen.has(h)) return;
          seen.add(h);
          out.push(h);
        };
        const roots = [
          document.querySelector("#changelist-form"),
          document.querySelector("#result_list"),
          document.querySelector("table#result_list"),
          document.querySelector("#content-main"),
          document.querySelector("main .changelist"),
          document.querySelector(".changelist-results"),
          document.querySelector(".module.filtered#changelist"),
          document.querySelector("#content .module"),
        ].filter(Boolean);
        for (const root of roots) {
          root.querySelectorAll('a[href*="/change/"]').forEach(a => add(a.getAttribute("href")));
        }
        const rowSelectors = [
          "#result_list tbody tr",
          "table.changelist tbody tr",
          ".results tbody tr",
          "#changelist tbody tr",
        ];
        for (const sel of rowSelectors) {
          for (const tr of document.querySelectorAll(sel)) {
            const cells = [...tr.querySelectorAll("th,td")].map(x => (x.textContent || "").trim());
            if (cells.some(c => c.includes("There are no") || /no .* found/i.test(c))) continue;
            const a = tr.querySelector("th a") || tr.querySelector("td a");
            if (a) add(a.getAttribute("href"));
          }
        }
        if (out.length) return out;
        const main = document.querySelector("#content-main, main#content-main, article, main");
        if (main) {
          main.querySelectorAll('a[href*="/change/"]').forEach(a => {
            const h = a.getAttribute("href") || "";
            if (h.includes("nkb_question") || h.includes("evaluation") || h.includes("evalution") || h.includes("metric")) add(h);
          });
        }
        return out;
      }"""
    )


def _changelist_query_urls(list_base: str, qid: str) -> list[str]:
    """Django admin: ?q= only uses search_fields; FK filters often use question__id__exact."""
    base = list_base.rstrip("/") + "/"
    q_enc = quote(qid, safe="")
    return [
        f"{base}?question__id__exact={qid}",
        f"{base}?question_id__exact={qid}",
        f"{base}?question__pk__exact={qid}",
        f"{base}?question__id={qid}",
        f"{base}?q={qid}",
        f"{base}?q={q_enc}",
    ]


def _hrefs_from_question_change_page(page, qid: str) -> list[str]:
    """Last resort: find change links to evaluation-metric objects from the Question admin page."""
    q_url = f"{ADMIN_URL}nkb_question/question/{qid}/change/"
    print(f"  Trying question change page for related metric links: {q_url}")
    try:
        page.goto(q_url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        page.wait_for_load_state("networkidle")
    except Exception as e:
        print(f"  WARN: could not open question page: {e}")
        return []
    if "404" in page.title() or "not found" in page.title().lower():
        return []
    return page.evaluate(
        """() => {
        const out = [];
        for (const a of document.querySelectorAll('a[href*="/change/"]')) {
          const h = a.getAttribute("href") || "";
          const hl = h.toLowerCase();
          if ((hl.includes("evaluation") || hl.includes("evalution")) && hl.includes("metric")) out.push(h);
        }
        return [...new Set(out)];
      }"""
    )


def _changelist_search_by_question_id(page, list_base: str, qid: str) -> list[str]:
    """Use the admin changelist search box (search by question id) — same as manual workflow."""
    base = list_base.rstrip("/") + "/"
    print(f"  Changelist search box: open {base} then search for question id")
    try:
        resp = page.goto(base, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        page.wait_for_load_state("networkidle")
    except Exception as e:
        print(f"  WARN: could not open changelist: {e}")
        return []
    if resp is not None and resp.status >= 400:
        print(f"  NOTE: changelist returned HTTP {resp.status} (wrong model path?) — {base}")
        return []
    if "403 Forbidden" in page.title() or "403 Forbidden" in page.content():
        print("  ERROR: 403 on changelist — check permissions.")
        return []

    search_selectors = [
        'input[name="q"]',
        "#searchbar",
        "#toolbar input[name='q']",
        "#changelist-search input[type='text']",
        'form#changelist-search input[name="q"]',
        "input[type='search']",
    ]
    submitted = False
    for sel in search_selectors:
        inp = page.locator(sel).first
        try:
            inp.wait_for(state="visible", timeout=4000)
            inp.fill("")
            inp.fill(qid)
            inp.press("Enter")
            page.wait_for_load_state("networkidle")
            submitted = True
            break
        except Exception:
            continue

    if submitted:
        hrefs = _collect_change_hrefs(page)
        if hrefs:
            print(f"  Search found {len(hrefs)} row(s) to edit.")
            return hrefs
        for btn_sel in (
            'input[type="submit"][value="Search"]',
            'button[type="submit"]',
            "button[aria-label='Search']",
        ):
            btn = page.locator(btn_sel).first
            try:
                if btn.is_visible():
                    btn.click()
                    page.wait_for_load_state("networkidle")
                    hrefs = _collect_change_hrefs(page)
                    if hrefs:
                        print(f"  Search (button) found {len(hrefs)} row(s) to edit.")
                        return hrefs
            except Exception:
                continue
        n_links = page.locator('a[href*="/change/"]').count()
        print(
            f"  NOTE: search ran but no changelist rows parsed (page has ~{n_links} /change/ links total). "
            "If you see results manually, the theme DOM may differ — send a saved HTML snippet or admin theme name."
        )
        return []

    print("  WARN: could not find changelist search input; trying URL filters.")
    return []


def _try_fetch_metric_hrefs(page, qid: str) -> list[str]:
    max_tries = int(os.environ.get("DJANGO_EVAL_METRICS_MAX_CHANGELIST_TRIES", "12"))
    tries = 0
    for list_url in _list_url_bases():
        hrefs = _changelist_search_by_question_id(page, list_url, qid)
        if hrefs:
            return hrefs
        for cand in _changelist_query_urls(list_url, qid):
            if tries >= max_tries:
                print(f"  WARN: reached max changelist tries ({max_tries}); stopping further URL probes.")
                return []
            tries += 1
            print(f"  Opening changelist: {cand}")
            try:
                r = page.goto(cand, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
                page.wait_for_load_state("networkidle")
            except Exception as e:
                print(f"  WARN: navigation failed: {e}")
                continue
            # If kicked to login / no auth, stop immediately.
            if page.locator("#id_username").count() > 0 and page.locator("#id_password").count() > 0:
                print("  ERROR: landed on login page while probing changelist (session/permission issue).")
                return []
            if "403 Forbidden" in page.title() or "403 Forbidden" in page.content():
                print("  ERROR: 403 on changelist — check permissions.")
                return []
            if r is not None and r.status >= 400:
                continue
            hrefs = _collect_change_hrefs(page)
            if hrefs:
                return hrefs
    hrefs = _hrefs_from_question_change_page(page, qid)
    return hrefs


def _read_language(page) -> str | None:
    sel = page.locator("#id_language")
    if sel.count() == 0:
        return None
    try:
        return sel.input_value()
    except Exception:
        try:
            return (sel.inner_text() or "").strip() or None
        except Exception:
            return None


def _fill_execution_time_field(page, value: float) -> bool:
    """Admin shows 'Execution time in seconds'; model field may be execution_time_* or time_limit_*."""
    text = str(float(value))
    field_ids = [
        "id_execution_time_in_seconds",
        "id_execution_time",
        "id_time_limit_to_execute_in_seconds",
        "id_time_limit",
    ]
    for fid in field_ids:
        loc = page.locator(f"#{fid}")
        if loc.count() > 0:
            try:
                loc.first.fill(text)
                return True
            except Exception:
                continue
    for pattern in (
        r"Execution\s+time\s+in\s+seconds",
        r"Execution\s+time",
    ):
        try:
            page.get_by_label(re.compile(pattern, re.I)).fill(text)
            return True
        except Exception:
            continue
    label_for = page.evaluate(
        """() => {
        for (const lb of document.querySelectorAll('label')) {
          const t = (lb.textContent || '').toLowerCase();
          if ((t.includes('execution') && t.includes('second')) || t.includes('execution time')) {
            const id = lb.getAttribute('for');
            if (id) {
              const el = document.getElementById(id);
              if (el && /^(input|textarea)$/i.test(el.tagName)) return id;
            }
          }
        }
        return null;
      }"""
    )
    if label_for:
        try:
            page.fill(f"#{label_for}", text)
            return True
        except Exception:
            pass
    return False


def _update_one_question(page, qid: str, metrics: list[dict]) -> bool:
    desired: dict[str, float] = {}
    for m in metrics:
        if not isinstance(m, dict):
            continue
        lang = m.get("language")
        tl = m.get("time_limit_to_execute_in_seconds")
        if tl is None:
            tl = m.get("execution_time_in_seconds")
        if lang is None or tl is None:
            continue
        desired[_norm_lang(str(lang))] = float(tl)

    if not desired:
        print(f"  No valid metric rows in input for question {qid}; skipping.")
        return True

    hrefs = _try_fetch_metric_hrefs(page, qid)
    if not hrefs:
        print(f"  No evaluation metric rows found in admin for question {qid}.")
        print("  Create rows in admin first, or set DJANGO_EVAL_METRICS_MODEL_PATH /")
        print("  DJANGO_EVAL_METRICS_MODEL_PATH_ALTERNATES to match your admin URL.")
        return False

    remaining = dict(desired)
    ok = 0
    for rel in hrefs:
        if not remaining:
            break
        url = rel if rel.startswith("http") else urljoin(ADMIN_URL, rel)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"  WARN: could not open change page {url}: {e}")
            continue

        cur_lang = _read_language(page)
        if not cur_lang:
            print("  WARN: could not read #id_language on change page; skipping row.")
            continue
        key = _norm_lang(cur_lang)
        if key not in remaining:
            continue

        val = remaining[key]
        if not _fill_execution_time_field(page, val):
            print(f"  ERROR: could not fill 'Execution time in seconds' (or id_*) for language {cur_lang}.")
            continue

        try:
            page.click("input[name='_save']")
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"  ERROR: save failed for {cur_lang}: {e}")
            continue

        if "was changed successfully" in page.content():
            print(f"  SUCCESS: updated {cur_lang} execution time (seconds)={val}")
            ok += 1
            del remaining[key]
        else:
            print(f"  FAILURE: save not confirmed for language {cur_lang}")

    if remaining:
        print(f"  WARN: not updated (missing rows or no match): {', '.join(remaining.keys())}")

    return len(remaining) == 0 or ok > 0


def run_evaluation_metrics_updater(json_file: str) -> int:
    if not os.path.exists(json_file):
        print(f"Error: {json_file} not found.")
        return 1

    with open(json_file, "r", encoding="utf-8") as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in {json_file}: {e}")
            return 1

    by_q = payload.get("evaluation_metrics_by_question")
    if not isinstance(by_q, dict) or not by_q:
        print("No evaluation_metrics_by_question entries; nothing to do.")
        return 0

    if not django_admin_can_relogin_or_session(SESSION_FILE, admin_url=ADMIN_URL):
        print(
            f"Error: No saved session ({SESSION_FILE}) and no admin credentials in environment. "
            "Add BETA_/PROD_DJANGO_ADMIN_* to .secrets.env or secrets.local.env.",
            flush=True,
        )
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_args())
        context = new_admin_browser_context(browser, SESSION_FILE)
        page = context.new_page()
        try:
            goto_or_fail(page, ADMIN_URL, script="auto_evaluation_metrics_updater.py")
            if "Log out" not in page.content():
                user, pwd = django_admin_login_credentials(ADMIN_URL)
                if user and pwd:
                    print("Logging in...")
                    page.fill("#id_username", user)
                    page.fill("#id_password", pwd)
                    page.click("input[type='submit']")
                    page.wait_for_load_state("networkidle")
                    context.storage_state(path=SESSION_FILE)
                else:
                    print("Session expired and no credentials provided.")
                    return 1

            ok_n = 0
            fail_n = 0
            for qid, metrics in by_q.items():
                print(f"\nProcessing evaluation metrics for question: {qid}")
                if not isinstance(metrics, list):
                    print("  Invalid metrics list; skipping.")
                    fail_n += 1
                    continue
                if _update_one_question(page, str(qid), metrics):
                    ok_n += 1
                else:
                    fail_n += 1

            print(f"\nEvaluation metrics summary: success={ok_n}, failed={fail_n}")
            return 0 if fail_n == 0 else 1
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update test case evaluation metrics per question from JSON.")
    parser.add_argument("json_file", nargs="?", default="input_evaluation_metrics.json")
    args = parser.parse_args()
    sys.exit(run_evaluation_metrics_updater(args.json_file))
