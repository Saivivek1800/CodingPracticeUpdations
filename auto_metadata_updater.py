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
QUESTION_CHANGE_URL_TEMPLATE = ADMIN_URL + "nkb_question/question/{}/change/"
SESSION_FILE = os.environ.get("SESSION_FILE", "admin_session.json")


def run_metadata_updater(json_file):
    if not django_admin_can_relogin_or_session(SESSION_FILE, admin_url=ADMIN_URL):
        print(
            f"Error: No saved session ({SESSION_FILE}) and no admin credentials in environment. "
            "Add BETA_/PROD_DJANGO_ADMIN_* to .secrets.env or secrets.local.env.",
            flush=True,
        )
        sys.exit(1)
    if not os.path.exists(json_file):
        print(f"Error: {json_file} not found.")
        sys.exit(1)

    # Ensure absolute path for file upload logic if needed (not needed here but good practice)
    abs_json_file = os.path.abspath(json_file)

    with open(abs_json_file, 'r') as f:
        try:
            input_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {json_file}: {e}")
            sys.exit(1)

    question_data = input_data.get("question_data", {})
    if not question_data:
        print("Error: 'question_data' key not found or empty in input JSON.")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_args())
        context = new_admin_browser_context(browser, SESSION_FILE)
        page = context.new_page()

        goto_or_fail(page, ADMIN_URL, script="auto_metadata_updater.py")

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
                print(">>>   script:  auto_metadata_updater.py")
                print(">>>   step:    login (session expired?)")
                sys.exit(1)

        # Iterate through questions
        for question_id, metadata_str in question_data.items():
            print(f"\nProcessing Question ID: {question_id}")
            
            target_url = QUESTION_CHANGE_URL_TEMPLATE.format(question_id)
            print(f"Navigating to: {target_url}")
            
            try:
                page.goto(target_url)
                page.wait_for_load_state("networkidle")
            except Exception as e:
                 print(f"Error navigating to question page: {e}")
                 continue

            if "history" not in page.url: # Check if redirected to list or something else indicating ID not found? 
                # Django admin redirects to list if ID not found usually with a message.
                # Or returns 404. Playwright might throw error on 404? 
                # Let's check if we are on the change page.
                pass

            # Check if metadata field exists
            # Common selectors for django admin textual fields
            metadata_selector = "#id_metadata" 
            
            if not page.is_visible(metadata_selector):
                print(f"Error: Metadata field ({metadata_selector}) not found for question {question_id}.")
                # Debug dump
                # with open(f"debug_q_{question_id}.html", "w") as f: f.write(page.content())
                continue

            # Parse the stringified metadata to pretty print it
            try:
                if isinstance(metadata_str, str):
                    metadata_json = json.loads(metadata_str)
                else:
                    metadata_json = metadata_str # Already json?
                
                formatted_metadata = json.dumps(metadata_json, indent=4)
            except json.JSONDecodeError:
                print(f"Warning: Metadata for {question_id} is not valid JSON string. Using as is.")
                formatted_metadata = metadata_str

            print("Updating metadata field...")
            # We specifically target #id_metadata
            page.fill(metadata_selector, formatted_metadata)

            print("Saving...")
            page.click("input[name='_save']") # Save and go back to list (or wherever)
            page.wait_for_load_state("networkidle")

            if "was changed successfully" in page.content():
                print(f"SUCCESS: Metadata updated for {question_id}")
            else:
                print(f"FAILURE: Could not verify success for {question_id}")
                # Check for errors
                if page.is_visible(".errornote"):
                    print(f"Error Note: {page.inner_text('.errornote')}")
                if page.is_visible(".errorlist"):
                    print(f"Field Errors: {page.inner_text('.errorlist')}")

        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate Metadata Update Task")
    parser.add_argument("json_file", help="Path to the user input JSON file")
    args = parser.parse_args()
    
    run_metadata_updater(args.json_file)
