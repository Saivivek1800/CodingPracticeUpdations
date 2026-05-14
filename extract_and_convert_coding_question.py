import argparse
import json
import os
import time

import requests
from playwright.sync_api import sync_playwright

from admin_playwright_util import (
    chromium_launch_args,
    django_admin_can_relogin_or_session,
    django_admin_login_credentials,
    goto_or_fail,
    new_admin_browser_context,
)
from convert_extracted_to_coding_json import convert


ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "https://nkb-backend-ccbp-beta.earlywave.in/admin/")
if not ADMIN_URL.endswith("/"):
    ADMIN_URL += "/"

CONTENT_LOADING_URL = ADMIN_URL + "nkb_load_data/contentloading/add/"
SESSION_FILE = os.environ.get("SESSION_FILE", "beta_admin_session.json")


def _max_wait_seconds_for_payload(payload: dict) -> int:
    """How long to poll the admin task before giving up (batch jobs need longer)."""
    if os.environ.get("EXTRACT_MAX_WAIT_SEC"):
        return max(60, int(os.environ["EXTRACT_MAX_WAIT_SEC"]))
    ids = payload.get("question_ids")
    n = len(ids) if isinstance(ids, list) else 1
    # Default: at least 30 min; add 5 min per question (10 questions ≈ 80 min).
    return max(1800, 900 + n * 300)


def _page_looks_logged_in(page) -> bool:
    """Detect Django admin session without relying on full HTML (faster, fewer false negatives)."""
    try:
        u = (page.url or "").lower()
        if "/admin/login" in u or u.rstrip("/").endswith("/login"):
            return False
    except Exception:
        pass
    try:
        loc = page.locator("a[href*='logout']")
        if loc.count() > 0:
            try:
                return loc.first.is_visible(timeout=5000)
            except Exception:
                return True
    except Exception:
        pass
    try:
        body = page.content()
    except Exception:
        body = ""
    return "Log out" in body or "Logout" in body


def _looks_like_http_url(s: str) -> bool:
    t = (s or "").strip()
    return t.startswith("http://") or t.startswith("https://")


def _is_fetched_error_body(text: str) -> bool:
    """True when text is clearly a traceback / exception dump (not another JSON wrapper with URLs)."""
    t = text.lstrip()
    if not t:
        return False
    if t.startswith("{") or t.startswith("["):
        return False
    lowered = t.lower()
    return (
        "traceback (most recent call last)" in lowered
        or lowered.startswith("exception ")
        or "invalid_question_ids" in lowered
        or "invalidinputdataexception" in lowered
        or "\n  file \"" in lowered
    )


def _http_get_text(url: str) -> str:
    r = requests.get(url.strip(), timeout=120)
    r.raise_for_status()
    return (r.text or "").strip()


def _find_task_output_download_url(data: dict) -> str | None:
    """
    Admin often stores only a JSON wrapper; the real log/error is at a URL.

    Mirrors extract_coding_questions.py: on FAILURE, output may be
    {\"exception\": \"https://...\"} (signed URL to the real body).
    """
    # Order matters: 'exception' is commonly the error artifact URL on failure.
    direct_keys = (
        "exception",
        "traceback_url",
        "error_url",
        "task_output_url",
        "output_url",
        "result_url",
        "failure_output_url",
        "log_url",
        "details_url",
        "input_questions_json_s3_url",
        "url",
    )
    for k in direct_keys:
        v = data.get(k)
        if isinstance(v, str) and _looks_like_http_url(v):
            return v.strip()
    for nest in ("response", "output", "result", "data", "error"):
        sub = data.get(nest)
        if isinstance(sub, dict):
            inner = _find_task_output_download_url(sub)
            if inner:
                return inner
        if isinstance(sub, str) and _looks_like_http_url(sub):
            return sub.strip()
    return None


def _resolve_task_output_to_text(task_output_text: str, max_hops: int = 5) -> str:
    """
    Follow bare URLs or JSON fields that point to URLs until we get real text/JSON content.
    Stops when the body looks like an exception/traceback or is JSON without a download URL.
    """
    raw = (task_output_text or "").strip()
    last_error: str | None = None
    for _ in range(max_hops):
        if not raw:
            break
        if _is_fetched_error_body(raw):
            break
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            url = _find_task_output_download_url(data)
            if url:
                try:
                    raw = _http_get_text(url)
                    continue
                except Exception as e:
                    last_error = f"(Failed to download task output from URL: {e})"
                    try:
                        raw = json.dumps(data, indent=2, ensure_ascii=False)
                    except TypeError:
                        raw = str(data)
                    break
            break
        if _looks_like_http_url(raw) and "\n" not in raw:
            try:
                raw = _http_get_text(raw)
                continue
            except Exception as e:
                return f"(Failed to download task output from URL: {e})\nURL was:\n{raw}"[:12000]
        break
    if last_error and raw:
        return f"{last_error}\n\n{raw}"
    if last_error:
        return last_error
    return raw


def _extract_failure_detail(task_output_text: str) -> str:
    """Best-effort parse of admin task output JSON/text so users see the real error."""
    raw = (task_output_text or "").strip()
    if not raw:
        return "(No error text was returned in the task output field — the failure reason is unavailable in this run.)"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw if len(raw) <= 12000 else raw[:12000] + "\n… (truncated)"

    if not isinstance(data, dict):
        return raw if len(raw) <= 12000 else raw[:12000] + "\n… (truncated)"

    chunks: list[str] = []
    inv = data.get("invalid_question_ids")
    if inv is not None:
        try:
            pretty_inv = json.dumps(inv, indent=2, ensure_ascii=False)
        except TypeError:
            pretty_inv = str(inv)
        chunks.append(f"invalid_question_ids:\n{pretty_inv}")
    for key in ("error", "exception", "message", "detail", "reason", "traceback", "stack_trace"):
        val = data.get(key)
        if val is not None and str(val).strip():
            if isinstance(val, str) and _looks_like_http_url(val) and key == "exception":
                continue
            chunks.append(f"{key}:\n{val}")

    for nest_name in ("response", "output", "result", "data"):
        sub = data.get(nest_name)
        if isinstance(sub, dict):
            for key in ("error", "exception", "message", "detail", "traceback"):
                val = sub.get(key)
                if val is not None and str(val).strip():
                    if isinstance(val, str) and _looks_like_http_url(val) and key == "exception":
                        continue
                    chunks.append(f"{nest_name}.{key}:\n{val}")
        elif isinstance(sub, str) and sub.strip():
            chunks.append(f"{nest_name}:\n{sub.strip()}")

    if chunks:
        return "\n\n".join(chunks)

    # Fallback: pretty-print whole object (often includes nested error)
    try:
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
    except TypeError:
        pretty = str(data)
    return pretty if len(pretty) <= 12000 else pretty[:12000] + "\n… (truncated)"


def _extract_s3_url(task_output_text: str) -> str | None:
    data = json.loads(task_output_text)
    if isinstance(data, dict):
        response = data.get("response")
        if isinstance(response, dict) and response.get("input_questions_json_s3_url"):
            return response["input_questions_json_s3_url"]
        output = data.get("output")
        if isinstance(output, dict) and output.get("input_questions_json_s3_url"):
            return output["input_questions_json_s3_url"]
        if isinstance(output, str) and output.startswith("http"):
            return output
    return None


def run(input_file: str, raw_output_file: str, converted_output_file: str) -> None:
    if not django_admin_can_relogin_or_session(SESSION_FILE, admin_url=ADMIN_URL):
        raise SystemExit(
            f"Error: No saved session ({SESSION_FILE}) and no admin credentials in environment. "
            "Add BETA_/PROD_DJANGO_ADMIN_* to .secrets.env or secrets.local.env (gitignored *.local.env)."
        )

    with open(input_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_args())
        context = new_admin_browser_context(browser, SESSION_FILE)
        page = context.new_page()

        goto_or_fail(page, ADMIN_URL, script="extract_and_convert_coding_question.py")
        try:
            page.wait_for_load_state("networkidle", timeout=90000)
        except Exception:
            pass

        if not _page_looks_logged_in(page):
            user, pwd = django_admin_login_credentials(ADMIN_URL)
            if user and pwd:
                page.fill("#id_username", user)
                page.fill("#id_password", pwd)
                page.click("input[type='submit']")
                page.wait_for_load_state("networkidle")
                context.storage_state(path=SESSION_FILE)
            else:
                _env_hint = os.environ.get("DJANGO_TARGET_ENV") or (
                    "prod" if "prod" in os.path.basename(SESSION_FILE).lower() else "beta"
                )
                raise RuntimeError(
                    "Django admin session is missing or expired, and no username/password were loaded for re-login. "
                    f"Target from session file: {_env_hint}. "
                    "Add BETA_DJANGO_ADMIN_USERNAME/PASSWORD (and PROD_* for prod) to .secrets.env, "
                    "or set SECRETS_DECRYPTION_KEY so .secrets.enc decrypts in NON_INTERACTIVE mode. "
                    f"You can delete {SESSION_FILE} after fixing credentials, then run again to save a new session."
                )

        print("Creating content loading task...")
        page.goto(CONTENT_LOADING_URL)
        page.wait_for_load_state("networkidle")
        page.select_option("#id_task_type", "EXTRACT_CODING_QUESTION_CONTENT")
        page.fill("#id_input_data", json.dumps(payload))
        page.click("input[name='_continue']")
        page.wait_for_load_state("networkidle")

        print("Tracking extract task in admin (polling status; URL omitted for users without admin access).")
        status_selector = ".field-task_status .readonly"
        output_selector = ".field-task_output_url .readonly"

        poll_interval = max(3, int(os.environ.get("EXTRACT_POLL_INTERVAL_SEC", "5")))
        max_wait = _max_wait_seconds_for_payload(payload)
        deadline = time.monotonic() + max_wait
        print(
            f"Polling until SUCCESS or FAILURE (max ~{max_wait // 60}m {max_wait % 60}s); "
            f"set EXTRACT_MAX_WAIT_SEC to override."
        )

        s3_url = None
        success_without_url = False
        while time.monotonic() < deadline:
            page.reload()
            page.wait_for_load_state("networkidle")
            status = page.inner_text(status_selector).strip() if page.is_visible(status_selector) else ""
            print(f"Status: {status or 'UNKNOWN'}")
            if status == "SUCCESS":
                task_output = page.inner_text(output_selector).strip() if page.is_visible(output_selector) else ""
                s3_url = _extract_s3_url(task_output)
                if s3_url:
                    break
                success_without_url = True
                break
            if status == "FAILURE":
                task_out = page.inner_text(output_selector).strip() if page.is_visible(output_selector) else ""
                resolved_out = _resolve_task_output_to_text(task_out)
                detail = _extract_failure_detail(resolved_out)
                raise RuntimeError(
                    "Content loading task finished with status FAILURE.\n"
                    "Parsed error from the admin task output field (Exception / traceback when the backend provides it):\n"
                    "----------\n"
                    f"{detail}\n"
                    "----------"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval, max(1.0, remaining)))

        browser.close()

    if not s3_url:
        if success_without_url:
            raise RuntimeError("Could not find input_questions_json_s3_url in task output.")
        raise RuntimeError(
            "Timed out waiting for SUCCESS (no input_questions_json_s3_url yet). "
            "For large batches, set EXTRACT_MAX_WAIT_SEC (seconds) higher, or wait and re-run."
        )

    print(f"Downloading extracted JSON from: {s3_url}")
    response = requests.get(s3_url, timeout=120)
    response.raise_for_status()
    with open(raw_output_file, "wb") as f:
        f.write(response.content)
    print(f"Saved extracted JSON: {raw_output_file}")

    with open(raw_output_file, "r", encoding="utf-8") as f:
        extracted = json.load(f)
    converted = convert(extracted)
    with open(converted_output_file, "w", encoding="utf-8") as f:
        json.dump(converted, f, indent=2)
    print(f"Saved converted coding JSON: {converted_output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract coding question content via admin and convert to coding JSON.")
    parser.add_argument("input_file", nargs="?", default="input_extract_question.json")
    parser.add_argument("--raw-output", default="extracted_coding_questions.json")
    parser.add_argument("--output", default="coding_questions_output.json")
    args = parser.parse_args()
    run(args.input_file, args.raw_output, args.output)
