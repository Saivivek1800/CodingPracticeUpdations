import os
import sys
import time
import argparse
import json
from playwright.sync_api import sync_playwright

from admin_playwright_util import django_admin_can_relogin_or_session, django_admin_login_credentials

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith('/'):
    ADMIN_URL += '/'

SESSION_FILE = os.environ.get("SESSION_FILE", "beta_admin_session.json")

if not django_admin_can_relogin_or_session(SESSION_FILE, admin_url=ADMIN_URL):
    print(
        f"Error: No saved session ({SESSION_FILE}) and no admin credentials in environment. "
        "Add BETA_/PROD_DJANGO_ADMIN_* to .secrets.env or secrets.local.env.",
        flush=True,
    )
    sys.exit(1)

def update_testcase_weightages(json_file):
    if not os.path.exists(json_file):
        print(f"Error: File '{json_file}' not found.")
        return

    with open(json_file, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in '{json_file}': {e}")
            return

    if not isinstance(data, dict):
        print(f"Error: JSON file must contain a dictionary mapping testcase IDs to weightages.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=SESSION_FILE) if os.path.exists(SESSION_FILE) else browser.new_context()
        page = context.new_page()

        print("Navigating to Admin...")
        try:
            page.goto(ADMIN_URL)
        except Exception as e:
            print(f"Error navigating to admin: {e}")
            return

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
                return

        for testcase_id, new_weightage in data.items():
            # Direct navigation to the edit page for that test case ID
            target_url = f"{ADMIN_URL}nkb_coding_core/testcasedetails/{testcase_id}/change/"
            print(f"Navigating directly to test case: {target_url}")
            
            page.goto(target_url)
            page.wait_for_load_state("networkidle")

            if page.locator("#id_username").count() > 0 and page.locator("#id_password").count() > 0:
                print(f"Error: Redirected to login while opening test case '{testcase_id}'.")
                print(f"Current URL: {page.url}\n")
                continue

            if "change" not in page.url or page.is_visible(".errornote"):
                print(f"Error: Could not access test case '{testcase_id}'. Are you sure the ID is correct and you have permission?")
                print(f"Current URL: {page.url}\n")
                continue

            print(f"Updating weightage to {new_weightage}...")
            try:
                # Field id differs across envs; try common ids first.
                field_selector = None
                for sel in ("#id_weightage", "#id_score", "#id_test_case_weightage"):
                    if page.locator(sel).count() > 0:
                        field_selector = sel
                        break
                if not field_selector:
                    # Last resort: locate by label text containing "weightage".
                    field_id = page.evaluate(
                        """() => {
                            for (const lb of document.querySelectorAll('label')) {
                                const t = (lb.textContent || '').toLowerCase();
                                if (t.includes('weightage')) return lb.getAttribute('for') || null;
                            }
                            return null;
                        }"""
                    )
                    if field_id:
                        field_selector = f"#{field_id}"

                if not field_selector:
                    print("Error: Could not find a weightage input field on this page.")
                    print(f"Current URL: {page.url}\n")
                    continue

                page.wait_for_selector(field_selector, timeout=5000)

                # Read current weightage just for logs
                old_weightage = page.input_value(field_selector)
                print(f"  Old weightage was: {old_weightage}")

                # Fill new weightage
                page.fill(field_selector, str(new_weightage))

                # Save the form
                print("Saving changes...")
                page.click("input[name='_save']")
                page.wait_for_load_state("networkidle")
                
                if "was changed successfully" in page.content() or "The test case details" in page.content():
                    print(f"Successfully updated weightage for Test Case '{testcase_id}' to {new_weightage}!\n")
                else:
                    print(f"Warning: Success message not detected after saving '{testcase_id}'. Please verify manually.\n")
                    
            except Exception as e:
                print(f"Error updating weightage for '{testcase_id}': {e}\n")
                
        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update weightages of multiple test cases in Django Admin from a JSON file.")
    parser.add_argument("json_file", help="Path to the JSON file containing testcase ID to weightage mappings.")
    args = parser.parse_args()
    
    update_testcase_weightages(args.json_file)
