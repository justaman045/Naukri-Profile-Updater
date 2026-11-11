# Naukri Profile Manager — AGENTS.md

Cross-platform (Windows/macOS/Linux) PySide6 desktop app for viewing/updating a Naukri profile, fully headless over HTTP (no browser, Selenium or Playwright). Naukri has no public API — the app calls its internal, undocumented services.

## Commands

- Install: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`. Must run inside a venv — `src/main.py` refuses otherwise (frozen exe exempt). Any activated venv counts, not just `VIRTUAL_ENV`.
- Run: `python src/main.py` (or `pip install -e . && naukri-profile-update`).
- Verify (the only check — no pytest/ruff/mypy configured, don't invent them):
  `QT_QPA_PLATFORM=offscreen python -c "from src.ui.main_window import MainWindow"`
- Tests (plain scripts, no pytest):
  `QT_QPA_PLATFORM=offscreen python src/tests/test_captcha_auto_login.py`
  `QT_QPA_PLATFORM=offscreen python src/tests/test_native_lib.py`
- Build: `python build.py` (onedir), `--onefile`, `--versioned` (implies `--onefile`). `--version X` rewrites `_FALLBACK_VERSION` in `src/core/version.py` — check `git status` afterwards (build mutates the source file). `--versioned --version X` renames the onefile artifact to `NaukriProfileManager-<X>-<os>-<arch>`.
- Every build runs `tools/verify_bundle.py` on the artifact and refuses to finish if it fails. The verifier checks httpcloak's native library is present *and* its whole dependency closure travels with it (Windows: `libgcc_s_seh-1.dll` + OpenSSL DLLs).
- `httpcloak==1.7.3` is pinned in `requirements.txt` — the native file name and companion DLLs are a packaging contract. Bump deliberately, then rebuild and re-verify.
- PyInstaller does not cross-compile; build per OS. `build.py` uses `--collect-all PySide6 --collect-all shiboken6 --collect-all playwright`, parks the Qt Designer plugin out of the bundle, and bundles `login_via_browser.py` via `--add-data`. `_version_info()` sanitizes Windows VERSIONINFO to strictly numeric 4-part values (PyInstaller evals it as Python).

## Wiring you can't infer from filenames

- `src/main.py` is a `while True` loop — closing the window ends it; logout returns to `LoginDialog` via `MainWindow.relogin_requested` instead of exiting; the loop-local `prefill_email` carries the dead account into the next login. Keep the loop; don't simplify it away.
- `src/main.py` inserts repo `ROOT` into `sys.path` so `src.*` imports work from the repo root and from the PyInstaller `_MEIPASS` bundle — keep it.
- Layout: `src/core` (NaukriManager, ApiWorker, session/settings/credentials/update_check/version/AI/resume/native_lib/diagnostics + vendored NopeRi in `src/core/nope_ri`), `src/models`, `src/ui` (one module per tab). Vendored NopeRi uses **relative** imports (upstream absolute — re-apply on sync); mostly unused upstream cruft, leave alone.
- App version: `src/core/version.py` reads `[project] version` from pyproject, falls back to `_FALLBACK_VERSION` when frozen; keep them in sync (`build.py --version` rewrites the fallback).

## Runtime gotchas

- All blocking Naukri HTTP runs through `ApiWorker` (`src/core/worker.py`). Every live worker registers in module-level `_ACTIVE` and releases on `finished`; reassign the worker attribute between runs. `ApiWorker.shutdown()` is mandatory before Qt teardown (falls back to `terminate()`).
- httpcloak stores cookies as a plain `list` of `Cookie` objects, not a `RequestsCookieJar` — use `src/core/nope_ri/utils/cookies.py` only (`get_cookie`, `cookies_to_dict`, `set_cookies`). `set_cookies` must call httpcloak's native `session.set_cookie(...)`; `.cookies` is copy-on-read, so appending is a no-op.
- Every public `NaukriManager` method wraps its body in `self._guard_auth(...)`; the hook must be a `Signal.emit`, not a plain callable (it runs on the worker thread). `NaukriAuthError` (401/403) triggers auto re-login; everything else goes straight to the error dialog. `_notified_error` dedupes nested guards; `_recovering` blocks rejected-password loops.
- **A 2xx is not proof a save worked** — check `result.status_code` and the error envelope (`EditTab._on_saved`).

## Naukri HTTP contract (hard-won — don't regress)

- Read profile: `GET .../v2/users/self?expand_level=3` (`FULL_PROFILE_URL`) — rich payload under `profile[0]`. `fullprofiles` is **write-only** (GET 405/500) and is what updates POST to with `x-http-method-override: PUT`. The `PROFILE_FETCH_URL` constant in `nope_ri/config/constants.py` is dead, pointing at that write-only endpoint.
- Position is NOT `role` — parsed from root `employments[]` (current entry, or latest by `startDate`) via `designation`.
- Resume download: `GET .../v1/users/self/profiles/{pid}/resume` with `content-type: application/pdf` and **`Accept` left at `application/json`** (`Accept: application/pdf` → **406**). Require a `%PDF-` marker in the first 1 KiB or raise; a dead-but-not-yet-401 session answers with the HTML login page. 401/403 stay `NaukriAuthError`.
- formKey: scraped live via `get_form_key2()` from the `mnj_v<NNN>.min.js` bundle (`attachCV` pattern) — never hardcode; don't re-add the app-shell `formKey="..."` pattern or a hardcoded bundle URL/version.
- `_fetch_js()` must use plain `requests` (httpcloak serves cached static assets as 304 with an **empty body**). Auth scheme: cloudgateway = Bearer; `/mnjapi/*` = cookie-only (Bearer → `401 4012 "Invalid scheme name"`).
- Resume re-upload: `POST https://filevalidation.naukri.com/file` (multipart `formKey`/`file`/`fileName`/`uploadCallback`/`fileKey`; `appid: 105` + `systemid: fileupload` headers) then `POST .../resman-aggregator-services/v0/users/self/profiles/{pid}/advResume` with `x-http-method-override: PUT` and `{"textCV": {"formKey": ..., "fileKey": ...}}` → `200 {"status": true}`. URL template MUST be `.format(profile_id=pid)`; `_validate_file_request` MUST use the httpcloak session; 404 "OCS Service" = wrong fileKey/formKey pair; tokens 1h TTL, check `exp` first.
- Resume text: `src/core/resume_text.py` via pypdf; PDF only, else `ResumeTextError`.

## UI conventions

- Status/error QLabels must not force window width: use `make_wrapping_status_label()` (box) / `make_wrapping_form_label()` (QFormLayout) from `src/ui/_label_utils.py`; never a raw wordWrap `QLabel`.
- Tabs: Profile · Edit · Refresh · Settings · About always visible; Developer added *after* About only when `settings.show_developer`. Resume download lazy via `ensure_resume_loaded()` on first tab show, not from `set_profile`.
- Dead-session recovery: on `NaukriAuthError` only → `_try_auto_relogin()`; 500/other → error dialog, no re-login. After relogin success, re-run `refresh_profile()` only when the initial load died; for save/refresh show "Session Renewed / try again".
- AI optimizer: resume download lazy; snapshot settings via `dataclasses.replace`; `FIELD_LIMITS` Headline (0,250), Summary (50,1000); `rewrite()` asks for 90–100% of budget then auto-clips; AI never falls back to Ollama (uses `settings.ai_provider` verbatim); OpenAI-compatible `{base}/chat/completions` vs native Anthropic `{base}/messages`; `_models_cache` class-level keyed by `(provider, base_url, api_key)`.

## Storage / credentials

- Session/cookie/settings/credentials live in `~/.naukri-profile-update/` (`session.json`, `config.json`, `credentials.json`). Passwords are cleartext by choice (written only when the login dialog's "Remember password" box is ticked, purged when unticked; `chmod 600` best-effort).
- `NaukriManager.logout()` must NOT delete saved credentials. `save_credential` owns the password; `ensure_credential` adds/refreshes an email-only account and never touches an existing stored password.
- `NaukriManager` wraps `NaukriLoginClient`; each network call splits into a decorated `_foo_request(...)` (raw I/O, wrapped in `with_exponential_retry` — 5 attempts, exponential backoff + jitter, retries 429/5xx) and an undecorated `foo(...)` holding parsing/raising.

## Update notifications

- Plain `requests` only (never the httpcloak session, never behind `_guard_auth`), no `with_exponential_retry`, short timeout (5s auto / 15s manual), failures silent (`logger.debug` + "unavailable" status), one nag per version, strict `X.Y.Z` compare (`parse_version` → 3-tuple, no `packaging` dep). Keep the About status line short — it sits in a `QFormLayout` with horizontal `Preferred`; release URL/notes go in the dialog only.

## Login helper (captcha workaround)

- Password login is captcha-gated; a 403 body carrying `captchaSiteKey` raises `NaukriCaptchaError` (a `NaukriAuthError` subclass). `LoginDialog` catches that type:
  - **Source checkout**: auto-runs `python login_via_browser.py --channel chrome --verify -e <email>` via `QProcess`, then adopts the verified session it saves. Playwright is a runtime dependency (`requirements.txt`); `python -m playwright install chromium` is only needed for `--channel chromium` (system Chrome is used for `--channel chrome`). `requirements-dev.txt` adds `cryptography`/`secretstorage` for `inject_session.py --from-browser` on Linux. `python inject_session.py --from-browser chrome -e <email> --verify` is the manual alternative.
  - **Frozen/standalone build**: `login_via_browser.py` is bundled into the `.exe` by `build.py` (`--collect-all playwright` + `--add-data`). When captcha blocks password login, the dialog runs `login_via_browser.main()` in a background `QThread` (PyInstaller one-file bundles don't expose a standalone Python interpreter for QProcess). Playwright opens a Chromium browser; the user logs in (captcha included), the helper verifies and saves the session to `session.json`, and the dialog accepts automatically. On failure/cancel, the dialog falls back to a "Paste your session token" field. Accepts bare token, `nauk_at=...`, raw Cookie header, or `Bearer ...` formats. The token is saved to `session.json` and the app auto-logs in from then on.
- Both helpers call `ensure_credential()` so the account is remembered without touching any stored password.

## Packaging

- PyInstaller: no cross-compile; build Windows on Windows, Linux on Linux, macOS on macOS. Install `PySide6-Essentials` not `PySide6`; needs `--paths ROOT --windowed`; spec is generated and gitignored — edit `build.py`; keep `--collect-all PySide6 --collect-all shiboken6 --collect-all playwright`; keep Designer plugin parking in `build.py`.
- `build.py` bundles `login_via_browser.py` via `--add-data` so frozen builds can auto-capture the session cookie.
- `_version_info()` sanitizer: Windows VERSIONINFO needs strictly numeric 4-part vers/prodvers; PyInstaller evals the file as Python — keep the sanitizer.
- **httpcloak's native library is not collected by PyInstaller.** `build.py::_httpcloak_lib()` locates `libhttpcloak-<os>-<arch>.<ext>` (glob-tolerant) and bundles the whole `httpcloak/lib/` directory into `httpcloak/lib` — the exact path httpcloak's `_get_lib_path()` searches. It **raises `SystemExit` when the library is missing**: a bundle without it builds green and dies on the user's machine with "Could not find httpcloak library". Never downgrade that to a warning.
- **Companion DLLs are transitive.** The MinGW-built Windows library needs `libwinpthread-1.dll` (via `libgcc_s_seh-1.dll`), which the httpcloak wheel does **not** ship. `build.py::_ensure_companion_dlls()` copies it in from PATH/MinGW; `tools/verify_bundle.py` checks dependencies **recursively** so a missing companion fails CI instead of shipping a broken bundle. `src/core/native_lib.py` also searches PATH/MinGW at runtime as a fallback for source checkouts.
- **`httpcloak` is pinned in `requirements.txt`** (`httpcloak==1.7.3`) because the native file name and its companion DLLs are part of the packaging contract. Bump deliberately, then rebuild and re-verify.
- **Every build is verified.** `build.py` calls `tools/verify_bundle.py` on the artifact and refuses to finish when it fails. The verifier checks (a) the native lib is in the bundle and (b) its whole dependency closure is too — on Windows the httpcloak DLL is MinGW-built and needs `libgcc_s_seh-1.dll` plus OpenSSL DLLs. A missing dependency surfaces as `[WinError 126] The specified module could not be found`, which never names the DLL at fault.
- **Windows onedir is published alongside the onefile `.exe`.** The `.exe` extracts itself into `%TEMP%` on every launch, where antivirus quarantines files; the one-folder zip is the escape hatch. Don't drop it.

## Diagnostics (the windowed build has no console)

- `src/core/diagnostics.py` writes `~/.naukri-profile-update/app.log` (rotating) and `~/.naukri-profile-update/error.log` (crash tracebacks). `src/main.py` installs the hooks **before importing PySide6** — a mismatched DLL raises *during import*, and that is exactly the failure the log exists for.
- `sys.excepthook` **and** `threading.excepthook` are both hooked: the app does all network I/O on an `ApiWorker` thread, so a crash there would otherwise vanish.
- `src/core/native_lib.py` resolves httpcloak's native library, registers its directory with `os.add_dll_directory()` on Windows, and exports `HTTPCLOAK_LIB_PATH` (which httpcloak honours ahead of its own `__file__` guessing). `NaukriManager.__init__` calls `ensure_native_lib()` **before** constructing the vendored client — httpcloak loads the library eagerly in `Session.__init__`, so this is the last chance to turn a bare `OSError` into an actionable `NativeLibError`.
- Never remove the diagnostics to "clean up" — without them every Windows failure report is an unusable "some DLL is not found".

## CI / release

- `.github/workflows/build.yml` runs on every push to `master` and via `workflow_dispatch` (optional `release` input to publish). 4-job matrix: windows-latest, ubuntu-latest, macos-15-intel, macos-15 (arm64), Python 3.12.
- Each job: installs `requirements.txt` + pyinstaller, runs `python -m playwright install chromium`, verifies httpcloak's native library loads (`src/core.native_lib.ensure_native_lib`), runs the two smoke tests (`test_native_lib.py`, `test_captcha_auto_login.py` offscreen), computes the next minor version (`X.Y.0` → `X.(Y+1).0`), runs `python build.py --onefile --versioned --version <NEXT>`, verifies the artifact with `tools/verify_bundle.py`, then on Windows also builds a one-dir zip via `shutil.make_archive`. Uploads artifacts via `actions/upload-artifact@v4.6.2`.
- A `release` job runs on push (not on `workflow_dispatch` unless `release` input is set), needs `contents: write`, duplicates tag guard (`git ls-remote --tags`), bumps `pyproject.toml` + `src/core/version.py` + README version strings, commits `chore(release): v<NEXT> [skip ci]`, tags `v<NEXT>`, pushes, then creates a GitHub Release via `gh release create`. The `[skip ci]` commit prevents re-triggering.
- The Linux raw binary is also zipped (Python `shutil.make_archive`, not the `zip` CLI) since browsers stall on extensionless 90MB files.

## Related

- `SESSION-LEARNINGS.md` — captcha auto-login environment gotchas (recreate a broken `.venv`, QProcess cross-test test ordering). Most of it is already reflected above.
