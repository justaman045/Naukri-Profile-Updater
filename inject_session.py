#!/usr/bin/env python3
"""Inject a Naukri browser session into the app's session store.

Naukri's password login is gated by a captcha (HTTP 403/406 with a
``captchaSiteKey``), so an automated login cannot succeed. Log in once in a real
browser and reuse that session here. The app then starts from the saved session
instead of calling the login API.

Sources
-------
* ``--from-browser firefox``  read Firefox's ``cookies.sqlite`` (no extra deps)
* ``--from-browser chrome``   read Chrome/Chromium/Brave/Edge/Vivaldi (Linux
                              best-effort; needs ``cryptography`` and usually
                              ``secretstorage``, or a ``--password-store basic``
                              profile)
* ``--from-json PATH``        Cookie-Editor export / Playwright storageState /
                              plain ``{name: value}`` map (any OS, no deps)
* positional ``cookies``      paste the raw ``Cookie`` header / ``@file``

Examples
--------
    python inject_session.py --from-browser firefox -e you@example.com
    python inject_session.py --from-browser chrome --verify -e you@example.com
    python inject_session.py --from-json cookies.json -e you@example.com
    python inject_session.py "nauk_at=eyJ...; _ga=GA1.2..." -e you@example.com
    python inject_session.py "nauk_at=..." -t "Bearer eyJ..." -e you@example.com
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `src` importable no matter which directory this script is run from.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.browser_cookies import (  # noqa: E402
    BrowserCookieError,
    build_session,
    read_chromium_cookies,
    read_firefox_cookies,
    read_json_cookies,
    save_session_data,
    verify_session,
)
from src.core.credentials import ensure_credential  # noqa: E402
from src.core.session_store import SESSION_FILE  # noqa: E402

_BROWSERS = ("firefox", "chrome", "chromium", "brave", "edge", "vivaldi")


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    """Parse a browser ``Cookie`` header into a ``{name: value}`` dict.

    Accepts values pasted with surrounding whitespace/newlines and ignores
    empty fragments. A value that itself contains ``=`` is preserved intact
    (only the first ``=`` splits name from value).
    """
    cookies: dict[str, str] = {}
    for part in cookie_header.replace("\n", ";").replace("\r", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if name:
            cookies[name] = value
    return cookies


def normalize_token(token: str) -> str:
    """Strip a pasted ``Authorization: Bearer`` prefix and whitespace."""
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def read_cookie_arg(value: str) -> str:
    """Return the cookie header, reading ``@path`` from a file when given."""
    if value.startswith("@"):
        path = Path(value[1:]).expanduser()
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"Could not read cookie file {path}: {exc}") from exc
    return value


def collect_cookies(args: argparse.Namespace) -> dict[str, str]:
    """Load cookies from whichever source the user selected."""
    if args.from_json:
        return read_json_cookies(args.from_json)
    if args.from_browser == "firefox":
        return read_firefox_cookies(args.profile)
    if args.from_browser:
        return read_chromium_cookies(
            args.from_browser, args.profile, args.password_store
        )
    if args.cookies is not None:
        return parse_cookie_header(read_cookie_arg(args.cookies))
    raise SystemExit(
        "No cookie source given. Use --from-browser, --from-json, or pass the "
        "Cookie header as the positional argument."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inject a Naukri browser session into the app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples\n--------", 1)[-1],
    )
    parser.add_argument(
        "cookies",
        nargs="?",
        default=None,
        help="Cookie header value, or @path to a file containing it.",
    )
    parser.add_argument(
        "--from-browser",
        choices=_BROWSERS,
        help="Read cookies directly from a browser profile.",
    )
    parser.add_argument(
        "--from-json",
        metavar="PATH",
        help="Read cookies from a JSON export (Cookie-Editor / storageState).",
    )
    parser.add_argument(
        "--profile",
        metavar="PATH",
        help="Browser profile directory or cookie database path.",
    )
    parser.add_argument(
        "--password-store",
        choices=("auto", "basic"),
        default="auto",
        help="Chromium key source: 'auto' (Secret Service, then peanuts) or "
             "'basic' (the --password-store=basic fallback).",
    )
    parser.add_argument(
        "-t", "--token",
        default="",
        help="Bearer token (optional; derived from the nauk_at cookie).",
    )
    parser.add_argument(
        "-e", "--email",
        default="",
        help="Naukri account email (status bar + saved-password lookups).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check the session against Naukri's profile endpoint before saving.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Save even when --verify reports the session as invalid.",
    )
    args = parser.parse_args(argv)

    sources = [bool(args.from_browser), bool(args.from_json), args.cookies is not None]
    if sum(sources) > 1:
        parser.error("choose only one of: positional cookies, --from-browser, --from-json")

    try:
        cookies = collect_cookies(args)
    except BrowserCookieError as exc:
        raise SystemExit(str(exc)) from exc

    if not cookies:
        raise SystemExit("No cookies were found in that source.")

    token = normalize_token(args.token)
    if token:
        cookies["nauk_at"] = token

    if not args.email:
        print(
            "Warning: no --email given. The status bar will show a blank account "
            "and saved-password re-login will not find this account.",
            file=sys.stderr,
        )

    try:
        data = build_session(cookies, args.email)
    except BrowserCookieError as exc:
        raise SystemExit(str(exc)) from exc

    if args.verify:
        ok, message = verify_session(cookies)
        print(f"Verification: {message}")
        if not ok and not args.force:
            raise SystemExit(
                "Not saving an invalid session (re-capture the cookies, or pass "
                "--force to save anyway)."
            )

    save_session_data(data)
    if args.email:
        try:
            ensure_credential(args.email)
        except OSError as exc:
            print(f"Warning: could not remember the account: {exc}", file=sys.stderr)

    print(f"Saved session for {args.email or '<no email>'} to {SESSION_FILE}")
    print(f"  cookies: {len(data.cookies)}   token: {'yes' if data.bearer_token else 'no'}")
    print("Start the app with: python src/main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
