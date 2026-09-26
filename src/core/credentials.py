"""Optional saved Naukri credentials, used to fill the login form and to
silently re-authenticate when a restored session turns out to be dead.

Storage rationale: `session.json` already writes a live Bearer token and cookie
dict in cleartext under this same directory, so this store keeps the same
posture rather than implying protection it does not have. A password is written
**only** when the user ticks "Remember password" in the login dialog; otherwise
just the email is kept so the account can still be picked from a list.

These credentials are intentionally NOT removed by `NaukriManager.logout()` --
surviving a logout is the whole point.
"""
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from src.core.session_store import APP_DIR

CREDENTIALS_FILE = APP_DIR / "credentials.json"


@dataclass
class Credential:
    """One saved account. `password` is empty when the user declined to store it."""

    email: str
    password: str = ""
    remember_password: bool = False
    last_used: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> "Credential":
        return cls(
            email=str(data.get("email", "") or ""),
            password=str(data.get("password", "") or ""),
            remember_password=bool(data.get("remember_password", False)),
            last_used=float(data.get("last_used", 0) or 0),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def list_credentials() -> list[Credential]:
    """Return saved accounts, most recently used first. Never raises."""
    data = _read_all()
    creds = [c for c in (Credential.from_dict(d) for d in data) if c.email]
    return sorted(creds, key=lambda c: (-c.last_used, c.email.lower()))


def get_credential(email: str) -> Optional[Credential]:
    """Return the saved credential for `email`, or None."""
    target = (email or "").strip().lower()
    if not target:
        return None
    for cred in list_credentials():
        if cred.email.strip().lower() == target:
            return cred
    return None


def credential_for_relogin(email: str) -> Optional[str]:
    """Return the stored password for `email`, or None when none is stored.

    This is the gate the UI uses before attempting an automatic re-login: a
    `None` here means the user must be sent to the login dialog.
    """
    cred = get_credential(email)
    if not cred or not cred.password:
        return None
    return cred.password


def save_credential(email: str, password: str, remember_password: bool) -> Optional[Credential]:
    """Insert or update the account, keyed by email, and mark it as just used.

    Passing `remember_password=False` (or an empty password) keeps the account in
    the picker but clears any previously stored password.
    """
    target = (email or "").strip()
    if not target:
        return None

    existing = {c.email.strip().lower(): c for c in list_credentials()}
    cred = existing.get(target.lower()) or Credential(email=target)
    cred.email = target
    cred.remember_password = bool(remember_password)
    cred.password = password if (remember_password and password) else ""
    cred.last_used = time.time()

    merged = [c for c in existing.values() if c.email.strip().lower() != target.lower()]
    merged.append(cred)
    _write_all(merged)
    return cred


def touch_credential(email: str) -> Optional[Credential]:
    """Mark an account as just used, leaving its stored password untouched.

    Called after a successful silent re-login so the account the user actually
    works in floats to the top of the login dialog's account picker.
    """
    cred = get_credential(email)
    if not cred:
        return None
    cred.last_used = time.time()
    target = cred.email.strip().lower()
    merged = [
        c for c in list_credentials() if c.email.strip().lower() != target
    ]
    merged.append(cred)
    _write_all(merged)
    return cred


def delete_credential(email: str) -> bool:
    """Forget an account. Returns True when something was actually removed."""
    target = (email or "").strip().lower()
    if not target:
        return False
    creds = list_credentials()
    kept = [c for c in creds if c.email.strip().lower() != target]
    if len(kept) == len(creds):
        return False
    _write_all(kept)
    return True


def _read_all() -> list[dict]:
    if not CREDENTIALS_FILE.exists():
        return []
    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = data.get("credentials") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [d for d in items if isinstance(d, dict)]


def _write_all(creds: list[Credential]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"credentials": [c.to_dict() for c in sorted(
        creds, key=lambda c: (-c.last_used, c.email.lower())
    )]}
    tmp = CREDENTIALS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(CREDENTIALS_FILE)
    _restrict_permissions(CREDENTIALS_FILE)


def _restrict_permissions(path: Path) -> None:
    """Best-effort owner-only access (no-op semantics on Windows)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
