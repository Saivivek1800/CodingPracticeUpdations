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

def run_content_loader(json_file, task_type):
    if not os.path.exists(json_file): # Fixed check to use start with exists
        print(f"Error: {json_file} not found.")
        sys.exit(1)

    # Ensure absolute path for file upload
    abs_json_file = os.path.abspath(json_file)

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_args())
        context = new_admin_browser_context(browser, SESSION_FILE)
        page = context.new_page()

        goto_or_fail(page, ADMIN_URL, script="auto_content_loader.py")

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
                browser.close()
                print()
                print(">>> PIPELINE_EXCEPTION")
                print(">>>   script:  auto_content_loader.py")
                print(">>>   step:    login (session expired?)")
                sys.exit(1)

        # --- Stage 1: Upload File ---
        print(f"Stage 1: Uploading File '{json_file}'...")
        page.goto(UPLOAD_FILE_URL)
        page.wait_for_load_state("networkidle")

        # Upload file to the input
        input_selector = "#id_file_url_tmp"
        
        if not page.is_visible(input_selector):
             print(f"Error: File input selector {input_selector} not found.")
             browser.close()
             return

        page.set_input_files(input_selector, abs_json_file)
        
        # Wait for the upload to complete. 
        print("Waiting for upload to complete...")
        
        try:
            # Wait for the populated value in the hidden/readonly input
            page.wait_for_function("document.getElementById('id_file_url').value.startsWith('http')", timeout=120000)
        except Exception as e:
            print("Error waiting for upload (timeout):", e)
            browser.close()
            return

        s3_url = page.input_value("#id_file_url")
        print(f"Upload successful. S3 URL: {s3_url}")

        # --- Stage 2: Create Content Loading Task ---
        print("Stage 2: Creating Content Loading Task...")
        page.goto(CONTENT_LOADING_URL)
        page.wait_for_load_state("networkidle")

        # Set Task Type to the provided argument
        print(f"Selecting Task Type: {task_type}")
        page.select_option("#id_task_type", task_type)
        
        # Fill Input Data with S3 URL wrapped in JSON
        input_data_json = json.dumps({"input_json_file_s3_url": s3_url})
        page.fill("#id_input_data", input_data_json)

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
        # Based on previous inspection, it was: <div class="form-row field-task_status"> ... <div class="readonly">IN_PROGRESS</div> ...
        status_selector = ".field-task_status .readonly"
        
        max_retries = 60 # Wait up to 5 minutes (5s * 60)
        for i in range(max_retries):
            # Reload to check status updates
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
                                        error_content = page.evaluate(f"async () => {{ const response = await fetch('{target_url}'); return await response.text(); }}")
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
                        # --- Stage 4: Cache Invalidation ---
                        try:
                            print("Navigating to create Cache Invalidation task...")
                            page.goto(CONTENT_LOADING_URL)
                            page.wait_for_load_state("networkidle")
                            
                            print("Selecting Task Type: CACHE_INVALIDATION")
                            page.select_option("#id_task_type", "CACHE_INVALIDATION")
                            
                            # Cache invalidation input data
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

        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate Content Loading Task")
    parser.add_argument("json_file", help="Path to the user input JSON file")
    parser.add_argument("--task-type", default="UPDATE_EXISTING_TESTCASES", help="Type of task to perform (default: UPDATE_EXISTING_TESTCASES)")
    args = parser.parse_args()
    
    run_content_loader(args.json_file, args.task_type)
