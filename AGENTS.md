# Naukri Profile Manager — AGENTS.md

Cross-platform (Windows/macOS/Linux) PySide6 desktop app for viewing/updating a
Naukri profile, fully headless over HTTP.

## Commands

- Install deps: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Run the app: `python src/main.py` (or `pip install -e . && naukri-profile-update`)
- Headless UI smoke test: `QT_QPA_PLATFORM=offscreen python -c "from src.ui.main_window import MainWindow; ..."`
- Build executable: `source .venv/bin/activate && python build.py` (add `--onefile` for single file)
- No lint/test/typecheck tooling is configured.

## Key architecture facts (would cost time to rediscover)

- `src/main.py` must insert `ROOT` into `sys.path` so `src` is importable from the
  repo root and inside a PyInstaller bundle. Keep that.
- `src/main.py` also refuses to run outside a virtualenv (exits with a message to
  stderr). The guard exempts `sys.frozen` builds so the packaged app still runs —
  do not remove the frozen exemption, or the distributed executable breaks.
- Naukri interaction lives in `src/core/nope_ri/` — a **vendored** copy of
  [NopeRi](https://github.com/Traverser25/NopeRi), edited so its absolute
  `from src...` imports became **relative** (`from .session import ...`, etc.).
  When syncing upstream, re-apply those import edits or the package breaks.
- `NaukriManager` (in `src/core/naukri_client.py`) wraps the vendored client. Its
  `fetch_profile()` is a **custom addition** that does a **GET to the rich read
  endpoint** (`GET /v2/users/self?expand_level=3`), NOT the dashboard or
  `fullprofiles`. `fullprofiles` is write/update-only (GET returns 405/500); the
  raw dashboard (`/v0/users/self/dashboard`) only carries basic identity. The
  `v2/users/self?expand_level=3` endpoint returns headline (`resumeHeadline`),
  summary, skills (`keySkills`), resume metadata (`cvInfo`, incl. `fileName`,
  `cvFormat`, `uploadDate`), name, `role.value`, city, `experience{month,year}`,
  CTC, notice period, etc., all under `profile[0]`. Do not revert to dashboard-only.
- Resume **download**: `GET /v1/users/self/profiles/{profile_id}/resume` with
  `content-type: application/pdf` (Accept must stay `application/json` — setting
  `Accept: application/pdf` returns **406**). `NaukriManager.refresh_resume()`
  downloads the on-file PDF, renames it to `Name_Position_Month_Day_Updated.pdf`
  (e.g. `Aman_Ojha_Software_Developer_September_1_Updated.pdf`) and re-uploads it.
  The renaming helper `_refresh_filename()` lives in `src/core/naukri_client.py`.
- `Profile.from_raw` in `src/models/profile.py` tolerates dict, `{dashBoard: ...}`
  and a single-element list `[{...}]` (which is what `fullprofiles` responses use).
- **httpcloak stores cookies as a `list` of `Cookie` objects, not a
  `RequestsCookieJar`.** The vendored NopeRi assumed `session.cookies.get(name)`,
  `.update()`, `.get_dict()` — all broken under httpcloak. Access cookies only via
  `src/core/nope_ri/utils/cookies.py` (`get_cookie`, `cookies_to_dict`,
  `set_cookies`). The vendored `login()`/`verify_otp()` were patched to use them.
- All blocking network calls MUST go through `ApiWorker` (a `QThread` in
  `src/core/worker.py`). Running Naukri HTTP on the UI thread freezes the app.
- Session persistence: `src/core/session_store.py` writes `~/.naukri-profile-update/session.json`
  (Bearer `nauk_at` token + cookies).
- App settings (Developer toggle + AI provider) live in `~/.naukri-profile-update/config.json`,
  managed by `src/core/settings.py` (`AppSettings` + `load_settings`/`save_settings`).
- The UI has a **Settings** tab (always visible) and a **Developer** tab that is
  **hidden unless** `settings.show_developer` is enabled (toggled in the Settings tab).
  `DeveloperTab` holds experimental tools; the first is an **AI field optimizer** that
  rewrites a chosen profile field using `src/core/ai_client.py`.
- `AiClient` is provider-agnostic with two chat paths: **OpenAI-compatible**
  `{base_url}/chat/completions` (OpenAI, Google Gemini, OpenRouter, Ollama,
  custom/LiteLLM) and **native Anthropic** `{base_url}/messages` (Claude).
  Base URL/model/API key come from settings; use a `QThread` (via `ApiWorker`)
  for these blocking calls.
- Settings **Model** field is an editable `QComboBox` with a "Load models" button
  that calls `AiClient.list_models()` (a `GET {base_url}/models` fetch of
  `data[].id`) and auto-reloads on provider change. The button is disabled until
  an API key is entered for key-required providers (all except Ollama).
  Claude's list fetch uses Anthropic-native headers (`anthropic-version`,
  `x-api-key`); the OpenAI-compatible providers use `Authorization: Bearer`.

## Naukri constraints you must respect

- **No public API.** Internal services (`central-login-services`, `cloudgateway-mynaukri`,
  `filevalidation.naukri.com`) can change/break without notice.
- **Sessions are IP-bound.** An IP change invalidates login → user must re-login.
  This is expected behavior, surfaced in the UI, not a bug.
- **Datacenter/cloud IPs (Azure, Google Cloud, GitHub Actions) are flagged** and often
  force MFA or block. Home/residential IPs are the reliable path.
- **OTP/MFA is out of MVP scope** for the login dialog; `send_otp`/`verify_otp` exist in
  the vendored client for future use.
- Vendored `session.py` uses `httpcloak` by default (or `curl_cffi` if httpcloak throws
  a permission error on Windows — flip `USE_CURL_CFFI` there).

## Packaging gotchas

- PyInstaller does **not** cross-compile: build each OS on that OS.
- `--paths ROOT` and `--windowed` in `build.py` are required (GUI, headless).
- **httpcloak's native `.so`/`.dll`/`.dylib` is NOT auto-collected by PyInstaller.**
  `build.py` locates and `--add-binary`s it into `httpcloak/lib/` (matching httpcloak's
  runtime search path). If you see "Could not find httpcloak library" in the packaged
  app, that bundling step broke — do not remove it. Also, the `--add-binary` destination
  must be the bare directory `httpcloak/lib` (no trailing filename), or PyInstaller
  nests the file inside a subdirectory of its own name and loading fails.
- Unsigned macOS builds show a Gatekeeper prompt (documented in README).