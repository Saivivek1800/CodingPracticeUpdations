import argparse
import json
import os
import sys
from urllib.parse import urljoin

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

HINT_LIST_URL = ADMIN_URL + "nkb_question/codingquestionhint/"
SESSION_FILE = os.environ.get("SESSION_FILE", "admin_session.json")


def extract_question_hints(payload):
    result = []
    if not isinstance(payload, list):
        return result
    for item in payload:
        q = item.get("question", {}) if isinstance(item, dict) else {}
        qid = q.get("question_id")
        hints = item.get("hints", []) if isinstance(item, dict) else []
        if not qid:
            continue
        normalized = []
        if isinstance(hints, list):
            hints_sorted = sorted(hints, key=lambda h: h.get("order", 10**9))
            for h in hints_sorted:
                desc = h.get("description", {}) if isinstance(h, dict) else {}
                content = desc.get("content", "")
                if content is None:
                    content = ""
                normalized.append(str(content))
        if not normalized or not any(str(x).strip() for x in normalized):
            continue
        result.append((qid, normalized))
    return result


def search_hint_change_links(page, qid):
    search_url = f"{HINT_LIST_URL}?q={qid}"
    page.goto(search_url, wait_until="domcontentloaded", timeout=int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000")))
    page.wait_for_load_state("networkidle")
    if "403 Forbidden" in page.title() or "403 Forbidden" in page.content():
        raise PermissionError("403 on codingquestionhint changelist")
    links = page.evaluate(
        """() => {
        const rows = [...document.querySelectorAll("#result_list tbody tr")];
        const out = [];
        for (const tr of rows) {
          const cells = [...tr.querySelectorAll("th,td")].map(x => (x.textContent || "").trim());
          if (cells.some(c => c.includes("There are no") || c.includes("No coding question hint"))) continue;
          if (!cells.some(c => c.includes("question") || c.includes("-"))) {
            // keep relaxed; just try anchor if present
          }
          const a = tr.querySelector("th a");
          if (a && a.getAttribute("href")) out.push(a.getAttribute("href"));
        }
        return out;
      }"""
    )
    return links


def fill_hint_content_on_change_page(page, hint_text):
    selectors = [
        "#id_description_content",
        "textarea[name='description_content']",
        "#id_description",
        "#id_content",
        "textarea",
    ]
    for sel in selectors:
        if page.locator(sel).count() > 0:
            try:
                page.fill(sel, hint_text)
                return True
            except Exception:
                continue
    return False


def set_hints_for_question(page, qid, hints):
    print(f"Updating hints for question: {qid}")
    # Nothing to write: do not fail the pipeline — admin may have no hint rows yet.
    if not hints or not any(str(h).strip() for h in hints):
        print("  No hint text in input for this question; skipping hint update.")
        return True
    try:
        links = search_hint_change_links(page, qid)
    except PermissionError:
        print("  ERROR: 403 Forbidden on Coding question hints model.")
        print("  Your current account/session does not have permission for /admin/nkb_question/codingquestionhint/.")
        return False
    except Exception as e:
        print(f"  Failed to search coding question hints: {e}")
        return False

    if not links:
        print("  No hint rows found in Coding question hints for this question id.")
        return False

    ok_count = 0
    for idx, rel in enumerate(links):
        if idx >= len(hints):
            break
        url = rel if rel.startswith("http") else urljoin(ADMIN_URL, rel)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000")))
            page.wait_for_load_state("networkidle")
            if not fill_hint_content_on_change_page(page, hints[idx]):
                print(f"  Could not locate content textarea on hint row {idx+1}.")
                continue
            page.click("input[name='_save']")
            page.wait_for_load_state("networkidle")
            if "was changed successfully" in page.content():
                ok_count += 1
            else:
                print(f"  Save message not found for hint row {idx+1}.")
        except Exception as e:
            print(f"  Failed updating hint row {idx+1}: {e}")

    print(f"  Updated {ok_count}/{min(len(hints), len(links))} hint rows.")
    return ok_count > 0


def run_hints_updater(input_json_file):
    if not os.path.exists(input_json_file):
        print(f"Error: {input_json_file} not found.")
        return 1

    with open(input_json_file, "r", encoding="utf-8") as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in {input_json_file}: {e}")
            return 1

    updates = extract_question_hints(payload)
    if not updates:
        print("No questions with hints found in input JSON.")
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
            goto_or_fail(page, ADMIN_URL, script="auto_hints_updater.py")
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

            ok = 0
            failed = 0
            for qid, hints in updates:
                if set_hints_for_question(page, qid, hints):
                    ok += 1
                else:
                    failed += 1
            print(f"Hints update summary: success={ok}, failed={failed}")
            return 0 if failed == 0 else 1
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update coding question hints from input.json")
    parser.add_argument("input_json_file", nargs="?", default="input.json", help="Path to input.json")
    args = parser.parse_args()
    sys.exit(run_hints_updater(args.input_json_file))
