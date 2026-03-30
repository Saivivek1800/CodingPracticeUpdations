import os
import sys
import time
import argparse
import json
from playwright.sync_api import sync_playwright

from admin_playwright_util import (
    chromium_launch_args,
    goto_or_fail,
    new_admin_browser_context,
)

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith('/'):
    ADMIN_URL += '/'
UPLOAD_FILE_URL = ADMIN_URL + "nkb_load_data/uploadfile/add/"
CONTENT_LOADING_URL = ADMIN_URL + "nkb_load_data/contentloading/add/"
CONTENT_LOADING_LIST_URL = ADMIN_URL + "nkb_load_data/contentloading/"
USERNAME = os.environ.get("DJANGO_ADMIN_USERNAME")
PASSWORD = os.environ.get("DJANGO_ADMIN_PASSWORD")

SESSION_FILE = os.environ.get("SESSION_FILE", "admin_session.json")

if not USERNAME or not PASSWORD:
    if not os.path.exists(SESSION_FILE):
        print(f"Error: DJANGO_ADMIN_USERNAME and DJANGO_ADMIN_PASSWORD environment variables must be set (no {SESSION_FILE} found).")
        exit(1)

def run_code_updater(json_file):
    if not os.path.exists(json_file):
        print(f"Error: {json_file} not found.")
        sys.exit(1)

    # Ensure absolute path for file upload
    abs_json_file = os.path.abspath(json_file)

    with sync_playwright() as p:
        try:
            print("Playwright: launching Chromium...", flush=True)
            browser = p.chromium.launch(**chromium_launch_args())
            print(f"Playwright: loading session / context ({SESSION_FILE})...", flush=True)
            context = new_admin_browser_context(browser, SESSION_FILE)
            page = context.new_page()
            goto_or_fail(page, ADMIN_URL, script="auto_code_updater.py")
        except SystemExit:
            raise
        except BaseException as boot_err:
            import traceback

            traceback.print_exc()
            print()
            print(">>> PIPELINE_EXCEPTION")
            print(">>>   phase:   PHASE_2_PERFORM_ACTIONS (Django admin)")
            print(">>>   script:  auto_code_updater.py")
            print(">>>   step:    Playwright launch or context (before page.goto)")
            print(f">>>   detail:  {boot_err}")
            sys.exit(1)

        try:

            if "Log out" not in page.content():
                print("Logging in...")
                if USERNAME and PASSWORD:
                    page.fill("#id_username", USERNAME)
                    page.fill("#id_password", PASSWORD)
                    page.click("input[type='submit']")
                    page.wait_for_load_state("networkidle")
                    context.storage_state(path=SESSION_FILE)
                else:
                    print("Error: Not logged in and no credentials provided to login. Please provide credentials or a valid session file.")
                    print()
                    print(">>> PIPELINE_EXCEPTION")
                    print(">>>   phase:   PHASE_2_PERFORM_ACTIONS (Django admin)")
                    print(">>>   script:  auto_code_updater.py")
                    print(">>>   step:    login (session expired?)")
                    print(">>>   detail:  Need DJANGO_ADMIN_USERNAME/PASSWORD or refresh beta_admin_session.json")
                    sys.exit(1)

            # --- Stage 1: Read File Content (No Upload) ---
            print(f"Reading File '{json_file}'...")
            with open(abs_json_file, "r", encoding="utf-8") as f:
                file_content = f.read()

            try:
                json.loads(file_content)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON in {json_file}: {e}")
                print()
                print(">>> PIPELINE_EXCEPTION")
                print(">>>   script:  auto_code_updater.py")
                print(">>>   step:    validate input JSON")
                sys.exit(1)

            # --- Stage 2: Create Content Loading Task ---
            print("Stage 2: Creating Content Loading Task (UPDATE_CODE_CONTENT)...")
            try:
                page.goto(
                    CONTENT_LOADING_URL,
                    wait_until="domcontentloaded",
                    timeout=int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000")),
                )
                page.wait_for_load_state("networkidle")
            except Exception as e:
                print()
                print(">>> PIPELINE_EXCEPTION")
                print(">>>   script:  auto_code_updater.py")
                print(">>>   step:    page.goto(CONTENT_LOADING_URL)")
                print(f">>>   detail:  {e}")
                sys.exit(1)

            # Set Task Type to UPDATE_CODE_CONTENT.
            # In some prod accounts, add page may be inaccessible or a different form.
            task_type_loc = page.locator("#id_task_type")
            if task_type_loc.count() == 0:
                print("SKIP: Content loading task form not available (#id_task_type missing).")
                print("  Likely no permission in this environment/account; skipping code updater.")
                return
            page.select_option("#id_task_type", "UPDATE_CODE_CONTENT")

            print("Filling input data with file content...")
            page.fill("#id_input_data", file_content)

            print("Submitting task (Save and continue)...")
            page.click("input[name='_continue']")
            page.wait_for_load_state("networkidle")

            if "was added successfully" in page.content() or "was changed successfully" in page.content():
                print("Task created/updated successfully.")
                print(f"Tracking Task URL: {page.url}")
            else:
                print("Warning: Success message not found.")

            print("Stage 3: Monitoring Task Status on Detail Page...")
            status_selector = ".field-task_status .readonly"
            max_retries = 60
            for i in range(max_retries):
                page.reload()
                page.wait_for_load_state("networkidle")

                if page.is_visible(status_selector):
                    status = page.inner_text(status_selector).strip()
                    print(f"Current Status: {status}")

                    if status in ["SUCCESS", "FAILURE"]:
                        print(f"Final Status: {status}")

                        if status == "FAILURE":
                            print("Fetching error details from Task Output...")
                            output_selector = ".field-task_output_url .readonly"
                            try:
                                if page.is_visible(output_selector):
                                    output_text = page.inner_text(output_selector).strip()
                                    try:
                                        output_data = json.loads(output_text)
                                        exception_url = output_data.get("exception")
                                        output_url = output_data.get("output")
                                        target_url = exception_url if exception_url else output_url

                                        if target_url:
                                            print(f"Fetching content from: {target_url}")
                                            error_content = page.evaluate(
                                                f"async () => {{ const response = await fetch('{target_url}'); return await response.text(); }}"
                                            )
                                            print("\n--- ERROR DETAILS ---")
                                            print(error_content)
                                            print("---------------------\n")
                                        else:
                                            print("No exception or output URL found in the task output data.")
                                    except json.JSONDecodeError:
                                        print(f"Failed to parse output text as JSON: {output_text}")
                                else:
                                    print("Could not find Task Output URL field on the page.")
                            except Exception as e:
                                print(f"Error extracting error details: {e}")

                        elif status == "SUCCESS":
                            print("Primary task completed successfully. Initiating Cache Invalidation...")
                            try:
                                print("Navigating to create Cache Invalidation task...")
                                page.goto(CONTENT_LOADING_URL)
                                page.wait_for_load_state("networkidle")
                                print("Selecting Task Type: CACHE_INVALIDATION")
                                page.select_option("#id_task_type", "CACHE_INVALIDATION")
                                page.fill("#id_input_data", "{}")
                                print("Submitting Cache Invalidation task...")
                                page.click("input[name='_save']")
                                page.wait_for_load_state("networkidle")
                                if "was added successfully" in page.content():
                                    print("Cache Invalidation task created successfully.")
                                else:
                                    print("Warning: Cache Invalidation task creation success message not found.")
                            except Exception as e:
                                print(f"Error creating Cache Invalidation task: {e}")

                        break
                    else:
                        print("Task in progress... waiting 5s")
                        time.sleep(5)
                else:
                    print("Error: Could not find status field on page.")
                    break
            else:
                print("Timeout waiting for task completion.")
        finally:
            try:
                browser.close()
            except Exception:
                pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate Code Content Update Task")
    parser.add_argument("json_file", help="Path to the user input JSON file")
    args = parser.parse_args()
    
    run_code_updater(args.json_file)
