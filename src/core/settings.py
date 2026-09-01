import json
from dataclasses import asdict, dataclass

from src.core.session_store import APP_DIR

CONFIG_FILE = APP_DIR / "config.json"

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