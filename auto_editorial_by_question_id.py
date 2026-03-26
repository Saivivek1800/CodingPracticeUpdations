"""
Update Learning Resource editorial content using Question id → Learning resource id (guided steps).

Admin model: Nkb_Question › Question guided solution steps
  - List shows Question id and Learning resource id (among other columns).
  - Search/filter by Question id → each row has the Learning resource id for that step.

This script:
  1) Opens that changelist and searches for your Question id.
  2) Reads the Learning resource id from the list (prefer the “Learning resource id” column).
  3) Opens Learning resource › change for that id and updates editorial (same as auto_editorial_updater).

Optional: EDITORIAL_TRY_QUESTION_FALLBACK=1 also tries the Question change page (off by default).

Input JSON — map Question id (UUID string) → editorial content to write:
  { "6b05b27f-77fe-4be5-ac4a-099d6851c9d4": "<p>...</p>" }

Optional wrapper keys (same inner dict): "editorial_by_question_id", "question_editorial"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import quote, urljoin

from playwright.sync_api import sync_playwright

from admin_playwright_util import chromium_launch_args, goto_or_fail, new_admin_browser_context

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith("/"):
    ADMIN_URL += "/"

GUIDED_STEP_LIST_URL = ADMIN_URL + "nkb_question/questionguidedsolutionstep/"
QUESTION_CHANGE_URL_TEMPLATE = ADMIN_URL + "nkb_question/question/{}/change/"
LEARNING_RESOURCE_CHANGE_URL_TEMPLATE = ADMIN_URL + "nkb_learning_resource/learningresource/{}/change/"

SESSION_FILE = os.environ.get("SESSION_FILE", "admin_session.json")
USERNAME = os.environ.get("DJANGO_ADMIN_USERNAME")
PASSWORD = os.environ.get("DJANGO_ADMIN_PASSWORD")
ADMIN_READY_TIMEOUT_MS = int(os.environ.get("DJANGO_ADMIN_READY_TIMEOUT_MS", "12000"))

# Admin URLs: .../learningresource/<pk>/... — PK may be integer or UUID (see guided step "Learning resource id").
LR_HREF_RE = re.compile(r"learningresource/(\d+)(?:/change)?/?", re.I)
LR_HREF_UUID_RE = re.compile(
    r"learningresource/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/change)?/?",
    re.I,
)
_LR_ADMIN_VALUE_RE = re.compile(
    r"^(?:\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.I,
)


def _is_learning_resource_admin_value(v: str) -> bool:
    v = (v or "").strip()
    return bool(v and _LR_ADMIN_VALUE_RE.match(v))


def _normalize_items(payload: dict) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")

    inner = payload
    for key in ("editorial_by_question_id", "question_editorial"):
        if key in payload and isinstance(payload[key], dict):
            inner = payload[key]
            break

    out: dict[str, str] = {}
    for k, v in inner.items():
        if k in ("editorial_by_question_id", "question_editorial", "learning_resource_data"):
            continue
        ks = str(k).strip()
        if not ks:
            continue
        out[ks] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    if not out:
        raise ValueError(
            "No question_id -> content entries found. Use {\"<question_uuid>\": \"<html or text>\"}"
        )
    return out


def _wait_admin_ready(page) -> None:
    """Fast post-navigation readiness check for Django admin pages."""
    for sel in ("#content-main", "#result_list", "form"):
        try:
            page.wait_for_selector(sel, timeout=ADMIN_READY_TIMEOUT_MS)
            return
        except Exception:
            continue


def _format_editorial_content(content_str) -> str:
    """Match auto_editorial_updater.py behavior for strings / nested JSON."""
    try:
        if isinstance(content_str, str):
            try:
                parsed_content = json.loads(content_str)
                if isinstance(parsed_content, (dict, list)):
                    return json.dumps(parsed_content, indent=4)
                return str(parsed_content)
            except json.JSONDecodeError:
                return content_str
        return json.dumps(content_str, indent=4)
    except Exception as e:
        print(f"  Warning: could not normalize content: {e}", flush=True)
        return str(content_str)


def _all_lr_ids_from_html(html: str) -> list[str]:
    """All learning-resource PKs found in HTML (numeric or UUID), stable order, unique."""
    seen: dict[str, None] = {}
    for m in LR_HREF_RE.finditer(html):
        seen.setdefault(m.group(1), None)
    for m in LR_HREF_UUID_RE.finditer(html):
        seen.setdefault(m.group(1), None)
    return list(seen.keys())


def _extract_learning_resource_ids_from_guided_step_changelist(page) -> list[str]:
    """
    On Question guided solution steps, the Learning resource id column appears when you search by Question id.
    Prefer column header “Learning resource id”; also scan links and row HTML for …/learningresource/<pk>/…
    """
    ids = page.evaluate(
        """() => {
        const out = [];
        const seen = new Set();
        const pushId = (id) => {
          if (!id || seen.has(id)) return;
          seen.add(id);
          out.push(id);
        };
        const lrHref = (href) => {
          if (!href) return;
          const m = href.match(/learningresource\\/(\\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
          if (m) pushId(m[1]);
        };

        const parseLrCellText = (raw) => {
          const s = (raw || "").trim();
          if (!s) return;
          const uuid = s.match(/^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i);
          if (uuid) { pushId(uuid[1]); return; }
          const plain = s.match(/^\\s*(\\d{2,20})\\s*$/);
          if (plain) { pushId(plain[1]); return; }
          const inParens = s.match(/\\((\\d{2,20})\\)/);
          if (inParens) { pushId(inParens[1]); return; }
          const m = s.match(/\\b(\\d{3,20})\\b/);
          if (m) pushId(m[1]);
        };

        const ths = [...document.querySelectorAll("#result_list thead th")];
        let lrCol = -1;
        let best = -1;
        ths.forEach((th, i) => {
          const txt = (th.textContent || "").toLowerCase().replace(/\\s+/g, " ");
          if (!txt.includes("learning") || !txt.includes("resource")) return;
          let score = 1;
          if (txt.includes("learning resource id") || txt.includes("learning_resource")) score += 3;
          else if (txt.includes("id")) score += 2;
          if (score > best) { best = score; lrCol = i; }
        });

        const rows = [...document.querySelectorAll("#result_list tbody tr")];
        for (const tr of rows) {
          const t = (tr.textContent || "").trim();
          if (/^0\\s+question guided solution step/i.test(t)) continue;
          if (/no (question guided|results|match)/i.test(t)) continue;

          if (lrCol >= 0) {
            const cells = [...tr.querySelectorAll("td, th")];
            const cell = cells[lrCol];
            if (cell) {
              for (const a of cell.querySelectorAll("a[href]")) lrHref(a.getAttribute("href"));
              parseLrCellText(cell.textContent || "");
            }
          }

          for (const a of tr.querySelectorAll("a[href]")) lrHref(a.getAttribute("href"));

          const rowHtml = tr.innerHTML || "";
          const re = /learningresource\\/(\\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/gi;
          let mm;
          while ((mm = re.exec(rowHtml)) !== null) pushId(mm[1]);
        }
        return out;
      }"""
    )
    return [str(x) for x in (ids or [])]


def _guided_step_change_hrefs(page) -> list[str]:
    """Links to .../questionguidedsolutionstep/<pk>/change/ (not /add/)."""
    hrefs = page.evaluate(
        """() => {
        const out = [];
        const re = /\\/questionguidedsolutionstep\\/[^/]+\\/change\\/?($|\\?)/i;
        const rows = [...document.querySelectorAll("#result_list tbody tr")];
        for (const tr of rows) {
          const t = (tr.textContent || "").trim();
          if (/no (question guided|results)/i.test(t)) continue;
          for (const a of tr.querySelectorAll("th a[href], td a[href]")) {
            const h = a.getAttribute("href") || "";
            if (re.test(h)) {
              out.push(h);
              break;
            }
          }
        }
        return out;
      }"""
    )
    return [str(h) for h in (hrefs or []) if h]


def _learning_resource_id_from_admin_form_page(page) -> str | None:
    """Resolve learning resource PK from any Django admin change form (step, question, etc.)."""
    # Wait for main form — FK widgets sometimes hydrate after load
    try:
        page.wait_for_selector("#content-main form", timeout=15000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    # Prefer form field values (e.g. guided step "Learning resource id" UUID) over arbitrary admin links.
    name_hints = (
        "learning_resource",
        "learning_resource_id",
        "resource",
        "tutorial_resource",
    )
    for nm in name_hints:
        for sel in (
            f'input[name="{nm}"]',
            f'select[name="{nm}"]',
            f'input[name="{nm}_id"]',
            f'select[name="{nm}_id"]',
        ):
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            try:
                tag = loc.evaluate("el => el.tagName.toLowerCase()")
                if tag == "input":
                    v = (loc.input_value() or "").strip()
                    if _is_learning_resource_admin_value(v):
                        return v
                elif tag == "select":
                    v = (loc.input_value() or "").strip()
                    if _is_learning_resource_admin_value(v):
                        return v
            except Exception:
                continue

    # id_learning_resource, id_learning_resource_0, etc.
    lr_by_id = page.locator("[id^='id_learning_resource']")
    for i in range(lr_by_id.count()):
        loc = lr_by_id.nth(i)
        try:
            tag = loc.evaluate("el => el.tagName.toLowerCase()")
            if tag == "input":
                v = (loc.input_value() or "").strip()
                if _is_learning_resource_admin_value(v):
                    return v
            if tag == "select":
                v = (loc.input_value() or "").strip()
                if _is_learning_resource_admin_value(v):
                    return v
        except Exception:
            continue

    # Hidden inputs often used by autocomplete
    hid = page.locator("input[type='hidden'][name*='resource']")
    for i in range(hid.count()):
        loc = hid.nth(i)
        try:
            v = (loc.input_value() or "").strip()
            if _is_learning_resource_admin_value(v):
                return v
        except Exception:
            continue

    # Custom FK names: any input/select with "learning" + "resource" in name
    dyn_names = page.evaluate(
        """() => {
        const out = [];
        for (const el of document.querySelectorAll("input[name], select[name]")) {
          const n = (el.getAttribute("name") || "");
          if (/learning/i.test(n) && /resource/i.test(n)) out.push(n);
        }
        return [...new Set(out)];
      }"""
    )
    for nm in dyn_names or []:
        loc = page.locator(f'[name="{nm}"]').first
        if loc.count() == 0:
            continue
        try:
            tag = loc.evaluate("el => el.tagName.toLowerCase()")
            if tag in ("input", "select"):
                v = (loc.input_value() or "").strip()
                if _is_learning_resource_admin_value(v):
                    return v
        except Exception:
            continue

    link_ids = page.evaluate(
        """() => {
        const s = new Set();
        for (const a of document.querySelectorAll('a[href*="learningresource"]')) {
          const m = (a.getAttribute("href") || "").match(
            /learningresource\\/(\\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i
          );
          if (m) s.add(m[1]);
        }
        return [...s];
      }"""
    )
    if link_ids:
        return str(link_ids[0])

    # Last resort: any learningresource in full HTML (may pick wrong id on busy pages)
    fallback = _all_lr_ids_from_html(page.content())
    return fallback[0] if fallback else None


def _try_learning_resource_from_question_admin(page, qid: str) -> str | None:
    """
    Optional fallback only if EDITORIAL_TRY_QUESTION_FALLBACK=1.
    Default flow uses Learning resource from Question guided solution steps only.
    """
    if os.environ.get("EDITORIAL_TRY_QUESTION_FALLBACK", "").strip() != "1":
        return None
    qid = (qid or "").strip()
    if not qid:
        return None
    q_url = QUESTION_CHANGE_URL_TEMPLATE.format(qid)
    timeout = int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000"))
    try:
        page.goto(q_url, wait_until="domcontentloaded", timeout=timeout)
        _wait_admin_ready(page)
    except Exception as e:
        print(f"  Could not open Question change page: {e}", flush=True)
        return None

    body = page.content()
    if "was not found" in body or "doesn't exist" in body or "404" in page.title():
        print("  Question change page: object not found (wrong question id or model?).", flush=True)
        return None

    return _learning_resource_id_from_admin_form_page(page)


def _guided_step_changelist_has_data_rows(page) -> bool:
    """True if the list shows at least one real row (not '0 question guided…')."""
    return bool(
        page.evaluate(
            """() => {
          const tr = document.querySelector("#result_list tbody tr");
          if (!tr) return false;
          const t = (tr.textContent || "").trim();
          if (/^0\\s+question guided solution step/i.test(t)) return false;
          if (/no (question guided|results|match)/i.test(t)) return false;
          return true;
        }"""
        )
    )


def _load_guided_step_list_for_question(page, qid: str) -> None:
    """Try admin filters until changelist has rows or learning resource ids, or all strategies exhausted."""
    timeout = int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000"))
    strategies = [
        ("q", f"{GUIDED_STEP_LIST_URL}?q={quote(qid)}"),
        ("question__id__exact", f"{GUIDED_STEP_LIST_URL}?question__id__exact={quote(qid)}"),
        ("question__pk__exact", f"{GUIDED_STEP_LIST_URL}?question__pk__exact={quote(qid)}"),
    ]
    for name, url in strategies:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            _wait_admin_ready(page)
        except Exception:
            continue
        if _extract_learning_resource_ids_from_guided_step_changelist(page):
            if name != "q":
                print(f"  (list filter: {name}=...)", flush=True)
            return
        if _guided_step_change_hrefs(page):
            if name != "q":
                print(f"  (list filter: {name}=...)", flush=True)
            return
        if _guided_step_changelist_has_data_rows(page):
            if name != "q":
                print(f"  (list filter: {name}=...)", flush=True)
            return
    # Last URL from loop may be empty; caller still reads current page


def _resolve_learning_resource_id(page, qid: str) -> str | None:
    _load_guided_step_list_for_question(page, qid)
    if "403 Forbidden" in page.title() or "403 Forbidden" in page.content():
        print("  ERROR: 403 on Question guided solution steps.", flush=True)
        return None

    ids = _extract_learning_resource_ids_from_guided_step_changelist(page)
    if ids:
        if len(ids) > 1:
            print(
                "  Note: multiple Learning resource ids in guided solution rows "
                f"({', '.join(ids)}); using first: {ids[0]}",
                flush=True,
            )
        else:
            print(
                f"  Using Learning resource id {ids[0]} from Question guided solution steps (list).",
                flush=True,
            )
        return ids[0]

    step_hrefs = _guided_step_change_hrefs(page)
    if not step_hrefs:
        print(
            "  No guided solution step change links on this list view (trying step forms if any).",
            flush=True,
        )

    last_err = None
    for idx, rel in enumerate((step_hrefs or [])[:15]):
        step_url = rel if rel.startswith("http") else urljoin(ADMIN_URL, rel)
        try:
            page.goto(step_url, wait_until="domcontentloaded", timeout=int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000")))
            _wait_admin_ready(page)
        except Exception as e:
            last_err = e
            continue

        lr = _learning_resource_id_from_admin_form_page(page)
        if lr:
            if idx > 0:
                print(f"  (used guided step row {idx + 1} of {len(step_hrefs)})", flush=True)
            print(f"  Resolved learning resource id from step form: {lr}", flush=True)
            return lr

    if last_err:
        print(f"  Last navigation error while opening guided steps: {last_err}", flush=True)

    if os.environ.get("EDITORIAL_TRY_QUESTION_FALLBACK", "").strip() == "1":
        print("  EDITORIAL_TRY_QUESTION_FALLBACK=1 — trying Question change page...", flush=True)
        lr = _try_learning_resource_from_question_admin(page, qid)
        if lr:
            print(f"  Resolved learning resource id from Question admin: {lr}", flush=True)
            return lr

    print(
        f"  EXCEPTION: Question ID {qid} not found learning resource "
        "(no guided step row, empty FK, or wrong filters).",
        flush=True,
    )
    return None


def _fill_admin_text_field(page, selector: str, value: str) -> bool:
    """
    Fill a Django admin body field. Prefer visible fill (auto_editorial_updater behavior);
    if the widget is rich-text, the textarea is often display:none — use force fill / value injection.
    """
    loc = page.locator(selector).first
    if loc.count() == 0:
        return False
    if page.is_visible(selector):
        try:
            page.fill(selector, value)
            return True
        except Exception:
            pass
    try:
        loc.scroll_into_view_if_needed(timeout=8000)
    except Exception:
        pass
    try:
        loc.fill(value, timeout=15000, force=True)
        return True
    except Exception:
        pass
    try:
        loc.evaluate(
            """(el, val) => {
            if (!el) return;
            if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
              el.value = val;
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
            }
          }""",
            value,
        )
        return True
    except Exception:
        return False


def _fill_learning_resource_content_and_save(page, resource_id: str, formatted: str) -> bool:
    """
    After the Learning resource id is known: same field order as auto_editorial_updater.py
    (#id_editorial → #id_tutorial → #id_content), then optional #id_content_en.
    Hidden rich-text textareas get force-fill / DOM value set when is_visible is false.
    """
    target_url = LEARNING_RESOURCE_CHANGE_URL_TEMPLATE.format(resource_id)
    print(f"  Navigating to: {target_url}", flush=True)
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000")))
        _wait_admin_ready(page)
    except Exception as e:
        print(f"  Error navigating to page: {e}", flush=True)
        return False

    if "was not found" in page.content() or "doesn't exist" in page.content():
        print(f"  Error: Learning Resource with ID {resource_id} not found.", flush=True)
        return False

    try:
        page.wait_for_selector("#content-main form", timeout=20000)
    except Exception:
        pass

    field_selectors = ["#id_editorial", "#id_tutorial", "#id_content"]
    active_selector = None
    for selector in field_selectors:
        if page.locator(selector).first.count() == 0:
            continue
        if _fill_admin_text_field(page, selector, formatted):
            active_selector = selector
            print(f"  Updating field {active_selector}...", flush=True)
            break

    if not active_selector:
        n = page.locator("textarea[name*='content']").count()
        for i in range(min(n, 8)):
            loc = page.locator("textarea[name*='content']").nth(i)
            try:
                nm = (loc.evaluate("el => el.name || ''") or "").lower()
            except Exception:
                nm = ""
            if "content_en" in nm or "content-en" in nm:
                continue
            try:
                loc.scroll_into_view_if_needed(timeout=8000)
            except Exception:
                pass
            try:
                loc.fill(formatted, timeout=15000, force=True)
                print(f"  Updating field textarea[name={nm!r}] (fallback)...", flush=True)
                active_selector = "textarea"
                break
            except Exception:
                pass
            try:
                loc.evaluate(
                    """(el, val) => {
                    if (!el) return;
                    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                      el.value = val;
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                  }""",
                    formatted,
                )
                print(f"  Updating field textarea[name={nm!r}] (fallback, DOM set)...", flush=True)
                active_selector = "textarea"
                break
            except Exception:
                continue

    if not active_selector:
        print(
            f"  Error: Could not find any editorial/tutorial/content field for resource {resource_id}. "
            f"Tried: {field_selectors} and content-named textareas.",
            flush=True,
        )
        return False

    if page.locator("#id_content_en").first.count() > 0 and _fill_admin_text_field(page, "#id_content_en", formatted):
        print("  Updating field #id_content_en...", flush=True)

    print("  Saving...", flush=True)
    page.click("input[name='_save']")
    _wait_admin_ready(page)

    if "was changed successfully" in page.content():
        print(f"  SUCCESS: Editorial/Tutorial updated for {resource_id}", flush=True)
        return True

    print(f"  FAILURE: Could not verify success for {resource_id}", flush=True)
    if page.is_visible(".errornote"):
        try:
            print(f"  Error Note: {page.inner_text('.errornote')}", flush=True)
        except Exception:
            pass
    if page.is_visible(".errorlist"):
        try:
            print(f"  Field Errors: {page.inner_text('.errorlist')}", flush=True)
        except Exception:
            pass
    return False


def run_editorial_by_question_id(json_file: str) -> int:
    if not os.path.exists(json_file):
        print(f"Error: {json_file} not found.", flush=True)
        if json_file == "input_editorial_by_question_id.json":
            print(
                '  Create input_editorial_by_question_id.json as {"<question_uuid>": "<editorial html or text>"}',
                flush=True,
            )
        return 1

    with open(json_file, "r", encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON: {e}", flush=True)
            return 1

    try:
        items = _normalize_items(raw)
    except ValueError as e:
        print(f"Error: {e}", flush=True)
        return 1

    ok = 0
    failed = 0
    updated_qids: list[str] = []
    missing_learning_resource_qids: list[str] = []
    failed_update_qids: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_args())
        context = new_admin_browser_context(browser, SESSION_FILE)
        page = context.new_page()
        try:
            goto_or_fail(page, ADMIN_URL, script="auto_editorial_by_question_id.py")
            if "Log out" not in page.content():
                if USERNAME and PASSWORD:
                    print("Logging in...", flush=True)
                    page.fill("#id_username", USERNAME)
                    page.fill("#id_password", PASSWORD)
                    page.click("input[type='submit']")
                    page.wait_for_load_state("networkidle")
                    context.storage_state(path=SESSION_FILE)
                else:
                    print("Session expired and no credentials provided.", flush=True)
                    return 1

            for qid, content in items.items():
                print(f"\nQuestion id: {qid}", flush=True)
                try:
                    lr_id = _resolve_learning_resource_id(page, qid)
                except Exception as e:
                    print(
                        f"  EXCEPTION: Question ID {qid} not found learning resource "
                        f"(resolve error: {e!r}) — skipping, continuing.",
                        flush=True,
                    )
                    missing_learning_resource_qids.append(qid)
                    failed += 1
                    continue
                if not lr_id:
                    print(f"  Skipping Question ID {qid} (continuing with next).", flush=True)
                    missing_learning_resource_qids.append(qid)
                    failed += 1
                    continue
                try:
                    formatted = _format_editorial_content(content)
                    print(f"  Updating learning resource {lr_id} (from guided solution steps)...", flush=True)
                    if _fill_learning_resource_content_and_save(page, lr_id, formatted):
                        ok += 1
                        updated_qids.append(qid)
                    else:
                        failed += 1
                        failed_update_qids.append(qid)
                except Exception as e:
                    print(
                        f"  Error while updating learning resource {lr_id}: {e!r} — skipping, continuing.",
                        flush=True,
                    )
                    failed += 1
                    failed_update_qids.append(qid)
                    continue

            print(f"\nEditorial-by-question-id summary: success={ok}, failed={failed}", flush=True)
            print(f"Updated questions count: {len(updated_qids)}", flush=True)
            if updated_qids:
                print(f"Updated question IDs: {', '.join(updated_qids)}", flush=True)
            print(f"Questions without learning resource count: {len(missing_learning_resource_qids)}", flush=True)
            if missing_learning_resource_qids:
                print(f"Questions without learning resource: {', '.join(missing_learning_resource_qids)}", flush=True)
            print(f"Questions failed during update count: {len(failed_update_qids)}", flush=True)
            if failed_update_qids:
                print(f"Questions failed during update: {', '.join(failed_update_qids)}", flush=True)
            return 0 if failed == 0 else 1
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Resolve learning resource from Question guided solution steps and update editorial."
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        default="input_editorial_by_question_id.json",
        help="JSON: { \"<question_id>\": \"<content>\" }",
    )
    args = parser.parse_args()
    sys.exit(run_editorial_by_question_id(args.json_file))
