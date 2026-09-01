from typing import Optional

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

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _refresh_filename(profile: Profile) -> str:
    """Build `FullName_Position_Month_Day_Updated.pdf`."""
    from datetime import datetime

    now = datetime.now()
    name = " ".join(profile.name.split()).replace(" ", "_") if profile.name else "Profile"
    position = " ".join(profile.position.split()).replace(" ", "_") if profile.position else "Position"
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
        self._inject_saved_session(session_data or (
            session_store.load_session() if use_saved_session else None
        ))

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
        self._require_auth()
        resp = self.client._fetch_full_profile()
        if not resp.ok:
            raise NaukriParseError(f"profile fetch failed ({resp.status_code})")
        try:
            data = resp.json()
        except Exception as exc:
            raise NaukriParseError("profile fetch returned non-JSON response") from exc
        return Profile.from_raw(data)

    def download_resume(self) -> bytes:
        """Download the current on-file Naukri resume as raw PDF bytes."""
        self._require_auth()
        return self.client.download_resume()

    def update_profile(
        self, headline: Optional[str] = None, name: Optional[str] = None, summary: Optional[str] = None,
    ) -> ProfileUpdateResult:
        self._require_auth()
        return self.client.update_profile(
            headline=headline, name=name, summary=summary
        )

    def upload_resume(self, pdf_path: str) -> ResumeUpdateResult:
        self._require_auth()
        return self.client.update_resume(pdf_path)

    def refresh_resume(self) -> str:
        """Download the on-file resume, rename to the `Name_Position_Month_Day_Updated.pdf`
        pattern and re-upload it. Returns the new filename."""
        from io import BytesIO

        profile = self.fetch_profile()
        new_name = _refresh_filename(profile)
        content = self.client.download_resume()
        stream = BytesIO(content)
        stream.name = new_name  # vendored validate_file() uses file.name for upload
        self._require_auth()
        result = self.client.update_resume(stream)
        if result.status_code != 200:
            raise NaukriParseError(f"resume re-upload failed ({result.status_code})")
        return new_name