import json

import requests

from src.core.settings import AppSettings, base_url_misconfig

ANTHROPIC_VERSION = "2023-06-01"


class AiError(Exception):
    """Raised when the configured AI provider cannot complete a request."""


SYSTEM_PROMPT = (
    "You are an expert Naukri profile optimization assistant. Rewrite the given "
    "profile field to make it concise, keyword-rich, ATS-friendly and compelling "
    "for recruiters. Return only the rewritten text, nothing else."
)

# Naukri per-field character limits (verified: web sources + live save HTTP-400 record).
# Each value is (min, max); a field with no min uses 0.
FIELD_LIMITS = {
    "Headline": (0, 250),
    "Summary": (50, 1000),
}


def field_max(field_name: str) -> int:
    """Return the Naukri max character length for a field (0 if unknown)."""
    limits = FIELD_LIMITS.get(field_name, (0, 0))
    return limits[1]


# Providers whose chat completes via the OpenAI-compatible /chat/completions path.
_OPENAI_COMPAT_PROVIDERS = {"openai", "gemini", "openrouter", "custom", "ollama"}


def _provider_requires_key(provider: str) -> bool:
    return provider != "ollama"


def _provider_error_message(payload) -> str | None:
    """Extract a human-friendly error message from a provider response body."""
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        msg = error.get("message")
        if msg:
            return str(msg)
        msg = error.get("type")
        if msg:
            return str(msg)
        return None
    if isinstance(error, str) and error:
        return error
    detail = payload.get("detail")
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict):
        msg = detail.get("message")
        if msg:
            return str(msg)
        if detail.get("msg"):
            return str(detail["msg"])
    return None


def _extract_choice_text(message: object) -> str:
    """Return the assistant text from an OpenAI-compatible message.

    Handles ``content`` as a plain string or a list of ``{type, text}`` blocks
    (multimodal / some providers). Raises if nothing recognizable is found.
    """
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            blocks = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text") or block.get("content")
                    if isinstance(text, str) and text:
                        blocks.append(text)
                elif isinstance(block, str) and block:
                    blocks.append(block)
            if blocks:
                return "\n".join(blocks)
        text = message.get("text")
        if isinstance(text, str):
            return text
    raise ValueError("assistant message has no text content")


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
        mismatch = base_url_misconfig(
            self.settings.ai_provider, self.settings.effective_base_url
        )
        if mismatch:
            raise AiError(mismatch)

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
    def rewrite(self, field_name: str, current_value: str,
                resume_text: str = "") -> str:
        if not self.settings.ai_configured:
            raise AiError(
                "AI is not configured. Set a base URL, model and (if required) an "
                "API key in the Settings tab."
            )
        mismatch = base_url_misconfig(
            self.settings.ai_provider, self.settings.effective_base_url
        )
        if mismatch:
            raise AiError(mismatch)
        resume_block = (
            "My current resume (full text):\n"
            "===== BEGIN RESUME =====\n"
            f"{resume_text}\n"
            "===== END RESUME =====\n"
            if resume_text.strip()
            else ""
        )
        limits = FIELD_LIMITS.get(field_name, (0, 0))
        min_len, max_len = limits
        if max_len:
            limit_lines = [
                f"- Maximum length: {max_len} characters (do NOT exceed this).",
            ]
            if min_len:
                limit_lines.append(f"- Minimum length: {min_len} characters.")
            limit_lines.append(
                f"- Aim to use roughly 90-100% of the {max_len}-character budget with "
                "keyword-rich, ATS-friendly content. No filler, no padding, no "
                "explanations."
            )
            limit_rule = "\n".join(limit_lines)
        else:
            limit_rule = (
                "Keep it concise and within the platform limit for this field; use "
                "keywords, no filler, no explanations."
            )
        prompt = (
            f"Rewrite the '{field_name}' field for my Naukri profile.\n"
            f"{resume_block}"
            f"Current {field_name} value: {current_value!r}\n\n"
            "Requirements for this field on Naukri:\n"
            f"{limit_rule}"
        )
        text = self._openai_compat_rewrite(prompt) \
            if self.settings.ai_provider != "claude" else self._claude_rewrite(prompt)
        if max_len and len(text) > max_len:
            text = text[:max_len].strip()
        return text

    @staticmethod
    def _parse_json_body(res: requests.Response) -> dict:
        try:
            data = res.json()
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _build_error(prefix: str, res: requests.Response, parsed: dict) -> str:
        status = res.status_code
        msg = _provider_error_message(parsed)
        if msg:
            return f"{prefix} ({status}): {msg}"
        snippet = (res.text or "").strip().replace("\n", " ")[:200]
        if snippet:
            return f"{prefix} ({status}): {snippet}"
        return f"{prefix} (HTTP {status})."

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
        parsed = self._parse_json_body(res)
        if not res.ok or _provider_error_message(parsed) is not None:
            raise AiError(self._build_error("AI request failed", res, parsed))
        try:
            choices = parsed["choices"]
            content = _extract_choice_text(choices[0].get("message"))
            return content.strip()
        except (TypeError, KeyError, IndexError, AttributeError, ValueError) as exc:
            raise AiError(self._build_error("Unexpected AI response from provider", res, parsed)) from exc

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
        parsed = self._parse_json_body(res)
        if not res.ok or _provider_error_message(parsed) is not None:
            raise AiError(self._build_error("AI request failed", res, parsed))
        try:
            content = parsed["content"]
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return "".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("text")
                ).strip()
            raise ValueError("claude content has unexpected shape")
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            raise AiError(self._build_error("Unexpected AI response from provider", res, parsed)) from exc

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