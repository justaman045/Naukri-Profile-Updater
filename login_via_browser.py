#!/usr/bin/env python3
"""Log in to Naukri in a real browser, then import the cookies into the app.

This is an optional developer helper: the app itself stays headless and never
imports Playwright. Use it when Naukri's captcha blocks the automated login.

Install once (not part of the app's runtime requirements):

    pip install playwright
    python -m playwright install chromium

Then run and log in in the window that opens:

    python login_via_browser.py --channel chrome --verify

The persistent profile at ``~/.naukri-profile-update/browser-profile`` keeps the
browser logged in across runs, so usually only the first run needs a manual
login.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.browser_cookies import (  # noqa: E402
    BrowserCookieError,
    build_session,
    save_session_data,
    verify_session,
)
from src.core.credentials import ensure_credential  # noqa: E402
from src.core.session_store import APP_DIR, SESSION_FILE  # noqa: E402

LOGIN_URL = "https://www.naukri.com/nlogin/login"
DEFAULT_PROFILE = APP_DIR / "browser-profile"


def _naukri_cookies(context) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for cookie in context.cookies():
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if domain == "naukri.com" or domain.endswith(".naukri.com"):
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value:
                cookies[str(name)] = str(value)
    return cookies


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--channel",
        choices=("chromium", "chrome", "msedge"),
        default="chrome",
        help="Browser to drive. 'chrome' uses an installed Google Chrome and is "
             "less likely to be captcha-challenged than bundled Chromium.",
    )
    parser.add_argument(
        "-e", "--email",
        default="",
        help="Naukri account email to store with the session.",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE),
        help="Persistent browser profile directory (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for a successful login (default: %(default)s).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check the captured session against Naukri's profile endpoint before saving.",
    )
    args = parser.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Playwright is not installed. Install it with:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )

    profile_dir = Path(args.profile_dir).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)

    cookies: dict[str, str] = {}
    channel = None if args.channel == "chromium" else args.channel

    with sync_playwright() as pw:
        try:
            context = pw.chromium.launch_persistent_context(
                str(profile_dir), headless=False, channel=channel
            )
        except Exception as exc:  # noqa: BLE001 - surface a clear hint
            raise SystemExit(
                f"Could not launch {args.channel}: {exc}\n"
                "Try --channel chromium (after `python -m playwright install chromium`) "
                "or install the selected browser."
            ) from exc

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(LOGIN_URL)
            print(
                "Log in to Naukri in the opened browser window.\n"
                f"Waiting up to {args.timeout}s for the `nauk_at` cookie..."
            )
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                try:
                    cookies = _naukri_cookies(context)
                    if cookies.get("nauk_at"):
                        break
                    page.wait_for_timeout(1000)
                except Exception:  # noqa: BLE001 - the user may close the window
                    break
        except KeyboardInterrupt:
            raise SystemExit("Cancelled.") from None
        finally:
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass

    if not cookies.get("nauk_at"):
        raise SystemExit(
            "Timed out before a Naukri session was established. Log in fully "
            "(complete any captcha) and try again."
        )

    try:
        data = build_session(cookies, args.email)
    except BrowserCookieError as exc:
        raise SystemExit(str(exc)) from exc

    if args.verify:
        ok, message = verify_session(cookies)
        print(f"Verification: {message}")
        if not ok:
            raise SystemExit("Not saving an invalid session.")

    save_session_data(data)
    if args.email:
        try:
            ensure_credential(args.email)
        except OSError as exc:
            print(f"Warning: could not remember the account: {exc}", file=sys.stderr)
    print(f"Saved session for {args.email or '<no email>'} to {SESSION_FILE}")
    print("Start the app with: python src/main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
