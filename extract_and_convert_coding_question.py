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

        if "Log out" not in page.content():
            if USERNAME and PASSWORD:
                page.fill("#id_username", USERNAME)
                page.fill("#id_password", PASSWORD)
                page.click("input[type='submit']")
                page.wait_for_load_state("networkidle")
                context.storage_state(path=SESSION_FILE)
            else:
                raise RuntimeError("Not logged in and no DJANGO_ADMIN_USERNAME/DJANGO_ADMIN_PASSWORD provided.")

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

        s3_url = None
        for _ in range(60):
            page.reload()
            page.wait_for_load_state("networkidle")
            status = page.inner_text(status_selector).strip() if page.is_visible(status_selector) else ""
            print(f"Status: {status or 'UNKNOWN'}")
            if status == "SUCCESS":
                task_output = page.inner_text(output_selector).strip() if page.is_visible(output_selector) else ""
                s3_url = _extract_s3_url(task_output)
                break
            if status == "FAILURE":
                raise RuntimeError("Content loading task failed. Check task output in admin.")
            time.sleep(5)

        browser.close()

    if not s3_url:
        raise RuntimeError("Could not find input_questions_json_s3_url in task output.")

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
