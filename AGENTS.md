# Naukri Profile Manager — AGENTS.md

Cross-platform (Windows/macOS/Linux) PySide6 desktop app for viewing/updating a Naukri
profile, fully headless over HTTP (no browser, Selenium or Playwright).

## Commands

- Install: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Run: `python src/main.py` (or `pip install -e . && naukri-profile-update`). Must run inside the venv — `src/main.py` hard-exits unless `VIRTUAL_ENV` is set or `sys.frozen` (packaged exe exempt).
- Headless UI import smoke test (the only real check — **no test/lint/typecheck tooling is configured**, don't invent commands):
  `QT_QPA_PLATFORM=offscreen python -c "from src.ui.main_window import MainWindow"`
- Build: `python build.py` (onedir), `--onefile`, `--versioned` (implies `--onefile`). Auto-installs PyInstaller; `build_windows.bat` helper. `--version X` rewrites `_FALLBACK_VERSION` in `src/core/version.py` → check `git status` afterwards.
- `pyproject.toml` uses `[tool.setuptools.packages.find] include = ["src", "src.*"]` — keep auto-discovery; a hand-maintained list once silently omitted all six `src.core.nope_ri*` subpackages.

## Wiring you can't infer from filenames

- `src/main.py` entry: `while True` loop — closing the window ends the loop; logout returns to the `LoginDialog` via `MainWindow.relogin_requested` instead of exiting; the loop-local `prefill_email` carries the dead account into the next login. Keep the loop; don't simplify it away.
- `src/main.py` inserts repo `ROOT` into `sys.path` so `src.*` imports work from the repo root *and* the PyInstaller `_MEIPASS` bundle — keep it.
- Layout: `src/core` (NaukriManager, ApiWorker, session/settings/credentials/update_check/version/AI/resume + vendored NopeRi in `src/core/nope_ri`), `src/models`, `src/ui` (one module per tab). Vendored NopeRi uses **relative** imports (upstream absolute — re-apply on sync); mostly unused upstream cruft, leave alone.
- App version: `src/core/version.py` reads `[project] version` from pyproject, falls back to `_FALLBACK_VERSION` when frozen; the release CI bumps both — keep in sync.

## Runtime gotchas

- All blocking Naukri HTTP must run through `ApiWorker` (`src/core/worker.py`). Every live worker registers in module-level `_ACTIVE` and releases on `finished`; reassign the worker attribute between runs. `ApiWorker.shutdown(timeout_ms)` is mandatory before Qt teardown (retry helper sleeps up to 60s between attempts; falls back to `terminate()`).
- httpcloak stores cookies as a plain `list` of `Cookie` objects, **not** a `RequestsCookieJar` — use `src/core/nope_ri/utils/cookies.py` only (`get_cookie`, `cookies_to_dict`, `set_cookies`); `set_cookies` must call httpcloak's native `session.set_cookie(...)` — `.cookies` is copy-on-read, so appending is a no-op that yields a session with zero cookies.
- Every public `NaukriManager` method wraps its body in `self._guard_auth(...)`; the hook must be a `Signal.emit`, not a plain callable (it runs on the worker thread). `NaukriAuthError` (401/403 via `_check_response`) triggers auto re-login; everything else goes straight to the error dialog. `_notified_error` dedupes nested guards; `_recovering` blocks rejected-password loops.
- **A 2xx is not proof a save worked** — check `result.status_code` and the error envelope (`EditTab._on_saved`).

## Naukri HTTP contract (hard-won — don't regress)

- Read profile: `GET .../v2/users/self?expand_level=3` (`FULL_PROFILE_URL`) — rich payload under `profile[0]`. `fullprofiles` is **write-only** (GET 405/500) and is what updates POST to with `x-http-method-override: PUT`. The `PROFILE_FETCH_URL` constant in `nope_ri/config/constants.py` is a dead constant pointing at the write-only endpoint.
- Position is NOT `role` — parsed from root `employments[]` (current entry, or latest by `startDate`) via `designation`.
- Resume download: `GET /v1/users/self/profiles/{pid}/resume` with `content-type: application/pdf` and **`Accept` left at `application/json`** (Accept: application/pdf → **406**). Require a `%PDF-` marker in the first 1 KiB or raise; a dead-but-not-yet-401 session answers with the HTML login page and the refresh would rename/re-upload it over the real resume. 401/403 stay `NaukriAuthError`.
- formKey: scraped live via `get_form_key2()` from the `mnj_v<NNN>.min.js` bundle (`attachCV` pattern) — never hardcode; do not re-add the app-shell `formKey="..."` pattern or a hardcoded bundle URL/version.
- `_fetch_js()` must use plain `requests` (httpcloak serves cached static assets as 304 with an **empty body**). Auth scheme: cloudgateway = Bearer; `/mnjapi/*` = cookie-only (Bearer → `401 4012 "Invalid scheme name"`).
- Resume re-upload: `POST https://filevalidation.naukri.com/file` (multipart `formKey`/`file`/`fileName`/`uploadCallback`/`fileKey`; `appid: 105` + `systemid: fileupload` are headers) then `POST .../resman-aggregator-services/v0/users/self/profiles/{pid}/advResume` with `x-http-method-override: PUT` and `{"textCV": {"formKey": ..., "fileKey": ...}}` → `200 {"status": true}`. URL template MUST be `.format(profile_id=pid)`; `_validate_file_request` MUST use the httpcloak session; 404 "OCS Service" = wrong fileKey/formKey pair; tokens 1h TTL, check `exp` first.
- Resume text: `src/core/resume_text.py` via pypdf; PDF only, else `ResumeTextError`.

## UI conventions

- Status/error QLabels must not force window width: use `make_wrapping_status_label()` (box) / `make_wrapping_form_label()` (QFormLayout) from `src/ui/_label_utils.py`; never a raw wordWrap `QLabel`.
- Tabs: Profile · Edit · Refresh · Settings · About always visible; Developer added *after* About only when `settings.show_developer`. Resume download lazy via `ensure_resume_loaded()` on first tab show, not from `set_profile`.
- Dead-session recovery: on `NaukriAuthError` only → `_try_auto_relogin()`; 500/other → error dialog, no re-login. After relogin success, re-run `refresh_profile()` only when the initial load died; for save/refresh show "Session Renewed / try again".
- AI optimizer: resume download lazy; snapshot settings via `dataclasses.replace`; `FIELD_LIMITS` Headline (0,250), Summary (50,1000); `rewrite()` asks for 90–100% of budget then auto-clips; AI never falls back to Ollama (uses `settings.ai_provider` verbatim, `base_url_misconfig` guardrail); OpenAI-compatible `{base}/chat/completions` vs native Anthropic `{base}/messages`; `_models_cache` class-level keyed by `(provider, base_url, api_key)`.

## Naukri constraints / storage / credentials

- No public Naukri API; sessions IP-bound (IP change → re-login, expected); datacenter/cloud IPs flagged; OTP/MFA out of MVP scope.
- Session/cookie/settings/credentials live in `~/.naukri-profile-update/` (`session.json`, `config.json`, `credentials.json`). Passwords are cleartext **by choice** (written only when the login dialog's "Remember password" box is ticked, purged when unticked; file `chmod 600` best-effort). `NaukriManager.logout()` must NOT delete saved credentials. `save_credential` owns the password; `ensure_credential` adds/refreshes an email-only account (used by the browser/inject login helpers) and never touches an existing stored password.
- `NaukriManager` wraps `NaukriLoginClient`; each network call splits into a decorated `_foo_request(...)` (raw I/O, wrapped in `with_exponential_retry` — 5 attempts, exponential backoff + jitter, retries 429/5xx) and an undecorated `foo(...)` holding parsing/raising.

## Update notifications

- Plain `requests` only (never the httpcloak session, never behind `_guard_auth`), no `with_exponential_retry`, short timeout (5s auto / 15s manual), failures silent (`logger.debug` + "unavailable" status), one nag per version, strict `X.Y.Z` compare (`parse_version` → 3-tuple, no `packaging` dep). Keep the About status line short — it sits in a `QFormLayout` with horizontal `Preferred`; release URL/notes go in the dialog only.

## Login helper (captcha workaround)

- Password login is captcha-gated; a 403 body carrying `captchaSiteKey` raises `NaukriCaptchaError` (a `NaukriAuthError` subclass). `LoginDialog` catches that type:
  - **Source checkout**: auto-runs `python login_via_browser.py --channel chrome --verify -e <email>` via `QProcess`, then adopts the verified session it saves. Needs `requirements-dev.txt` (playwright; `python -m playwright install chromium` for `--channel chromium`). `python inject_session.py --from-browser chrome -e <email> --verify` is the manual alternative.
  - **Frozen/standalone build** (the `.exe` users download): `login_via_browser.py` is not bundled, so the dialog opens `https://www.naukri.com/nlogin/login` in the user's default browser via `QDesktopServices.openUrl()`, shows a "Paste your session token" field, and the user pastes their `nauk_at` cookie or Bearer token after logging in manually (captcha included). Accepts bare token, `nauk_at=...`, raw Cookie header, or `Bearer ...` formats. The token is saved to `session.json` and the app auto-logs in from then on.
- Both helpers call `ensure_credential()` so the account is remembered without touching any stored password.

## Packaging

- PyInstaller: no cross-compile; needs `--paths ROOT --windowed`; spec is generated and gitignored — edit `build.py`; httpcloak native lib must go to bare `httpcloak/lib` dir; keep `--collect-all PySide6 --collect-all shiboken6`; install `PySide6-Essentials` not `PySide6`; keep Designer plugin parking in `build.py`.
- `_version_info()` sanitizer: Windows VERSIONINFO needs strictly numeric 4-part vers/`prodvers`; PyInstaller evals the file as Python — keep the sanitizer.

## CI / release

- 4-job matrix (windows/ubuntu/macos-15-intel/macos-15 arm64, py3.12) runs `python build.py --onefile --versioned --version <NEXT>`; every push to `master` auto-releases; release job bumps version + `_FALLBACK_VERSION`, rewrites README version strings, commits `chore(release): v<NEXT> [skip ci]`, pushes tag, publishes via `gh release create`; duplicate-tag guard.
- Don't hand-bump README version strings (bot regexes every `vX.Y.Z` / `-X.Y.Z-`).
- Pin `actions/upload-artifact@v4.6.2+`; `gh run upload` doesn't exist. Expected noise: macOS Node 20 deprecation (→Node 24); Linux `libxcb-*.so` WARNINGs (non-fatal).
