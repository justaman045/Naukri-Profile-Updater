from typing import Callable, Optional, TypeVar
import re

from src.core.nope_ri.client.naukri_client import NaukriLoginClient
from src.core.nope_ri.exceptions.exceptions import NaukriAuthError, NaukriParseError
from src.core.nope_ri.models.models import (
    NaukriSession,
    ProfileUpdateResult,
    ResumeUpdateResult,
)
from src.core.nope_ri.utils.cookies import cookies_to_dict, set_cookies
from src.core import session_store
from src.models.profile import Profile

T = TypeVar("T")

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _file_safe(value: str) -> str:
    """Collapse whitespace and drop characters that break a filename."""
    return "_".join(re.sub(r"[^A-Za-z0-9 _-]", "", value).split())


def _check_response(resp, what: str) -> None:
    """Raise a typed error for a non-ok response.

    401/403 becomes `NaukriAuthError` so the UI can distinguish "the restored
    session is dead" (worth an automatic re-login) from a server hiccup or a
    parse problem. Every other non-ok status stays a `NaukriParseError`, and the
    status code is always carried in the message.
    """
    if resp.ok:
        return
    if resp.status_code in (401, 403):
        raise NaukriAuthError(f"{what} — session invalid ({resp.status_code})")
    raise NaukriParseError(f"{what} failed ({resp.status_code})")


def _refresh_filename(profile: Profile) -> str:
    """Build `FullName_Position_Month_Day_Updated.pdf`."""
    from datetime import datetime

    now = datetime.now()
    name = _file_safe(profile.name) if profile.name else "Profile"
    position = _file_safe(profile.position) if profile.position else "Position"
    month = _MONTHS[now.month - 1]
    day = now.day
    return f"{name}_{position}_{month}_{day}_Updated.pdf"


class NaukriManager:
    """High-level wrapper around the vendored NopeRi client plus profile
    display support (which NopeRi does not provide natively)."""

    def __init__(
        self,
        username: str,
        password: str,
        use_saved_session: bool = True,
        session_data: Optional[session_store.SessionData] = None,
    ):
        self.client = NaukriLoginClient(username, password)
        self.username = username
        self.use_saved_session = use_saved_session
        self._auth_failure_hook: Optional[Callable[[Exception], None]] = None
        self._notified_error: Optional[Exception] = None
        self._recovering = False
        # Which public operation was running when the last auth failure was
        # reported. The UI reads this to decide whether a successful re-login
        # should re-run the profile load (it would clobber unsaved Edit input
        # otherwise). Set immediately before the hook fires, so it is safe to
        # read inside the hook.
        self.failed_op: str = ""
        self._inject_saved_session(session_data or (
            session_store.load_session() if use_saved_session else None
        ))

    def set_auth_failure_hook(self, hook: Optional[Callable[[Exception], None]]) -> None:
        """Register a callback for "this session is dead, try to recover".

        Fires for *every* operation that ends in a `NaukriAuthError`, not just
        the initial profile fetch, so a save, download or resume refresh during a
        dead session can trigger the automatic re-login too.

        The hook is invoked on whichever thread raised — an `ApiWorker` thread —
        so an implementation must marshal to the UI thread itself.
        `MainWindow` registers a `Signal.emit` for exactly that reason.
        """
        self._auth_failure_hook = hook

    def _guard_auth(self, op: str, fn: Callable[..., T], *args, **kwargs) -> T:
        """Run `fn`, notifying the auth-failure hook exactly once on a dead session.

        `op` names the public operation ("fetch_profile", "update_profile", …) so
        the UI can tell an initial-load failure from a mid-operation one. Nested
        guards share one notification: `refresh_resume()` calls
        `fetch_profile()`, so the same exception object travels through two
        wrappers. Identity comparison against the last notified exception keeps
        that to a single hook call while still reporting a *new* failure from a
        later operation.
        """
        try:
            return fn(*args, **kwargs)
        except NaukriAuthError as exc:
            if not self._recovering and self._notified_error is not exc:
                self._notified_error = exc
                self.failed_op = op
                if self._auth_failure_hook is not None:
                    self._auth_failure_hook(exc)
            raise

    def _inject_saved_session(self, data: Optional[session_store.SessionData]) -> None:
        if not data or not data.bearer_token:
            self.has_saved_session = False
            return
        cookies = dict(data.cookies)
        set_cookies(self.client.session, cookies)
        self.client.naukri_session = NaukriSession(data.bearer_token, cookies)
        self.has_saved_session = True

    @property
    def is_logged_in(self) -> bool:
        return self.client.naukri_session is not None

    def login(self) -> bool:
        """Authenticate, then persist the session locally."""
        try:
            self.client.login()
        except Exception:
            self.has_saved_session = False
            raise
        self._persist_session()
        self.has_saved_session = True
        return True

    def relogin_with_saved_password(self) -> bool:
        """Re-authenticate using the password stored for this account.

        Returns True when the session is usable again (it is re-persisted by
        `login()`, so the same manager object stays valid in place). Returns
        False when no password is stored for this account. Raises whatever
        `login()` raises when Naukri rejects the stored credentials, so the
        caller can fall back to the login dialog.
        """
        from src.core.credentials import credential_for_relogin, touch_credential

        password = credential_for_relogin(self.username)
        if not password:
            return False
        # A rejected stored password must not re-enter the recovery path, or the
        # hook would ask for another re-login and loop.
        self._recovering = True
        try:
            self.login()
        finally:
            self._recovering = False
        touch_credential(self.username)
        return True

    def logout(self) -> None:
        session_store.clear_session()
        self.client.naukri_session = None
        self.has_saved_session = False

    def _persist_session(self) -> None:
        if not self.client.naukri_session:
            return
        session_store.save_session(
            session_store.SessionData(
                username=self.username,
                bearer_token=self.client.naukri_session.bearer_token,
                cookies=cookies_to_dict(self.client.session),
            )
        )

    def _require_auth(self):
        if not self.is_logged_in:
            raise NaukriAuthError("Not logged in")

    def fetch_profile(self) -> Profile:
        """Fetch the full current profile from Naukri.

        Uses the rich read endpoint (`/v2/users/self?expand_level=3`) which
        returns headline, summary, skills, resume info (cvInfo), city,
        experience, CTC, notice period and more under `profile[0]`.
        """
        return self._guard_auth("fetch_profile", self._fetch_profile)

    def _fetch_profile(self) -> Profile:
        self._require_auth()
        resp = self.client._fetch_full_profile()
        _check_response(resp, "profile fetch")
        try:
            data = resp.json()
        except Exception as exc:
            raise NaukriParseError("profile fetch returned non-JSON response") from exc
        return Profile.from_raw(data)

    def download_resume(self) -> bytes:
        """Download the current on-file Naukri resume as raw PDF bytes."""
        return self._guard_auth("download_resume", self._download_resume)

    def _download_resume(self) -> bytes:
        self._require_auth()
        return self.client.download_resume()

    def update_profile(
        self, headline: Optional[str] = None, name: Optional[str] = None, summary: Optional[str] = None,
    ) -> ProfileUpdateResult:
        return self._guard_auth(
            "update_profile", self.client.update_profile,
            headline=headline, name=name, summary=summary,
        )

    def upload_resume(self, pdf_path: str) -> ResumeUpdateResult:
        return self._guard_auth("upload_resume", self.client.update_resume, pdf_path)

    def refresh_resume(self) -> str:
        """Download the on-file resume, rename to the `Name_Position_Month_Day_Updated.pdf`
        pattern and re-upload it. Returns the new filename."""
        return self._guard_auth("refresh_resume", self._refresh_resume)

    def _refresh_resume(self) -> str:
        from io import BytesIO

        # Calls the *public* fetch_profile(), so this really is a nested guard.
        # `_guard_auth` notifies once for the same exception object.
        profile = self.fetch_profile()
        new_name = _refresh_filename(profile)
        content = self.client.download_resume()
        stream = BytesIO(content)
        stream.name = new_name  # vendored validate_file() uses file.name for upload
        self._require_auth()
        result = self.client.update_resume(stream)
        if result.status_code != 200:
            detail = str(result.raw_response)[:200] if result.raw_response else ""
            if result.status_code in (401, 403):
                raise NaukriAuthError(
                    f"resume re-upload rejected — session invalid ({result.status_code}) {detail}".strip()
                )
            raise NaukriParseError(f"resume re-upload failed ({result.status_code}) {detail}".strip())
        return new_name