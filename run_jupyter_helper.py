import json
import os
import re
import sys
import time
from pathlib import Path
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


def _notebook_code_cells(page):
    """Code cells only — .jp-Cell includes markdown/output and breaks nth() indexing."""
    loc = page.locator(".jp-Notebook .jp-CodeCell")
    if loc.count() == 0:
        loc = page.locator(".jp-CodeCell")
    return loc


def _cm_preview_text(cell_locator, timeout_ms: int = 3000) -> str:
    ed = cell_locator.locator(".cm-content").first
    if ed.count() == 0:
        return (cell_locator.inner_text(timeout=timeout_ms) or "").strip()
    try:
        return (ed.inner_text(timeout=timeout_ms) or "").strip()
    except Exception:
        return ""


def _find_helper_data_code_cell_index(page) -> int:
    cells = _notebook_code_cells(page)
    n = cells.count()
    if n == 0:
        pipeline_exception(
            "notebook structure",
            "No .jp-CodeCell found — is this JupyterLab / Notebook 7?",
            1,
        )
    env_i = os.environ.get("JUPYTER_HELPER_DATA_CODE_CELL_INDEX")
    if env_i is not None and str(env_i).isdigit():
        return min(int(env_i), n - 1)
    for i in range(min(n, 40)):
        t = _cm_preview_text(cells.nth(i))
        if t and re.search(r"\bdata\s*=", t):
            print(f"Located `data =` payload cell: code cell index {i} (0-based).")
            return i
    # 1-based "cell 6" in the notebook = 0-based index 5 among code cells only.
    fallback = min(5, n - 1)
    print(
        f"Warning: no cell matched `data =` in first {min(n, 40)} code cells; "
        f"using fallback code cell index {fallback} (notebook cell 6, 1-based). "
        "Set JUPYTER_HELPER_DATA_CODE_CELL_INDEX to override."
    )
    return fallback


def _find_helper_output_code_cell_index(page, data_idx: int) -> int:
    cells = _notebook_code_cells(page)
    n = cells.count()
    env_i = os.environ.get("JUPYTER_HELPER_OUTPUT_CODE_CELL_INDEX")
    if env_i is not None and str(env_i).isdigit():
        return min(int(env_i), n - 1)
    for i in range(data_idx + 1, min(n, 40)):
        t = _cm_preview_text(cells.nth(i))
        if t and "add_debug_helper_code" in t:
            print(f"Located helper runner cell: code cell index {i}.")
            return i
    out = min(data_idx + 1, n - 1)
    print(f"Using code cell index {out} for output (next after data cell).")
    return out


def _replace_code_cell_editor(page, cells, cell_index: int, new_source: str) -> None:
    editor = cells.nth(cell_index).locator(".cm-content").first
    editor.wait_for(state="visible", timeout=20000)
    editor.scroll_into_view_if_needed()
    editor.click()
    time.sleep(0.2)
    page.keyboard.press("Control+a")
    time.sleep(0.05)
    page.keyboard.press("Backspace")
    time.sleep(0.05)
    # Large payloads: insert in chunks (insert_text is reliable but can be slow)
    chunk = 12000
    for start in range(0, len(new_source), chunk):
        page.keyboard.insert_text(new_source[start : start + chunk])
        time.sleep(0.01)
    time.sleep(0.2)


def run_notebook(notebook_url, password):
    input_path = Path("input_helper.json").resolve()
    print(f"\nReading helper payload from this machine: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        data_list = json.load(f)
    _n = len(data_list) if isinstance(data_list, list) else 0
    print(f"Loaded {_n} item(s); injecting into the remote notebook as Python variable `data` (code cell with `data =`).")
    # LoadHelperCode_to_FunctionBased.ipynb (beta default) expects variable 'data' set to the payload
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
            
        print("Selecting code cell with `data =` and injecting payload from JSON...")
        try:
            cells = _notebook_code_cells(page)
            data_cell_i = _find_helper_data_code_cell_index(page)
            _replace_code_cell_editor(page, cells, data_cell_i, payload)
            output_cell_i = _find_helper_output_code_cell_index(page, data_cell_i)
            
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
            
        # WAIT FOR OUTPUT CODE CELL (DOM reloads after restart — wait then re-resolve indices)
        try:
            wait_for_notebook_cells(page)
            cells = _notebook_code_cells(page)
            data_cell_i = _find_helper_data_code_cell_index(page)
            output_cell_i = _find_helper_output_code_cell_index(page, data_cell_i)
            print(
                f"Monitoring code cell {output_cell_i + 1} (0-based index {output_cell_i}) for execution result "
                "(this might take up to 2 minutes depending on the script)..."
            )
            output_locator = cells.nth(output_cell_i).locator(".jp-OutputArea-output")
            
            # We will afford 120 seconds for the notebook logic to finish processing
            output_locator.first.wait_for(timeout=120000, state="attached")

            # Extract and print the result from cell 8
            output_text = output_locator.all_inner_texts()
            result_str = "\n".join(output_text).strip()
            
            print("========================================")
            print("HELPER NOTEBOOK EXECUTION RESULT:")
            print(result_str if result_str else "No text output returned, it might be an empty output or an object.")
            print("========================================")
            print(
                "Note: Lines above are printed by the **remote** Jupyter kernel (paths like /home/ubuntu/... are on the "
                "notebook server). Your `data` still came from this PC:"
            )
            print(f"  {input_path}")
            
            if cells.nth(output_cell_i).locator(".jp-RenderedError").count() > 0:
                print("⚠️ WARNING: Output code cell returned an ERROR.")
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
