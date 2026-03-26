"""
Shared Playwright settings for Django admin automation.
Fixes common failures: short timeouts, SSL warnings, and silent exit 0 on navigation errors.
"""
from __future__ import annotations

import os
import sys

GOTO_TIMEOUT_MS = int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000"))


def new_admin_browser_context(browser, session_file: str | None):
    """Context with SSL relaxed and a normal UA (some hosts block bare headless)."""
    kwargs: dict = {
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 720},
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    if session_file and os.path.isfile(session_file):
        kwargs["storage_state"] = session_file
    return browser.new_context(**kwargs)


def goto_or_fail(page, url: str, *, script: str, step: str = "page.goto(admin)") -> None:
    """Navigate or print PIPELINE_EXCEPTION and exit 1. Caller should close browser in finally."""
    print("Navigating to Admin...", flush=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
    except Exception as e:
        print()
        print(">>> PIPELINE_EXCEPTION")
        print(">>>   phase:   PHASE_2_PERFORM_ACTIONS (Django admin)")
        print(f">>>   script:  {script}")
        print(f">>>   step:    {step}")
        print(f">>>   url:     {url}")
        print(">>>   code:    1")
        print(f">>>   detail:  {e}")
        u = url if len(url) <= 100 else url[:97] + "..."
        print(f">>>   hint:    curl -vI '{u}'  (if this fails, fix VPN/DNS/firewall first)")
        sys.exit(1)


def chromium_launch_args():
    return {"headless": True, "args": ["--disable-blink-features=AutomationControlled"]}
