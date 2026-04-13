"""Playwright driver for the base64 notebook: reads only input_base64.json (written by generate_base64_input.py)."""
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


def _notebook_code_cells(page):
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


def _find_base64_data_code_cell_index(page) -> int:
    cells = _notebook_code_cells(page)
    n = cells.count()
    if n == 0:
        pipeline_exception(
            "notebook structure",
            "No .jp-CodeCell found — is this JupyterLab / Notebook 7?",
            1,
        )
    env_i = os.environ.get("JUPYTER_BASE64_DATA_CODE_CELL_INDEX")
    if env_i is not None and str(env_i).isdigit():
        return min(int(env_i), n - 1)
    for i in range(min(n, 40)):
        t = _cm_preview_text(cells.nth(i))
        if t and re.search(r"\bquestion_code_repository_data\s*=", t):
            print(f"Located `question_code_repository_data =` cell: code cell index {i}.")
            return i
    fb = min(5, n - 1)
    print(
        f"Warning: no cell matched `question_code_repository_data =`; using fallback index {fb}. "
        "Set JUPYTER_BASE64_DATA_CODE_CELL_INDEX to override."
    )
    return fb


def _find_base64_runner_code_cell_index(page, data_idx: int) -> int:
    cells = _notebook_code_cells(page)
    n = cells.count()
    env_i = os.environ.get("JUPYTER_BASE64_RUNNER_CODE_CELL_INDEX")
    if env_i is not None and str(env_i).isdigit():
        return min(int(env_i), n - 1)
    for i in range(min(n, 40)):
        t = _cm_preview_text(cells.nth(i))
        if t and "update_question_to_user_function_evaluation" in t:
            print(f"Located base64 runner cell: code cell index {i}.")
            return i
    out = min(data_idx + 1, n - 1)
    print(f"Using code cell index {out} for runner (next after data cell).")
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
    chunk = 12000
    for start in range(0, len(new_source), chunk):
        page.keyboard.insert_text(new_source[start : start + chunk])
        time.sleep(0.01)
    time.sleep(0.2)


def run_notebook(notebook_url, password):
    input_path = Path("input_base64.json").resolve()
    print(f"\nReading base64 payload from this machine: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _n = len(data) if isinstance(data, list) else 0
    print(f"Loaded {_n} item(s); injecting into the remote notebook as `question_code_repository_data`.")
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
            
        print("Locating base64 data / runner code cells and injecting from input_base64.json...")
        try:
            cells = _notebook_code_cells(page)
            data_i = _find_base64_data_code_cell_index(page)
            _replace_code_cell_editor(page, cells, data_i, payload)
            runner_i = _find_base64_runner_code_cell_index(page, data_i)
            runner_src = "print(update_question_to_user_function_evaluation(question_code_repository_data))"
            _replace_code_cell_editor(page, cells, runner_i, runner_src)

            print("Triggering Kernel Restart & Run All...")
            page.click("text='Kernel'")
            page.wait_for_selector("li[data-command='runmenu:restart-and-run-all']", timeout=5000)
            page.click("li[data-command='runmenu:restart-and-run-all']")
            page.wait_for_selector("button.jp-Dialog-button.jp-mod-accept", timeout=5000)
            page.click("button.jp-Dialog-button.jp-mod-accept")
            
            print("Restart confirmed! Waiting for notebook to finish execution...")
            wait_for_notebook_cells(page)
            cells = _notebook_code_cells(page)
            data_i = _find_base64_data_code_cell_index(page)
            runner_i = _find_base64_runner_code_cell_index(page, data_i)

            output_locator = cells.nth(runner_i).locator(".jp-OutputArea-output")
            output_locator.first.wait_for(timeout=180000, state="attached")

            count = cells.count()
            
            print("========================================")
            print("NOTEBOOK EXECUTION RESULTS (code cells from data/runner onward):")
            start_i = min(data_i, runner_i)
            for i in range(start_i, count):
                cell = cells.nth(i)
                output_area = cell.locator(".jp-OutputArea-output")
                
                if output_area.count() > 0:
                    texts = output_area.all_inner_texts()
                    result = "\n".join(texts).strip()
                    if result:
                        print(f"\n--- CODE CELL {i + 1} OUTPUT ---")
                        print(result)
                
                # Check for errors
                if cell.locator(".jp-RenderedError").count() > 0:
                    print(f"\n⚠️ WARNING: Code cell {i + 1} returned an ERROR.")
                    error_text = cell.locator(".jp-RenderedError").all_inner_texts()
                    print("\n".join(error_text))
            
            print("\n========================================")
            print(
                "Note: Output above is from the **remote** Jupyter kernel (server paths), not from skipping "
                "your local JSON. Payload file on this PC:"
            )
            print(f"  {input_path}")
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
