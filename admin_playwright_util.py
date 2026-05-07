"""
Shared Playwright settings for Django admin automation.
Fixes common failures: short timeouts, SSL warnings, and silent exit 0 on navigation errors.
"""
from __future__ import annotations

import os
import sys

GOTO_TIMEOUT_MS = int(os.environ.get("DJANGO_ADMIN_GOTO_TIMEOUT_MS", "90000"))


def _django_admin_is_prod_target(admin_url: str | None = None) -> bool:
    if (os.environ.get("DJANGO_TARGET_ENV") or "").strip().lower() == "prod":
        return True
    u = (admin_url or os.environ.get("DJANGO_ADMIN_URL") or "").lower()
    return "prod-apis" in u or "/prod" in u


def django_admin_login_credentials(admin_url: str | None = None) -> tuple[str, str]:
    """
    Username/password for Django admin re-login.

    Read at call time (after shell sources .secrets.env / secrets.local.env). Order matches
    lib_django_session.sh: DJANGO_ADMIN_* then PROD/BETA fallbacks by target env.
    """
    u = (os.environ.get("DJANGO_ADMIN_USERNAME") or "").strip()
    p = (os.environ.get("DJANGO_ADMIN_PASSWORD") or "").strip()
    if u and p:
        return u, p
    if _django_admin_is_prod_target(admin_url):
        u = u or (os.environ.get("PROD_DJANGO_ADMIN_USERNAME") or "").strip()
        p = p or (os.environ.get("PROD_DJANGO_ADMIN_PASSWORD") or "").strip()
        if not u:
            u = (os.environ.get("BETA_DJANGO_ADMIN_USERNAME") or "").strip()
        if not p:
            p = (os.environ.get("BETA_DJANGO_ADMIN_PASSWORD") or "").strip()
    else:
        u = u or (os.environ.get("BETA_DJANGO_ADMIN_USERNAME") or "").strip()
        p = p or (os.environ.get("BETA_DJANGO_ADMIN_PASSWORD") or "").strip()
        if not u:
            u = (os.environ.get("PROD_DJANGO_ADMIN_USERNAME") or "").strip()
        if not p:
            p = (os.environ.get("PROD_DJANGO_ADMIN_PASSWORD") or "").strip()
    return u, p


def django_admin_can_relogin_or_session(session_file: str | None = None, *, admin_url: str | None = None) -> bool:
    """True if we have creds for re-login or a saved Playwright storage_state file to try first."""
    sf = session_file if session_file is not None else os.environ.get("SESSION_FILE", "admin_session.json")
    u, p = django_admin_login_credentials(admin_url)
    return bool(u and p) or bool(sf and os.path.isfile(sf))


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
