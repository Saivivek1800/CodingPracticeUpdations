import os
import sys
import time
import argparse
import json
from playwright.sync_api import sync_playwright

from admin_playwright_util import (
    chromium_launch_args,
    django_admin_can_relogin_or_session,
    django_admin_login_credentials,
    goto_or_fail,
    new_admin_browser_context,
)

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith('/'):
    ADMIN_URL += '/'
CONTENT_LOADING_URL = ADMIN_URL + "nkb_load_data/contentloading/add/"
SESSION_FILE = os.environ.get("SESSION_FILE", "admin_session.json")

if not django_admin_can_relogin_or_session(SESSION_FILE, admin_url=ADMIN_URL):
    print(
        f"Error: No saved session ({SESSION_FILE}) and no admin credentials in environment. "
        "Add BETA_/PROD_DJANGO_ADMIN_* to .secrets.env or secrets.local.env.",
        flush=True,
    )
    sys.exit(1)

def run_description_updater(json_file):
    if not os.path.exists(json_file):
        print(f"Error: {json_file} not found.")
        sys.exit(1)

    # Ensure absolute path for file upload
    abs_json_file = os.path.abspath(json_file)

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_args())
        context = new_admin_browser_context(browser, SESSION_FILE)
        page = context.new_page()

        goto_or_fail(page, ADMIN_URL, script="auto_description_updater.py")

        if "Log out" not in page.content():
            print("Logging in...")
            user, pwd = django_admin_login_credentials(ADMIN_URL)
            if user and pwd:
                page.fill("#id_username", user)
                page.fill("#id_password", pwd)
                page.click("input[type='submit']")
                page.wait_for_load_state("networkidle")
                context.storage_state(path=SESSION_FILE)
            else:
                print("Error: Not logged in and no credentials provided to login. Please provide credentials or a valid session file.")
                browser.close()
                print()
                print(">>> PIPELINE_EXCEPTION")
                print(">>>   script:  auto_description_updater.py")
                print(">>>   step:    login (session expired?)")
                sys.exit(1)

        # --- Stage 1: Read File Content (No Upload) ---
        print(f"Reading File '{json_file}'...")
        with open(abs_json_file, 'r') as f:
            file_content = f.read()
        
        # Validate that it is valid JSON (optional but good for safety)
        try:
            json_data = json.loads(file_content)
            # Basic validation for expected structure
            if "question_data" not in json_data:
                print("Warning: Input JSON does not container 'question_data' key. Proceeding anyway but check structure.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {json_file}: {e}")
            browser.close()
            sys.exit(1)

        # --- Stage 2: Create Content Loading Task ---
        print("Stage 2: Creating Content Loading Task (UPDATE_QUESTION_CONTENT)...")
        try:
            page.goto(
                CONTENT_LOADING_URL,
                wait_until="domcontentloaded",
                timeout=int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000")),
            )
            page.wait_for_load_state("networkidle")
        except Exception as e:
            browser.close()
            print()
            print(">>> PIPELINE_EXCEPTION")
            print(">>>   script:  auto_description_updater.py")
            print(">>>   step:    page.goto(CONTENT_LOADING_URL)")
            print(f">>>   detail:  {e}")
            sys.exit(1)

        # Set Task Type to UPDATE_QUESTION_CONTENT.
        # In some prod accounts, add page may be inaccessible or a different form.
        task_type_loc = page.locator("#id_task_type")
        if task_type_loc.count() == 0:
            print("SKIP: Content loading task form not available (#id_task_type missing).")
            print("  Likely no permission in this environment/account; skipping description updater.")
            browser.close()
            return
        page.select_option("#id_task_type", "UPDATE_QUESTION_CONTENT")
        
        # Fill Input Data with raw JSON content
        print("Filling input data with file content...")
        page.fill("#id_input_data", file_content)

        # Submit - Use 'Save and continue editing' to stay on the page and get the specific task ID
        print("Submitting task (Save and continue)...")
        page.click("input[name='_continue']")
        page.wait_for_load_state("networkidle")

        if "was added successfully" in page.content() or "was changed successfully" in page.content():
            print("Task created/updated successfully.")
            print(f"Tracking Task URL: {page.url}")
        else:
            print("Warning: Success message not found.")

        # --- Stage 3: Monitor Task Status ---
        print("Stage 3: Monitoring Task Status on Detail Page...")
        
        # Selector for the status field (readonly div in the form)
        status_selector = ".field-task_status .readonly"
        
        max_retries = 60 # Wait up to 5 minutes
        for i in range(max_retries):
            # Reload to check status updates
            page.reload()
            page.wait_for_load_state("networkidle")
            
            if page.is_visible(status_selector):
                status = page.inner_text(status_selector).strip()
                print(f"Current Status: {status}")
                
                if status in ["SUCCESS", "FAILURE"]:
                    print(f"Final Status: {status}")
                    
                    if status == "SUCCESS":
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

                    if status == "FAILURE":
                        print("Fetching error details from Task Output...")
                        
                        # The output seems to be a JSON string inside the readonly div, not a direct link.
                        output_selector = ".field-task_output_url .readonly"
                        
                        try:
                            if page.is_visible(output_selector):
                                output_text = page.inner_text(output_selector).strip()
                                print(f"Raw Output Text: {output_text}")
                                
                                try:
                                    output_data = json.loads(output_text)
                                    # Users wants the exception or output link content
                                    exception_url = output_data.get("exception")
                                    output_url = output_data.get("output")
                                    
                                    target_url = exception_url if exception_url else output_url
                                    
                                    if target_url:
                                        print(f"Fetching content from: {target_url}")
                                        # Fetch the content of the URL using the browser context
                                        error_content = page.evaluate(f"async () => {{ const response = await fetch('{target_url}'); return await response.text(); }}")
                                        print("\n--- ERROR DETAILS ---")
                                        print(error_content)
                                        print("---------------------\n")
                                    else:
                                        print("No exception or output URL found in the task output data.")
                                        
                                except json.JSONDecodeError:
                                    print("Failed to parse output text as JSON.")
                                    print(f"Content: {output_text}")
                            else:
                                print("Could not find Task Output URL field on the page.")
                                # Fallback to dumping if still failing to find it
                                # print("Saving page content to debug_failure.html...")
                                # with open("debug_failure.html", "w") as f: f.write(page.content())
                        except Exception as e:
                            print(f"Error extracting error details: {e}")

                    break
                else:
                    print("Task in progress... waiting 5s")
                    time.sleep(5)
            else:
                 print("Error: Could not find status field on page.")
                 break
        else:
             print("Timeout waiting for task completion.")

        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate Description Update Task")
    parser.add_argument("json_file", help="Path to the user input JSON file")
    args = parser.parse_args()
    
    run_description_updater(args.json_file)
