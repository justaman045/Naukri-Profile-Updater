import json
from dataclasses import asdict, dataclass

from src.core.session_store import APP_DIR

CONFIG_FILE = APP_DIR / "config.json"

# Provider keys considered to use the local Ollama server (localhost:11434).
_OLLAMA_PROVIDERS = {"ollama"}


def base_url_misconfig(provider: str, base_url: str) -> str | None:
    """Return an actionable message if provider/base_url are inconsistent.

    The real risk is a stale base URL pointing at the local Ollama server while
    a non-Ollama provider is selected (the app never falls back to Ollama on its
    own). Returns None when the combination is consistent.
    """
    url = (base_url or "").rstrip("/")
    if not url:
        if provider not in _OLLAMA_PROVIDERS and provider:
            return (
                "Base URL is empty. Set it in the Settings tab for this provider."
            )
        return None
    is_ollama_url = _looks_like_ollama(url)
    if is_ollama_url and provider not in _OLLAMA_PROVIDERS:
        return (
            f"Selected provider is '{provider}' but the Base URL points at the "
            f"local Ollama server ({url}). Fix the Base URL in Settings."
        )
    return None


def _looks_like_ollama(url: str) -> bool:
    try:
        from urllib.parse import urlparse

        parts = urlparse(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return host in ("localhost", "127.0.0.1") and parts.port in (None, 11434)

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "claude": "https://api.anthropic.com/v1",
    "ollama": "http://localhost:11434/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "custom": "",
}

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "claude": "Anthropic Claude",
    "ollama": "Ollama (local)",
    "openrouter": "OpenRouter",
    "custom": "Custom",
}


@dataclass
class AppSettings:
    show_developer: bool = False
    ai_provider: str = "openai"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = ""

    @property
    def effective_base_url(self) -> str:
        if self.ai_base_url:
            return self.ai_base_url.rstrip("/")
        return DEFAULT_BASE_URLS.get(self.ai_provider, "").rstrip("/")

    @property
    def ai_configured(self) -> bool:
        base = self.effective_base_url
        if not base:
            return False
        if self.ai_provider == "ollama":
            return bool(self.ai_model)
        return bool(self.ai_model and self.ai_api_key)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        return cls(
            show_developer=bool(data.get("show_developer", False)),
            ai_provider=data.get("ai_provider", "openai"),
            ai_base_url=data.get("ai_base_url", ""),
            ai_model=data.get("ai_model", ""),
            ai_api_key=data.get("ai_api_key", ""),
        )


def load_settings() -> AppSettings:
    if not CONFIG_FILE.exists():
        return AppSettings()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return AppSettings.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)