import json

import requests

from src.core.settings import AppSettings

ANTHROPIC_VERSION = "2023-06-01"


class AiError(Exception):
    """Raised when the configured AI provider cannot complete a request."""


SYSTEM_PROMPT = (
    "You are an expert Naukri profile optimization assistant. Rewrite the given "
    "profile field to make it concise, keyword-rich, ATS-friendly and compelling "
    "for recruiters. Return only the rewritten text, nothing else."
)

# Providers whose chat completes via the OpenAI-compatible /chat/completions path.
_OPENAI_COMPAT_PROVIDERS = {"openai", "gemini", "openrouter", "custom", "ollama"}


def _provider_requires_key(provider: str) -> bool:
    return provider != "ollama"


class AiClient:
    """Provider-agnostic chat client.

    OpenAI-compatible providers (OpenAI, Gemini, OpenRouter, custom/LiteLLM,
    Ollama) use ``POST {base_url}/chat/completions``. Anthropic Claude uses its
    native ``POST {base_url}/messages``. Model lists are fetched from each
    provider's ``GET {base_url}/models`` endpoint.
    """

    def __init__(self, settings: AppSettings, timeout: int = 90):
        self.settings = settings
        self.timeout = timeout
        self._models_cache: tuple = (None, None, None, None)  # (provider, base, key, models)

    # ------------------------------------------------------------------
    # Auth / headers
    # ------------------------------------------------------------------
    def _openai_headers(self) -> dict:
        headers = {"content-type": "application/json"}
        if self.settings.ai_api_key:
            headers["authorization"] = f"Bearer {self.settings.ai_api_key}"
        return headers

    def _claude_headers(self) -> dict:
        return {
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "x-api-key": self.settings.ai_api_key,
        }

    # ------------------------------------------------------------------
    # Model listing
    # ------------------------------------------------------------------
    def list_models(self, force: bool = False) -> list[str]:
        """Fetch available model IDs from the configured provider."""
        if not self.settings.effective_base_url:
            raise AiError("AI is not configured. Set a base URL in the Settings tab.")

        key = (self.settings.ai_provider, self.settings.effective_base_url,
               self.settings.ai_api_key)
        if not force and self._models_cache[:3] == key and self._models_cache[3] is not None:
            return self._models_cache[3]

        provider = self.settings.ai_provider
        url = f"{self.settings.effective_base_url}/models"
        if provider == "claude":
            headers = self._claude_headers()
        else:
            headers = self._openai_headers()

        res = requests.get(url, headers=headers, timeout=self.timeout)
        if not res.ok:
            detail = res.text[:200]
            if res.status_code in (401, 403):
                raise AiError(f"Auth failed while listing models ({res.status_code}). "
                              f"Check your API key / base URL. {detail}")
            raise AiError(f"Failed to list models ({res.status_code}): {detail}")

        model_ids = self._parse_models(res.json())
        self._models_cache = (*key, model_ids)
        return model_ids

    def _parse_models(self, payload) -> list[str]:
        ids = []
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("id"):
                        ids.append(str(item["id"]))
        # Deduplicate, keep order.
        seen = set()
        out = []
        for m in ids:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return sorted(out)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def rewrite(self, field_name: str, current_value: str) -> str:
        if not self.settings.ai_configured:
            raise AiError(
                "AI is not configured. Set a base URL, model and (if required) an "
                "API key in the Settings tab."
            )
        prompt = (
            f"Rewrite the '{field_name}' field for my Naukri profile.\n"
            f"Current value: {current_value!r}\n\n"
            "Rules: keep it under the platform limit for this field, use keywords, "
            "no filler, no explanations."
        )
        if self.settings.ai_provider == "claude":
            return self._claude_rewrite(prompt)
        return self._openai_compat_rewrite(prompt)

    def _openai_compat_rewrite(self, prompt: str) -> str:
        url = f"{self.settings.effective_base_url}/chat/completions"
        payload = {
            "model": self.settings.ai_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        res = requests.post(
            url, headers=self._openai_headers(), json=payload, timeout=self.timeout
        )
        if not res.ok:
            raise AiError(f"AI request failed ({res.status_code}): {res.text[:300]}")
        try:
            return res.json()["choices"][0]["message"]["content"].strip()
        except (TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AiError(f"Unexpected AI response: {res.text[:300]}") from exc

    def _claude_rewrite(self, prompt: str) -> str:
        url = f"{self.settings.effective_base_url}/messages"
        payload = {
            "model": self.settings.ai_model,
            "max_tokens": self._claude_max_tokens(),
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }
        res = requests.post(
            url, headers=self._claude_headers(), json=payload, timeout=self.timeout
        )
        if not res.ok:
            raise AiError(f"AI request failed ({res.status_code}): {res.text[:300]}")
        try:
            content = res.json()["content"]
            return "".join(block.get("text", "") for block in content).strip()
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise AiError(f"Unexpected AI response: {res.text[:300]}") from exc

    def _claude_max_tokens(self) -> int:
        try:
            models = self.list_models(force=False)
        except Exception:
            models = []
        if self.settings.ai_model in models:
            try:
                url = f"{self.settings.effective_base_url}/models/{self.settings.ai_model}"
                res = requests.get(url, headers=self._claude_headers(), timeout=self.timeout)
                if res.ok:
                    info = res.json()
                    mt = info.get("max_tokens") or info.get("max_output_tokens")
                    if isinstance(mt, int) and mt > 0:
                        return mt
            except Exception:
                pass
        return 2048