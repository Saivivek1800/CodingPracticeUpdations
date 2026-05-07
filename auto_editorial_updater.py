import os
import time
import argparse
import json
from playwright.sync_api import sync_playwright

from admin_playwright_util import django_admin_can_relogin_or_session, django_admin_login_credentials

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith('/'):
    ADMIN_URL += '/'
LEARNING_RESOURCE_CHANGE_URL_TEMPLATE = ADMIN_URL + "nkb_learning_resource/learningresource/{}/change/"

SESSION_FILE = os.environ.get("SESSION_FILE", "admin_session.json")


def _require_login_or_session() -> None:
    if django_admin_can_relogin_or_session(SESSION_FILE, admin_url=ADMIN_URL):
        return
    print(
        f"Error: No saved session ({SESSION_FILE}) and no admin credentials in environment. "
        "Add BETA_/PROD_DJANGO_ADMIN_* to .secrets.env or secrets.local.env.",
        flush=True,
    )
    raise SystemExit(1)

def run_editorial_updater(json_file):
    _require_login_or_session()

    if not os.path.exists(json_file):
        print(f"Error: {json_file} not found.")
        return

    abs_json_file = os.path.abspath(json_file)

    with open(abs_json_file, 'r') as f:
        try:
            input_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {json_file}: {e}")
            return

    # User mentioned: "I will give input like this \n { \"id \":\"content\" }"
    # So we assume the main JSON is a dictionary of ID -> content
    # If the user wraps it in a "learning_resource_data" key, we handle that as well.
    if "learning_resource_data" in input_data:
        items_to_update = input_data["learning_resource_data"]
    else:
        # Otherwise, assume the root object is the dict map
        items_to_update = input_data

    if not items_to_update or not isinstance(items_to_update, dict):
        print("Error: No valid data found in input JSON. File should be a dictionary of { 'id': 'content' }.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=SESSION_FILE) if os.path.exists(SESSION_FILE) else browser.new_context()
        page = context.new_page()

        # Login if needed
        print("Navigating to Admin...")
        try:
            page.goto(ADMIN_URL)
        except Exception as e:
            print(f"Error navigating to admin: {e}")
            return

        if "Log out" not in page.content():
            print(f"Current URL: {page.url}")
            print("Logging in...")
            user, pwd = django_admin_login_credentials(ADMIN_URL)
            if user and pwd:
                page.fill("#id_username", user)
                page.fill("#id_password", pwd)
                page.click("input[type='submit']")
                page.wait_for_load_state("networkidle")
                context.storage_state(path=SESSION_FILE)
            else:
                print(
                    "Error: Session expired and no credentials for re-login. "
                    "Add PROD_DJANGO_ADMIN_USERNAME/PASSWORD (prod) or BETA_* (beta) to .secrets.env, "
                    "or set SECRETS_DECRYPTION_KEY / .secrets.key for .secrets.enc.",
                    flush=True,
                )
                browser.close()
                return

        for resource_id, content_str in items_to_update.items():
            resource_id = resource_id.strip() # in case user said "id " 
            print(f"\nProcessing Learning Resource ID: {resource_id}")
            
            target_url = LEARNING_RESOURCE_CHANGE_URL_TEMPLATE.format(resource_id)
            print(f"Navigating to: {target_url}")
            
            try:
                page.goto(target_url)
                page.wait_for_load_state("networkidle")
            except Exception as e:
                 print(f"Error navigating to page: {e}")
                 continue

            if "was not found" in page.content() or "doesn't exist" in page.content():
                print(f"Error: Learning Resource with ID {resource_id} not found.")
                continue

            # Check if editorial/tutorial field exists
            # We try several likely selectors. 
            field_selectors = ["#id_editorial", "#id_tutorial", "#id_content"]
            active_selector = None
            
            for selector in field_selectors:
                if page.is_visible(selector):
                    active_selector = selector
                    break
            
            if not active_selector:
                print(f"Error: Could not find any editorial/tutorial field for resource {resource_id}. Checked: {field_selectors}")
                continue

            # Unstringify: handle user's intent. If it's a JSON stringified string, we can parse and re-dump, 
            # or just unescape by using json.loads if they literally meant double-encoded string.
            try:
                if isinstance(content_str, str):
                    # Attempt to parse json structure (if they passed stringified JSON/HTML and want it extracted)
                    # Many times stringified data in JSON when loaded is just a string.
                    # If they want it formatting or further unstringified:
                    try:
                        parsed_content = json.loads(content_str)
                        if isinstance(parsed_content, (dict, list)):
                            formatted_content = json.dumps(parsed_content, indent=4)
                        else:
                            # It was a string inside a JSON string
                            formatted_content = str(parsed_content)
                    except json.JSONDecodeError:
                        formatted_content = content_str # Not a json string, just use as is
                else:
                    # It's an object/array already, convert to pretty JSON
                    formatted_content = json.dumps(content_str, indent=4)
            except Exception as e:
                print(f"Warning: Issue unstringifying for {resource_id}: {e}")
                formatted_content = str(content_str)

            print(f"Updating field {active_selector}...")
            # We target the identified field
            page.fill(active_selector, formatted_content)

            # Check if there is also an English translation field
            if page.is_visible("#id_content_en"):
                print("Updating field #id_content_en...")
                page.fill("#id_content_en", formatted_content)

            print("Saving...")
            page.click("input[name='_save']") 
            page.wait_for_load_state("networkidle")

            if "was changed successfully" in page.content():
                print(f"SUCCESS: Editorial/Tutorial updated for {resource_id}")
            else:
                print(f"FAILURE: Could not verify success for {resource_id}")
                if page.is_visible(".errornote"):
                    print(f"Error Note: {page.inner_text('.errornote')}")
                if page.is_visible(".errorlist"):
                    print(f"Field Errors: {page.inner_text('.errorlist')}")

        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate Editorial/Tutorial Update Task")
    parser.add_argument("json_file", help="Path to the input JSON file containing IDs mapping to content")
    args = parser.parse_args()
    
    run_editorial_updater(args.json_file)
