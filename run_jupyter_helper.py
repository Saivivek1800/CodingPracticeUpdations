import json
import sys
import time
import os
from playwright.sync_api import sync_playwright

GOTO_TIMEOUT_MS = int(os.environ.get("JUPYTER_GOTO_TIMEOUT_MS", "60000"))
CELL_LOAD_TIMEOUT_MS = int(os.environ.get("JUPYTER_CELL_LOAD_TIMEOUT_MS", "90000"))


def pipeline_exception(step: str, detail: str, code: int = 1) -> None:
    print()
    print(">>> PIPELINE_EXCEPTION")
    print(">>>   phase:   PHASE_2_PERFORM_ACTIONS (Jupyter)")
    print(">>>   file:    run_jupyter_helper.py")
    print(f">>>   step:    {step}")
    print(f">>>   code:    {code}")
    print(f">>>   detail:  {detail}")
    sys.exit(code)


def wait_for_notebook_cells(page):
    selectors = [".jp-Cell", ".jp-Notebook .jp-Cell", ".jp-CodeCell"]
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=CELL_LOAD_TIMEOUT_MS)
            return
        except Exception:
            continue

    # Retry once after refresh; sometimes Jupyter UI assets load slowly.
    try:
        page.reload(wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
    except Exception:
        pass

    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=CELL_LOAD_TIMEOUT_MS)
            return
        except Exception:
            continue
    raise TimeoutError(f"Notebook cells did not appear within {CELL_LOAD_TIMEOUT_MS}ms")

def run_notebook(notebook_url, password):
    print("\nReading data from input_helper.json...")
    with open("input_helper.json", "r", encoding="utf-8") as f:
        data_list = json.load(f)
        
    # The debugers.ipynb needs variable 'data' set to the payload
    # The payload is already a list in input_helper.json
    payload = "data = " + json.dumps(data_list, indent=4)

    with sync_playwright() as p:
        # Running headless=True to hide the browser window. You can change it to False if you want to watch.
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        
        print(f"Navigating to Jupyter Notebook at {notebook_url}...")
        try:
            page.goto(notebook_url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        except Exception as e:
            browser.close()
            pipeline_exception(
                "page.goto(Jupyter notebook)",
                f"Cannot open {notebook_url!r} — {e}. "
                "Check VPN/firewall/network, or use SKIP_JUPYTER=1 for Django-only run.",
                1,
            )

        try:
            page.wait_for_selector("input#password_input", timeout=5000)
            print("Logging in...")
            page.fill("input#password_input", password)
            page.click("button#login_submit")
        except Exception:
            print("No password input found or already logged in.")
            
        print("Waiting for notebook cells to load...")
        try:
            wait_for_notebook_cells(page)
        except Exception as e:
            browser.close()
            pipeline_exception(
                "wait_for_selector(.jp-Cell)",
                f"Notebook UI did not load — {e}. "
                "Try increasing JUPYTER_CELL_LOAD_TIMEOUT_MS (e.g. 120000).",
                1,
            )
            
        print("Selecting cell 7 and injecting payload...")
        try:
            # Click the 7th cell editor (index 6)
            # In debugers.ipynb:
            # Cell index 0-3: setup
            # Cell index 4: helper functions
            # Cell index 6: data = [...]
            # Cell index 7: add_debug_helper_code(data) - produces output
            editor = page.locator(".jp-Cell").nth(6).locator(".cm-content")
            editor.click()
            
            # Select all text and delete
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            
            # Insert the payload
            page.keyboard.insert_text(payload)
            
            print("Triggering Kernel Restart & Run All...")
            # Click the Kernel menu
            page.click("text='Kernel'")
            
            # Click the item in the dropdown using the exact data-command for Jupyter Notebook 7
            page.wait_for_selector("li[data-command='runmenu:restart-and-run-all']", timeout=5000)
            page.click("li[data-command='runmenu:restart-and-run-all']")
            
            # The confirmation dialog has a button 'Restart'
            page.wait_for_selector("button.jp-Dialog-button.jp-mod-accept", timeout=5000)
            page.click("button.jp-Dialog-button.jp-mod-accept")
            
            print("Restart confirmed! Waiting for notebook to finish execution...")
        except Exception as e:
            browser.close()
            pipeline_exception(
                "Kernel restart / cell edit automation",
                str(e),
                1,
            )
            
        # WAIT FOR CELL 8 TO OUTPUT SUCCESS OR FAILURE
        try:
            print("Monitoring Cell 8 for the execution result (this might take up to 2 minutes depending on the script)...")
            # Cell index 7 is the 8th cell. We want to wait until it produces an output area
            output_locator = page.locator(".jp-Cell").nth(7).locator(".jp-OutputArea-output")
            
            # We will afford 120 seconds for the notebook logic to finish processing
            output_locator.first.wait_for(timeout=120000, state="attached")

            # Extract and print the result from cell 8
            output_text = output_locator.all_inner_texts()
            result_str = "\n".join(output_text).strip()
            
            print("========================================")
            print("CELL 8 EXECUTION RESULT:")
            print(result_str if result_str else "No text output returned, it might be an empty output or an object.")
            print("========================================")
            
            # Additional check: Did cell 8 have an error traceback?
            if page.locator(".jp-Cell").nth(7).locator(".jp-RenderedError").count() > 0:
                print("⚠️ WARNING: Cell 8 returned an ERROR.")
            else:
                print("✅ Successfully finished executing script.")
                
        except Exception as e:
            browser.close()
            pipeline_exception(
                "wait for cell 7 output / notebook execution",
                str(e),
                1,
            )

        print("\nProcess fully completed. Closing connection.")
        browser.close()

if __name__ == "__main__":
    url = os.environ.get("JUPYTER_URL")
    pwd = os.environ.get("JUPYTER_PASSWORD")
    
    if not url or not pwd:
        pipeline_exception(
            "environment variables",
            "Set JUPYTER_URL and JUPYTER_PASSWORD (e.g. in .secrets.env)",
            1,
        )

    run_notebook(url, pwd)
