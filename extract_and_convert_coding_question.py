import argparse
import json
import os
import time

import requests
from playwright.sync_api import sync_playwright

from admin_playwright_util import chromium_launch_args, goto_or_fail, new_admin_browser_context
from convert_extracted_to_coding_json import convert


ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith("/"):
    ADMIN_URL += "/"

CONTENT_LOADING_URL = ADMIN_URL + "nkb_load_data/contentloading/add/"
SESSION_FILE = os.environ.get("SESSION_FILE", "beta_admin_session.json")
USERNAME = os.environ.get("DJANGO_ADMIN_USERNAME")
PASSWORD = os.environ.get("DJANGO_ADMIN_PASSWORD")


def _max_wait_seconds_for_payload(payload: dict) -> int:
    """How long to poll the admin task before giving up (batch jobs need longer)."""
    if os.environ.get("EXTRACT_MAX_WAIT_SEC"):
        return max(60, int(os.environ["EXTRACT_MAX_WAIT_SEC"]))
    ids = payload.get("question_ids")
    n = len(ids) if isinstance(ids, list) else 1
    # Default: at least 30 min; add 5 min per question (10 questions ≈ 80 min).
    return max(1800, 900 + n * 300)


def _page_looks_logged_in(page) -> bool:
    """Detect Django admin session without relying on full HTML (faster, fewer false negatives)."""
    try:
        u = (page.url or "").lower()
        if "/admin/login" in u or u.rstrip("/").endswith("/login"):
            return False
    except Exception:
        pass
    try:
        loc = page.locator("a[href*='logout']")
        if loc.count() > 0:
            try:
                return loc.first.is_visible(timeout=5000)
            except Exception:
                return True
    except Exception:
        pass
    try:
        body = page.content()
    except Exception:
        body = ""
    return "Log out" in body or "Logout" in body


def _extract_s3_url(task_output_text: str) -> str | None:
    data = json.loads(task_output_text)
    if isinstance(data, dict):
        response = data.get("response")
        if isinstance(response, dict) and response.get("input_questions_json_s3_url"):
            return response["input_questions_json_s3_url"]
        output = data.get("output")
        if isinstance(output, dict) and output.get("input_questions_json_s3_url"):
            return output["input_questions_json_s3_url"]
        if isinstance(output, str) and output.startswith("http"):
            return output
    return None


def run(input_file: str, raw_output_file: str, converted_output_file: str) -> None:
    with open(input_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_args())
        context = new_admin_browser_context(browser, SESSION_FILE)
        page = context.new_page()

        goto_or_fail(page, ADMIN_URL, script="extract_and_convert_coding_question.py")
        try:
            page.wait_for_load_state("networkidle", timeout=90000)
        except Exception:
            pass

        if not _page_looks_logged_in(page):
            if USERNAME and PASSWORD:
                page.fill("#id_username", USERNAME)
                page.fill("#id_password", PASSWORD)
                page.click("input[type='submit']")
                page.wait_for_load_state("networkidle")
                context.storage_state(path=SESSION_FILE)
            else:
                _env_hint = os.environ.get("DJANGO_TARGET_ENV") or (
                    "prod" if "prod" in os.path.basename(SESSION_FILE).lower() else "beta"
                )
                raise RuntimeError(
                    "Django admin session is missing or expired, and no username/password were loaded for re-login. "
                    f"Target from session file: {_env_hint}. "
                    "Add BETA_DJANGO_ADMIN_USERNAME/PASSWORD (and PROD_* for prod) to .secrets.env, "
                    "or set SECRETS_DECRYPTION_KEY so .secrets.enc decrypts in NON_INTERACTIVE mode. "
                    f"You can delete {SESSION_FILE} after fixing credentials, then run again to save a new session."
                )

        print("Creating content loading task...")
        page.goto(CONTENT_LOADING_URL)
        page.wait_for_load_state("networkidle")
        page.select_option("#id_task_type", "EXTRACT_CODING_QUESTION_CONTENT")
        page.fill("#id_input_data", json.dumps(payload))
        page.click("input[name='_continue']")
        page.wait_for_load_state("networkidle")

        print(f"Tracking task: {page.url}")
        status_selector = ".field-task_status .readonly"
        output_selector = ".field-task_output_url .readonly"

        poll_interval = max(3, int(os.environ.get("EXTRACT_POLL_INTERVAL_SEC", "5")))
        max_wait = _max_wait_seconds_for_payload(payload)
        deadline = time.monotonic() + max_wait
        print(
            f"Polling until SUCCESS or FAILURE (max ~{max_wait // 60}m {max_wait % 60}s); "
            f"set EXTRACT_MAX_WAIT_SEC to override."
        )

        s3_url = None
        success_without_url = False
        while time.monotonic() < deadline:
            page.reload()
            page.wait_for_load_state("networkidle")
            status = page.inner_text(status_selector).strip() if page.is_visible(status_selector) else ""
            print(f"Status: {status or 'UNKNOWN'}")
            if status == "SUCCESS":
                task_output = page.inner_text(output_selector).strip() if page.is_visible(output_selector) else ""
                s3_url = _extract_s3_url(task_output)
                if s3_url:
                    break
                success_without_url = True
                break
            if status == "FAILURE":
                raise RuntimeError("Content loading task failed. Check task output in admin.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval, max(1.0, remaining)))

        browser.close()

    if not s3_url:
        if success_without_url:
            raise RuntimeError("Could not find input_questions_json_s3_url in task output.")
        raise RuntimeError(
            "Timed out waiting for SUCCESS (no input_questions_json_s3_url yet). "
            "For large batches, set EXTRACT_MAX_WAIT_SEC (seconds) higher, or wait and re-run."
        )

    print(f"Downloading extracted JSON from: {s3_url}")
    response = requests.get(s3_url, timeout=120)
    response.raise_for_status()
    with open(raw_output_file, "wb") as f:
        f.write(response.content)
    print(f"Saved extracted JSON: {raw_output_file}")

    with open(raw_output_file, "r", encoding="utf-8") as f:
        extracted = json.load(f)
    converted = convert(extracted)
    with open(converted_output_file, "w", encoding="utf-8") as f:
        json.dump(converted, f, indent=2)
    print(f"Saved converted coding JSON: {converted_output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract coding question content via admin and convert to coding JSON.")
    parser.add_argument("input_file", nargs="?", default="input_extract_question.json")
    parser.add_argument("--raw-output", default="extracted_coding_questions.json")
    parser.add_argument("--output", default="coding_questions_output.json")
    args = parser.parse_args()
    run(args.input_file, args.raw_output, args.output)
