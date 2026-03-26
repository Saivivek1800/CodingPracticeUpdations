import os
import time
import json
import requests
from playwright.sync_api import sync_playwright

ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith('/'):
    ADMIN_URL += '/'
CONTENT_LOADING_URL = ADMIN_URL + "nkb_load_data/contentloading/add/"

# Default to beta session
SESSION_FILE = os.environ.get("SESSION_FILE", "beta_admin_session.json")

def wait_for_success_and_extract(page):
    print("Stage 2: Monitoring Task Status on Detail Page...")
    status_selector = ".field-task_status .readonly"
    
    max_retries = 60 # Wait up to 5 minutes
    for i in range(max_retries):
        page.reload()
        page.wait_for_load_state("networkidle")
        
        if page.is_visible(status_selector):
            status = page.inner_text(status_selector).strip()
            print(f"Current Status: {status}")
            
            if status in ["SUCCESS", "FAILURE"]:
                print(f"Final Status: {status}")
                if status == "SUCCESS":
                    print("Fetching details from Task Output...")
                    output_selector = ".field-task_output_url .readonly"
                    try:
                        if page.is_visible(output_selector):
                            output_text = page.inner_text(output_selector).strip()
                            output_data = json.loads(output_text)
                            
                            s3_url = output_data.get("output", {}).get("input_questions_json_s3_url")
                            if s3_url:
                                print(f"Found input_questions_json_s3_url: {s3_url}")
                                print("Downloading URL...")
                                
                                response = requests.get(s3_url)
                                if response.status_code == 200:
                                    with open("extracted_coding_questions.json", "wb") as f:
                                        f.write(response.content)
                                    print("Successfully downloaded to extracted_coding_questions.json")
                                else:
                                    print(f"Failed to download URL. Status code: {response.status_code}")
                            else:
                                print("input_questions_json_s3_url not found in successful output.")
                                print(f"Output was: {output_text}")
                        else:
                            print("Task Output field not found.")
                    except Exception as e:
                        print(f"Error on success parsing: {e}")
                else:
                    print("Task FAILED. Fetching error details from Task Output...")
                    output_selector = ".field-task_output_url .readonly"
                    try:
                        if page.is_visible(output_selector):
                            output_text = page.inner_text(output_selector).strip()
                            output_data = json.loads(output_text)
                            exception_url = output_data.get("exception")
                            if exception_url:
                                error_response = requests.get(exception_url)
                                print("\n--- ERROR DETAILS ---")
                                print(error_response.text)
                                print("---------------------\n")
                    except Exception as e:
                        print(f"Error on parsing failure: {e}")
                break
            else:
                print("Task in progress... waiting 5s")
                time.sleep(5)
        else:
             print("Error: Could not find status field on page.")
             break
    else:
         print("Timeout waiting for task completion.")

def extract_content(input_data):
    task_type = "EXTRACT_CODING_QUESTION_CONTENT"
    
    if not os.path.exists(SESSION_FILE):
        print(f"Error: SESSION_FILE {SESSION_FILE} does not exist.")
        exit(1)
        
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=SESSION_FILE)
        page = context.new_page()

        print("Navigating to Admin...")
        try:
            page.goto(CONTENT_LOADING_URL)
        except Exception as e:
            print(f"Error navigating to admin: {e}")
            return

        print(f"Stage 1: Creating Content Loading Task...")
        print(f"Selecting Task Type: {task_type}")
        page.select_option("#id_task_type", task_type)
        
        print("Filling Input Data...")
        page.fill("#id_input_data", json.dumps(input_data))

        print("Submitting task (Save and continue)...")
        page.click("input[name='_continue']")
        page.wait_for_load_state("networkidle")

        if "was added successfully" in page.content() or "was changed successfully" in page.content():
            print("Task created successfully.")
            print(f"Tracking Task URL: {page.url}")
            wait_for_success_and_extract(page)
        else:
            print("Failed to submit task or verify submission. Please check if the session is still valid.")
        
        browser.close()

if __name__ == "__main__":
    import sys
    
    # Check if a file was provided as argument, else use default data
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            input_data = json.load(f)
    else:
        input_data = {
          "question_ids": [
            "6e42becb-950e-49cb-87c4-b5cbe7ba6fb1"
          ]
        }
    
    extract_content(input_data)
