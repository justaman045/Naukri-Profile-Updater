"""Read Naukri cookies from a real browser and turn them into a session.

Naukri's password login is gated by its own captcha widget (``niCaptchaWidget``)
plus a reCAPTCHA/BotGuard fallback, so a headless HTTP client cannot sign in on
its own. The supported workaround is to log in once in a real browser and reuse
that browser's cookies.

This module is deliberately import-safe for the app (``src.core...``) and for the
standalone scripts (which insert the repo root on ``sys.path`` first). It never
logs cookie or token values.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import requests

from src.core.session_store import SESSION_FILE, SessionData, save_session

# Cookie-only endpoint; used as a fallback check (see AGENTS.md).
DASHBOARD_URL = "https://www.naukri.com/mnjapi/v4/dashBoard"
# Authenticated read used by the app; 401/403 cleanly identifies a dead token.
PROFILE_URL = (
    "https://www.naukri.com/cloudgateway-mynaukri/"
    "resman-aggregator-services/v2/users/self?expand_level=3"
)
NAUKRI_COOKIE = "nauk_at"

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

_CHROMIUM_KEYRING_LABELS = {
    "chrome": "Chrome Safe Storage",
    "chromium": "Chromium Safe Storage",
    "brave": "Brave Safe Storage",
    "edge": "Microsoft Edge Safe Storage",
    "vivaldi": "Vivaldi Safe Storage",
}


class BrowserCookieError(Exception):
    """Raised when a browser's cookie store cannot be read or has no session."""


def is_naukri_host(host: str) -> bool:
    """True for the apex domain and any subdomain of ``naukri.com``."""
    host = (host or "").strip().lstrip(".").lower()
    return host == "naukri.com" or host.endswith(".naukri.com")


# ---------------------------------------------------------------------------
# Session construction / persistence / verification
# ---------------------------------------------------------------------------

def build_session(cookies: dict, email: str = "") -> SessionData:
    """Validate captured cookies and return a :class:`SessionData`.

    ``nauk_at`` is the JWT the app sends as ``Authorization: Bearer``; without
    it every cloudgateway call would 401, so its absence is an error rather than
    a silently broken session.
    """
    cleaned = {
        str(name): str(value)
        for name, value in (cookies or {}).items()
        if name and value is not None and str(value) != ""
    }
    token = cleaned.get(NAUKRI_COOKIE, "").strip()
    if not token:
        raise BrowserCookieError(
            "No `nauk_at` cookie found. Log in to naukri.com fully in the "
            "browser and try again (that cookie is the session token)."
        )
    return SessionData(username=(email or "").strip(), bearer_token=token, cookies=cleaned)


def save_session_data(data: SessionData) -> None:
    """Persist the session and keep the file owner-only where possible."""
    save_session(data)
    try:
        os.chmod(SESSION_FILE, 0o600)
    except OSError:
        pass


def verify_session(cookies: dict, timeout: int = 10) -> tuple[bool, str]:
    """Check a captured session against Naukri, returning ``(ok, message)``.

    The primary check is an authenticated profile read with the ``nauk_at``
    Bearer token: 200 means the session works, 401/403 means it is dead. If that
    call cannot decide (unexpected status), fall back to the cookie-only
    dashboard endpoint. Network errors are reported as failures but never raise,
    so callers can decide whether to save anyway.
    """
    token = str((cookies or {}).get(NAUKRI_COOKIE, "")).strip()
    if not token:
        return False, "no `nauk_at` token in the captured cookies"

    headers = {
        "accept": "application/json",
        "appid": "105",
        "systemid": "Naukri",
        "user-agent": _UA,
        "authorization": f"Bearer {token}",
    }
    try:
        resp = requests.get(PROFILE_URL, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"could not reach Naukri: {exc}"
    if resp.status_code == 200:
        return True, "session is valid (profile reachable)"
    if resp.status_code in (401, 403):
        return False, f"session rejected (HTTP {resp.status_code}) — re-capture the cookies"

    # Unexpected status from the profile call: try the cookie-only dashboard.
    try:
        dash = requests.get(
            DASHBOARD_URL,
            cookies=cookies,
            headers={"accept": "application/json", "user-agent": _UA},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"could not reach Naukri: {exc}"
    if dash.status_code == 200:
        return True, "session is valid (dashboard reachable)"
    if dash.status_code in (401, 403):
        return False, f"session rejected (HTTP {dash.status_code}) — re-capture the cookies"
    return False, f"unexpected HTTP {resp.status_code} (dashboard {dash.status_code})"


# ---------------------------------------------------------------------------
# Firefox (plaintext cookies.sqlite)
# ---------------------------------------------------------------------------

def _firefox_cookie_candidates() -> list[Path]:
    home = Path.home()
    if sys.platform == "darwin":
        roots = [home / "Library/Application Support/Firefox/Profiles"]
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        roots = [Path(appdata) / "Mozilla/Firefox/Profiles"] if appdata else []
    else:
        roots = [
            home / ".mozilla/firefox",
            home / "snap/firefox/common/.mozilla/firefox",
            home / ".var/app/org.mozilla.firefox/.mozilla/firefox",
        ]
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found.extend(root.glob("*/cookies.sqlite"))
    return found


def read_firefox_cookies(profile: str | Path | None = None) -> dict[str, str]:
    """Return ``{name: value}`` for every Naukri cookie in a Firefox profile."""
    path = _resolve_firefox_path(profile)
    try:
        with _readonly_copy(path) as db_path:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT host, name, value FROM moz_cookies "
                    "WHERE host LIKE ?",
                    ("%naukri.com",),
                ).fetchall()
            finally:
                conn.close()
    except sqlite3.DatabaseError as exc:
        raise BrowserCookieError(f"could not read Firefox cookies at {path}: {exc}") from exc

    return {
        str(name): str(value)
        for host, name, value in rows
        if is_naukri_host(host) and value is not None
    }


def _resolve_firefox_path(profile: str | Path | None) -> Path:
    if profile:
        path = Path(profile).expanduser()
        if path.is_dir():
            path = path / "cookies.sqlite"
        if not path.exists():
            raise BrowserCookieError(f"Firefox cookie database not found: {path}")
        return path
    candidates = _firefox_cookie_candidates()
    if not candidates:
        raise BrowserCookieError(
            "No Firefox cookie database found. Launch Firefox and log in to "
            "naukri.com first, or pass --profile <path>."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Chromium family (encrypted Cookies database — Linux best effort)
# ---------------------------------------------------------------------------

def _chromium_base_dir(browser: str) -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        roots = {
            "chrome": home / "Library/Application Support/Google/Chrome",
            "chromium": home / "Library/Application Support/Chromium",
            "brave": home / "Library/Application Support/BraveSoftware/Brave-Browser",
            "edge": home / "Library/Application Support/Microsoft Edge",
            "vivaldi": home / "Library/Application Support/Vivaldi",
        }
    elif sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        roots = {
            "chrome": local / "Google/Chrome/User Data",
            "chromium": local / "Chromium/User Data",
            "brave": local / "BraveSoftware/Brave-Browser/User Data",
            "edge": local / "Microsoft/Edge/User Data",
            "vivaldi": local / "Vivaldi/User Data",
        }
    else:
        roots = {
            "chrome": home / ".config/google-chrome",
            "chromium": home / ".config/chromium",
            "brave": home / ".config/BraveSoftware/Brave-Browser",
            "edge": home / ".config/microsoft-edge",
            "vivaldi": home / ".config/vivaldi",
        }
    return roots[browser]


def _chromium_cookie_candidates(browser: str) -> list[Path]:
    base = _chromium_base_dir(browser)
    if not base.is_dir():
        return []
    found: list[Path] = []
    for profile in base.iterdir():
        if not profile.is_dir():
            continue
        for name in ("Cookies", "Network/Cookies"):
            candidate = profile / name
            if candidate.is_file():
                found.append(candidate)
    return found


def _resolve_chromium_path(browser: str, profile: str | Path | None) -> Path:
    if profile:
        path = Path(profile).expanduser()
        if path.is_dir():
            for name in ("Cookies", "Network/Cookies"):
                if (path / name).is_file():
                    path = path / name
                    break
        if not path.is_file():
            raise BrowserCookieError(f"{browser} cookie database not found: {path}")
        return path
    candidates = _chromium_cookie_candidates(browser)
    if not candidates:
        raise BrowserCookieError(
            f"No {browser} cookie database found. Log in to naukri.com in "
            f"{browser} first, or pass --profile <path>."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _decrypt_chromium_windows(encrypted: bytes) -> str:
    """Decrypt a Chrome v10/v11 cookie value on Windows using DPAPI.

    Chrome on Windows encrypts cookie values with ``CryptProtectData``. The
    first 3 bytes are the ``v10``/``v11`` prefix; the rest is the DPAPI blob.
    ``CryptUnprotectData`` decrypts it for the current user without any extra
    Python packages. Returns ``""`` when decryption fails or the value is not
    v10/v11.
    """
    if len(encrypted) < 4 or encrypted[:3] not in (b"v10", b"v11"):
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        raw = encrypted[3:]
        data_in = DATA_BLOB()
        data_in.cbData = len(raw)
        data_in.pbData = (ctypes.c_byte * len(raw)).from_buffer_copy(raw)

        data_out = DATA_BLOB()
        desc = ctypes.c_wchar_p()

        if not crypt32.CryptUnprotectData(
            ctypes.byref(data_in),
            ctypes.byref(desc),
            None,
            None,
            None,
            0,
            ctypes.byref(data_out),
        ):
            return ""

        try:
            result = ctypes.string_at(
                data_out.pbData, data_out.cbData
            ).decode("utf-8", "replace")
        finally:
            kernel32.LocalFree(data_out.pbData)
        return result
    except Exception:  # noqa: BLE001 - DPAPI is best effort on Windows
        return ""


def read_chromium_cookies(
    browser: str,
    profile: str | Path | None = None,
    password_store: str = "auto",
) -> dict[str, str]:
    """Return Naukri cookies from a Chromium-family browser.

    Linux: encrypted values are decrypted with the key from Secret Service or
    ``"peanuts"`` (see :func:`_decrypt_chromium_value`).
    Windows: v10/v11 values are decrypted with DPAPI (see
    :func:`_decrypt_chromium_windows`). v20+ (app-bound encryption) is not
    decryptable here — export cookies as JSON and use ``--from-json`` instead.
    macOS (Keychain) is not supported — use ``--from-json`` there.
    """
    if browser not in _CHROMIUM_KEYRING_LABELS:
        raise BrowserCookieError(f"unsupported browser: {browser}")
    path = _resolve_chromium_path(browser, profile)

    try:
        with _readonly_copy(path) as db_path:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT host_key, name, value, encrypted_value FROM cookies"
                ).fetchall()
            finally:
                conn.close()
    except sqlite3.DatabaseError as exc:
        raise BrowserCookieError(
            f"could not read {browser} cookies at {path}: {exc}"
        ) from exc

    use_windows = sys.platform.startswith("win")
    passwords = [] if use_windows else _candidate_passwords(browser, password_store)
    cookies: dict[str, str] = {}
    chosen: bytes | None = None

    for host, name, value, encrypted in rows:
        if not is_naukri_host(host):
            continue
        if value:
            cookies[str(name)] = str(value)
            continue
        if not encrypted:
            continue
        decrypted = ""
        if use_windows:
            decrypted = _decrypt_chromium_windows(encrypted)
        elif chosen is None:
            for password in passwords:
                try:
                    candidate = _decrypt_chromium_value(encrypted, host, password)
                except BrowserCookieError:
                    raise
                except Exception:
                    continue
                if _looks_text(candidate):
                    chosen = password
                    decrypted = candidate
                    break
            if chosen is None:
                raise BrowserCookieError(
                    f"could not decrypt {browser} cookies. On Linux, run the "
                    "browser with --password-store=basic, install the optional "
                    "`cryptography`+`secretstorage` packages, or export the "
                    "cookies as JSON and use --from-json."
                )
        else:
            try:
                decrypted = _decrypt_chromium_value(encrypted, host, chosen)
            except Exception:
                continue
        if decrypted:
            cookies[str(name)] = decrypted

    return {name: value for name, value in cookies.items() if value}


def _candidate_passwords(browser: str, password_store: str) -> list[bytes]:
    if password_store == "basic" or not sys.platform.startswith("linux"):
        return [b"peanuts"]
    passwords: list[bytes] = []
    secret = _keyring_secret(_CHROMIUM_KEYRING_LABELS.get(browser, ""))
    if secret:
        passwords.append(secret)
    # Chrome silently falls back to this when no keyring is available.
    passwords.append(b"peanuts")
    return passwords


def _keyring_secret(label: str) -> bytes | None:
    if not label:
        return None
    try:
        import secretstorage
    except ImportError:
        return None
    try:
        bus = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(bus)
        for item in collection.get_all_items():
            if item.get_label() != label:
                continue
            if getattr(item, "is_locked", lambda: False)():
                item.unlock()
            return bytes(item.get_secret())
    except Exception:  # noqa: BLE001 - keyring is best effort
        return None
    return None


def _decrypt_chromium_value(encrypted: bytes, host: str, password: bytes) -> str:
    if not encrypted:
        return ""
    if encrypted[:3] not in (b"v10", b"v11"):
        # v20+ uses app-bound encryption; not decryptable here.
        return ""
    if not sys.platform.startswith("linux"):
        raise BrowserCookieError(
            "cookie decryption is only supported for Linux browser profiles. "
            "Export the cookies as JSON (Cookie-Editor) and use --from-json."
        )
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise BrowserCookieError(
            "Chrome cookie decryption needs the optional `cryptography` "
            "package, or export cookies as JSON and use --from-json."
        ) from exc

    key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1, 16)
    iv = b" " * 16
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    raw = decryptor.update(encrypted[3:]) + decryptor.finalize()
    if not raw:
        return ""
    pad = raw[-1]
    if 1 <= pad <= 16:
        raw = raw[:-pad]
    # Chrome >= 130 prefixes the plaintext with SHA256(host_key) on some builds.
    if len(raw) > 32 and raw[:32] == hashlib.sha256(host.encode()).digest():
        raw = raw[32:]
    return raw.decode("utf-8", "replace")


def _looks_text(value: str) -> bool:
    return bool(value) and all(ch.isprintable() or ch in "\t\r\n" for ch in value)


# ---------------------------------------------------------------------------
# JSON export (Cookie-Editor, Playwright storageState, plain map)
# ---------------------------------------------------------------------------

def read_json_cookies(path: str | Path) -> dict[str, str]:
    """Read cookies from a JSON export.

    Accepts a Cookie-Editor list of objects, a Playwright ``storageState``
    (``{"cookies": [...]}``), or a plain ``{name: value}`` map.
    """
    source = Path(path).expanduser()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BrowserCookieError(f"could not read {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BrowserCookieError(f"{source} is not valid JSON: {exc}") from exc

    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        data = data["cookies"]

    if isinstance(data, dict):
        return {
            str(name): str(value)
            for name, value in data.items()
            if value is not None and str(value) != ""
        }

    if isinstance(data, list):
        cookies: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            host = item.get("domain") or item.get("host") or ""
            name = item.get("name")
            value = item.get("value")
            if not name or value is None:
                continue
            if host and not is_naukri_host(host):
                continue
            cookies[str(name)] = str(value)
        if not cookies:
            raise BrowserCookieError(
                f"{source} contained no Naukri cookies (domain must be *.naukri.com)."
            )
        return cookies

    raise BrowserCookieError(f"unrecognised cookie export format in {source}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _readonly_copy(path: Path):
    """Yield a temporary copy of a live SQLite DB so it can be read safely.

    Browsers keep the database open and may have a WAL file; copying the DB and
    its sidecars avoids ``database is locked`` and reading a half-written page.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="naukri-cookies-"))
    try:
        for suffix in ("", "-wal", "-shm"):
            source = path if not suffix else path.with_name(path.name + suffix)
            if source.exists():
                shutil.copy2(source, tmpdir / (path.name + suffix))
        yield tmpdir / path.name
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
