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
    print(">>>   file:    run_jupyter_base64.py")
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
    print("\nReading data from input_base64.json...")
    with open("input_base64.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        
    payload = "question_code_repository_data = " + json.dumps(data, indent=4)

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
            
        print("Updating cell 6/7 and triggering a single restart-run-all...")
        try:
            # Click the 6th cell editor (index 5)
            editor = page.locator(".jp-Cell").nth(5).locator(".cm-content")
            editor.click()
            
            # Select all text and delete
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            
            # Insert payload in cell 6
            page.keyboard.insert_text(payload)

            # Edit cell 7 before triggering run-all so we do only one kernel restart.
            cell7 = page.locator(".jp-Cell").nth(6)
            cell7.locator(".cm-content").click()
            
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.insert_text("print(update_question_to_user_function_evaluation(question_code_repository_data))")

            print("Triggering Kernel Restart & Run All...")
            page.click("text='Kernel'")
            page.wait_for_selector("li[data-command='runmenu:restart-and-run-all']", timeout=5000)
            page.click("li[data-command='runmenu:restart-and-run-all']")
            page.wait_for_selector("button.jp-Dialog-button.jp-mod-accept", timeout=5000)
            page.click("button.jp-Dialog-button.jp-mod-accept")
            
            print("Restart confirmed! Waiting for notebook to finish execution...")
            
            # Wait for cell 7's output area
            output_locator = page.locator(".jp-Cell").nth(6).locator(".jp-OutputArea-output")
            output_locator.first.wait_for(timeout=180000, state="attached")

            cells = page.locator(".jp-Cell")
            count = cells.count()
            
            print("========================================")
            print("NOTEBOOK EXECUTION RESULTS (CELL 7+):")
            
            for i in range(6, count):
                cell = cells.nth(i)
                output_area = cell.locator(".jp-OutputArea-output")
                
                if output_area.count() > 0:
                    texts = output_area.all_inner_texts()
                    result = "\n".join(texts).strip()
                    if result:
                        print(f"\n--- CELL {i+1} OUTPUT ---")
                        print(result)
                
                # Check for errors
                if cell.locator(".jp-RenderedError").count() > 0:
                    print(f"\n⚠️ WARNING: Cell {i+1} returned an ERROR.")
                    error_text = cell.locator(".jp-RenderedError").all_inner_texts()
                    print("\n".join(error_text))
            
            print("\n========================================")
            print("✅ Successfully finished collecting outputs.")
                
        except Exception as e:
            browser.close()
            pipeline_exception(
                "notebook execution monitoring / cell output",
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
