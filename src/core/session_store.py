import json
from pathlib import Path

APP_DIR = Path.home() / ".naukri-profile-update"
SESSION_FILE = APP_DIR / "session.json"


class SessionData:
    """Serializable representation of a Naukri session."""

    def __init__(self, username: str, bearer_token: str, cookies: dict):
        self.username = username
        self.bearer_token = bearer_token
        self.cookies = cookies  # {name: value}

    @classmethod
    def from_json(cls, data: dict) -> "SessionData":
        return cls(
            username=data.get("username", ""),
            bearer_token=data.get("bearer_token", ""),
            cookies=data.get("cookies", {}),
        )

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "bearer_token": self.bearer_token,
            "cookies": self.cookies,
        }


def save_session(session_data: SessionData) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(session_data.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(SESSION_FILE)


def load_session() -> SessionData | None:
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        if not data.get("bearer_token"):
            return None
        return SessionData.from_json(data)
    except (json.JSONDecodeError, OSError):
        return None


def clear_session() -> None:
    try:
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
    except OSError:
        pass