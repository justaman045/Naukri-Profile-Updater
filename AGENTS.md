# Naukri Profile Manager — AGENTS.md

Cross-platform (Windows/macOS/Linux) PySide6 desktop app for viewing/updating a
Naukri profile, fully headless over HTTP (no browser, Selenium or Playwright).

## Commands

- Install deps: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Run the app: `python src/main.py` (or `pip install -e . && naukri-profile-update`). The venv guard
  in `src/main.py` aborts when not in a virtualenv, so run everything inside `.venv`.
- Headless UI import smoke test (the closest thing to a test suite):
  `QT_QPA_PLATFORM=offscreen python -c "from src.ui.main_window import MainWindow"`
- Build executable: `python build.py` (onedir), `--onefile` for a single file, `--versioned`
  (implies `--onefile`) to rename to `NaukriProfileManager-<ver>-<os>-<arch>`. `build.py`
  auto-installs PyInstaller into the active interpreter if missing. Windows helper:
  `build_windows.bat`.
- **No lint / test / typecheck tooling is configured** — don't invent `pytest`/`ruff`/`mypy`
  commands. Verification is the offscreen import above plus reading the code.
- `pyproject.toml` discovers packages with `[tool.setuptools.packages.find] include = ["src", "src.*"]`
  rather than listing them. A hand-maintained list had silently omitted all six `src.core.nope_ri*` packages, so
  a non-editable `pip install .` / wheel build shipped a package that died on `import src.core.nope_ri`. Keep it
  discovered — don't reintroduce a literal list.

## Wiring you can't infer from filenames

- `src/main.py` inserts `ROOT` into `sys.path` so `src` imports work from the repo root *and*
  from a PyInstaller bundle. Keep it.
- `src/main.py` also refuses to run outside a virtualenv. The guard exempts `sys.frozen` builds
  so the packaged app still runs — do not remove the frozen exemption or the exe breaks.
- `main()` is a `while True` loop so **logout returns to the LoginDialog instead of exiting**
  (closing the window ends the loop; `MainWindow.relogin_requested` drives the re-login).
  Don't "simplify" the loop away. A loop-local `prefill_email` carries the account whose session
  just died into the next iteration's `LoginDialog`.
- Naukri HTTP lives in `src/core/nope_ri/` — a **vendored** copy of
  [NopeRi](https://github.com/Traverser25/NopeRi) whose absolute `from src...` imports were
  rewritten to **relative** (`from .session import ...`). Re-apply those edits when syncing
  upstream or the package breaks. Much of it is unused upstream cruft (job search, apply,
  `PUBLIC_KEY`); leave it alone unless a task needs it.
- `NaukriManager` (`src/core/naukri_client.py`) is the app's own wrapper over
  `NaukriLoginClient`: `fetch_profile()`, `download_resume()`, `refresh_resume()`,
  `update_profile()`, session inject/persist.
- **Convention in the vendored client**: every network call is split into a decorated
  `_foo_request(...)` (raw I/O, wrapped in `with_exponential_retry` from
  `nope_ri/utils/request_helper.py` — 5 attempts, exponential backoff + jitter, retries 429/5xx)
  and an undecorated `foo(...)` holding the parsing/raising. Follow the split when adding
  calls so retry doesn't wrap non-idempotent logic.
- **httpcloak stores cookies as a plain `list` of `Cookie` objects, not a
  `RequestsCookieJar`.** The vendored code assumed `session.cookies.get(name)` / `.update()` /
  `.get_dict()` — all silently broken. Access cookies *only* through
  `src/core/nope_ri/utils/cookies.py` (`get_cookie`, `cookies_to_dict`, `set_cookies`).
  `set_cookies()` must call httpcloak's native `session.set_cookie(...)`: `.cookies` is a
  copy-on-read property, so appending to it is a no-op that yields a session with ZERO cookies
  (`/mnjuser/profile` redirects to login). **Do not regress this.**
- All blocking network calls MUST run through `ApiWorker` (a `QThread` in
  `src/core/worker.py`) — Naukri HTTP on the UI thread freezes the app.
  **Every live `ApiWorker` registers itself in the module-level `_ACTIVE` set and
  releases on `finished`; that registry, not a parent pointer, is what keeps a
  running `QThread` from being garbage-collected.** Callers reassign their worker
  attribute (clicking Refresh twice is enough), so dropping the last reference
  mid-run used to make CPython destroy a live `QThread` and Qt `abort()` —
  an uncatchable SIGABRT, `exit 134`, no traceback. Do not "tidy" the registry
  away, and do not rely on `parent=` to solve it: parenting to a widget just
  moves the same abort to widget-destruction time.
  The release is safe from inside the `finished` slot because a `QThread` object
  lives in the thread that *created* it, so auto-connection queues the slot onto
  the UI thread's event loop, which can only run after `finish()` has returned.
- **`ApiWorker.shutdown(timeout_ms)` is mandatory before Qt teardown.** Called from
  `main()` right after `app.exec()` returns (and from `MainWindow.closeEvent` with a
  2s budget). The retry helper sleeps up to 60s between attempts, so a bounded wait
  alone cannot guarantee a clean exit; `shutdown()` falls back to `terminate()` as a
  documented last resort. Because the registry is global, a worker added by a future
  tab no longer has to be remembered in `closeEvent`.
- Session persistence: `src/core/session_store.py` → `~/.naukri-profile-update/session.json`
  (Bearer `nauk_at` + cookie dict). App settings (`show_developer`, AI provider/key/model) →
  `~/.naukri-profile-update/config.json` via `src/core/settings.py`.
- **Saved credentials** live in `src/core/credentials.py` →
  `~/.naukri-profile-update/credentials.json`: `list_credentials` / `get_credential` /
  `save_credential` (upserts by email) / `delete_credential` / `credential_for_relogin` /
  `touch_credential` (MRU bump, never touches the password).
  **Passwords are stored in cleartext by choice** — `session.json` already holds a live Bearer
  token in cleartext in the same directory, so a plaintext store is the same posture (file is
  `chmod 600` best-effort). Keep it that way rather than adding a crypto/keyring dep: a new
  dependency means touching `requirements.txt` + `pyproject.toml` + the PyInstaller flags in
  `build.py`, and the OS keyring backends need hidden-imports. A password is written **only**
  when the user ticks the login dialog's "Remember password" box; un-ticking it on a later
  login **purges** the stored one. Corrupt/missing JSON yields `[]` instead of raising, so the
  login path never breaks on a bad file.
- **`NaukriManager.logout()` must NOT delete saved credentials** — it only clears
  `session.json`. Surviving a logout is the entire point of the feature; don't "tidy" it.
- **401/403 must surface as `NaukriAuthError`, everything else as `NaukriParseError`.** Use
  `_check_response(resp, what)` in `src/core/naukri_client.py` for any new response check —
  the typed auth error is what lets the UI tell a dead session apart from a 500 and trigger the
  automatic re-login. The vendored `fetch_profile_id()` needed the same guard: it called
  `res.json()` with no `ok` check, so an expired session surfaced as a raw `JSONDecodeError`
  and hid the 401. `update_profile()` had it too. Note `_should_retry` only retries 429/5xx,
  so a 401 fails fast.
- **Every public `NaukriManager` method wraps its body in `self._guard_auth(...)`.** That is
  what makes the automatic re-login fire for a *save* or resume refresh, not just the initial
  profile load. The hook is registered by `MainWindow` as `self._auth_failure.emit` — it must
  be a `Signal.emit` and not a plain callable, because the hook runs on the worker thread and
  touching `_relogin_worker` or a dialog from there is undefined. Two invariants:
  `_notified_error` makes nested guards (`refresh_resume` → `fetch_profile`) notify once for
  the same exception object, and `_recovering` stops a rejected stored password from
  re-entering the recovery path and looping.
- **A 2xx is not proof a profile save worked.** `EditTab._on_saved` must inspect
  `result.status_code` and the body's error envelope; it used to print "Saved successfully."
  unconditionally, hiding real rejections (an over-length summary answers 400).
- App identity/version lives in `src/core/version.py` (`APP_NAME`, `DEVELOPER`, `LICENSE`,
  `CREDITS`, `app_version()`). `app_version()` reads `[project] version` from `pyproject.toml`
  in a source checkout and falls back to `_FALLBACK_VERSION` when frozen (pyproject.toml isn't
  bundled). Keep the two in sync; the release CI job bumps both.
- Profile parsing: `Profile.from_raw` (`src/models/profile.py`) tolerates the rich
  `{user, profile: [...]}` shape, a bare dict, `{dashBoard: ...}`, and a single-element list
  (the `fullprofiles` response).

## Naukri HTTP contract (hard-won — don't regress)

- **Read the profile with `GET .../v2/users/self?expand_level=3`** (`FULL_PROFILE_URL`), which
  returns headline (`resumeHeadline`), summary, skills (`keySkills`), resume metadata
  (`cvInfo`: `fileName`/`cvFormat`/`uploadDate`), name, city, `experience{month,year}`, CTC,
  notice period, etc. under `profile[0]`. Do **not** revert to dashboard-only.
  `fullprofiles` is **write-only** (GET 405/500) and is what `update_profile()` POSTs to with
  `x-http-method-override: PUT`. The raw dashboard only carries basic identity (it's used just
  to resolve `profileId`).
  Note `PROFILE_FETCH_URL` in `nope_ri/config/constants.py` is a **dead constant** pointing at
  the write-only `fullprofiles` — it is not the read endpoint.
- **Position is NOT `role`.** It's parsed from the root-level `employments[]` — the entry with
  `employmentType == "current"` (or null `endDate`), else the latest by `startDate`, reading
  `designation`. Profile-level `role.value` is a stale generic default ("Software Developer")
  and is only used for legacy payloads with no `employments` key.
- **Resume download**: `GET /v1/users/self/profiles/{profile_id}/resume` with
  `content-type: application/pdf` and **`Accept` left at `application/json`** — setting
  `Accept: application/pdf` returns **406**.
  **A 200 here is not proof of a PDF**: a dead-but-not-yet-401 session answers with the HTML
  login page, and `refresh_resume()` would rename that to `..._Updated.pdf` and re-upload it
  *over the user's real resume*. `download_resume()` therefore requires a `%PDF-` marker in
  the first 1 KiB and raises `NaukriParseError` otherwise — it must keep refusing rather than
  letting a 2xx through, and 401/403 must stay `NaukriAuthError` so recovery can fire.
- **formKey is the `attachCV` key from the `mnj_v<NNN>.min.js` bundle, scraped live — never
  hardcode it.** There are TWO uploader keys on a page and they differ: the app-shell chat
  uploader declares `this.formKey="<key>"` in `app_v<NNN>.min.js`, while the **profile resume
  uploader** declares `c="attachCV",d="<key>"` in `mnj_v<NNN>.min.js`. The wrong one makes
  filevalidation return a honeypot key and the `advResume` attach answer
  `404 "Received 404 from OCS Service"`. `get_form_key2()` reads the profile HTML, finds the
  `app_v` bundle, reads the version map `_c={app:"_v470",mnj:"_v323",...}` (regex
  `MNJ_VERSION_PATTERN`, `constants.py`) and fetches `mnj_v<NNN>.min.js`, then applies
  `RESUME_FORM_KEY_PATTERNS` via `extract_resume_form_key`. On `formKey2 not found`, inspect
  the current `mnj_v*` bundle and update that pattern — do not re-add a hardcoded bundle URL
  or version.
  **Do not re-add a pattern for the app-shell `formKey="..."` shape.** The only way to reach
  the honeypot key was `get_form_key()` (deleted, with `APP_JS_PATTERN`/`FORM_KEY_PATTERNS`),
  and `extract_form_key2()` — which the live generic bundle scan still calls — used to fall
  back to `FORM_KEY_PATTERNS`, so a bad scrape returned a plausible-looking wrong key instead
  of failing. It now tries only the `attachCV` pattern plus the legacy `d="..."` signatures.
  The formKey path logs at debug on every swallowed exception, so "formKey2 not found" is
  diagnosable instead of silent.
- **`_fetch_js()` must use plain `requests`, not the httpcloak session.** The shared session
  serves cached static CDN assets as `304 Not Modified` with an **empty body**, so the scraped
  JS silently comes back blank. The bundles are public CDN files with no bot gate.
- **Auth scheme differs by API family**: cloudgateway endpoints use `Authorization: Bearer
  <nauk_at>`; `/mnjapi/*` is **cookie-only** — sending a Bearer header there triggers
  `401 4012 "Invalid scheme name"`. `GET /mnjapi/v4/dashBoard` returning 200 is the definitive
  check that a restored session actually works.
- **Resume re-upload flow** (verified end-to-end; `refresh_resume()` changes
  `cvInfo.uploadDate`): `POST https://filevalidation.naukri.com/file` (multipart fields
  `formKey`, `file`, `fileName`, `uploadCallback:"true"`, `fileKey`; `appid: 105` +
  `systemid: fileupload` are **headers**, not form fields), then
  `POST .../resman-aggregator-services/v0/users/self/profiles/{pid}/advResume` with
  `x-http-method-override: PUT` and body `{"textCV": {"formKey": ..., "fileKey": ...}}` →
  `200 {"status": true}`.
  Gotchas: the URL template MUST be `.format(profile_id=pid)` (a missing `.format` sends the
  literal `{profile_id}` → `400 invalid profileid/...`); `_validate_file_request` MUST use the
  httpcloak session (browser-like TLS), not plain `requests`; a 404 "OCS Service" means the
  fileKey/formKey pair was wrong, not a network problem; tokens are 1h-TTL, and after expiry
  the attach fails with an empty `401` (check `exp` first).
  Historical dead ends — do NOT re-walk: `POST /file/external` returns an OCS-style `U<32 hex>`
  key that still 404s on attach; `/mnjapi/v1|v2/advResume` return `500`;
  `//files.naukri.com/0/saveFile.php` / `saveUrlFile.php` are dead (503/504).
- **Renaming**: `refresh_resume()` builds `Name_Position_Month_Day_Updated.pdf` via
  `_refresh_filename()` (`naukri_client.py`), where `Position` comes from `profile.position`
  and both segments pass through `_file_safe()` (drops everything but letters/digits/space/
  hyphen, then spaces → `_`, so parentheses and commas vanish). The stream's `.name` is what
  the vendored `validate_file()` sends as the upload filename.
- **Resume text extraction** for the AI optimizer: `src/core/resume_text.py`
  (`extract_resume_text(manager)`) downloads the on-file resume and extracts the full text with
  **pypdf** (`PdfReader` + per-page `extract_text`, all pages joined, no truncation).
  **PDF only** — non-PDF formats and PDFs with no extractable text (scanned/image, no OCR)
  raise `ResumeTextError`.

## UI conventions

- **Status/error QLabels must never force the window wider.** A `wordWrap` QLabel with the
  default size policy balloons the window (a QLabel has no width to wrap within). Use
  `make_wrapping_status_label()` from `src/ui/_label_utils.py` (horizontal
  `QSizePolicy.Ignored`) for box-layout status labels. **But `Ignored` breaks a `QFormLayout`
  row height** — Qt under-sizes the row and vertically clips the text (first line cut, last
  hidden), so `QFormLayout` value labels use `make_wrapping_form_label()` (horizontal
  `Preferred`). Both return a `WrappingValueLabel`, a `QLabel` subclass that overrides
  `heightForWidth()` to compute the true wrapped height from `fontMetrics`, because plain
  `QLabel.heightForWidth` is unreliable in `QFormLayout`/`QScrollArea`. The Profile form also
  sits in a `QScrollArea` so a long Summary/Skills can't overflow the window bottom.
- Tabs: **Profile · Edit · Refresh · Settings · About** are always visible; **Developer** is
  added *after* About only when `settings.show_developer` is on (toggled in Settings), and
  removed when toggled off (`MainWindow._sync_developer_visibility`).
- **Dead-session recovery hangs off `MainWindow._on_auth_failure`**, which the manager's auth
  hook drives for *every* operation, not just the initial load. On a `NaukriAuthError` (and
  only that) `_try_auto_relogin()` silently re-authenticates via
  `NaukriManager.relogin_with_saved_password()` on an `ApiWorker` — the same manager object
  stays valid because `login()` re-persists the session. A **500 or any non-auth error must
  never trigger a re-login**; it goes straight to the error dialog.
  `_relogin_attempted` is a one-shot guard so a rejected password (or a server-side auth
  change) can't loop. On failure `_fallback_to_login()` calls `manager.logout()`, sets
  `relogin_requested`, and closes — `main()`'s loop reopens `LoginDialog`, pre-filled with
  `prefill_email` (a loop-local in `main()` that carries the account whose session just died).
  `_on_relogin_done` re-runs `refresh_profile()` **only** when the dead session was the
  initial profile load; for a save or a resume refresh it shows "Session Renewed / try again"
  instead, because a profile refresh would overwrite whatever the user has typed into the
  Edit tab. The originating tab still shows its own error — recovery is a bonus, not a
  substitute for an honest message.
- `LoginDialog(prefill_email=...)` lists saved accounts in a combo box (blank first entry) and
  fills email + password + the remember checkbox on selection; `_persist_credential()` runs on
  success. Settings' "Saved accounts" group holds the delete path (`UserRole` item data carries
  the raw email, so lookups don't depend on the display text).
- `DeveloperTab` holds experimental tools. Its first tool is the **AI field optimizer**:
  loads the on-file resume text into an editable box on a background `ApiWorker`, calls
  `AiClient.rewrite(field, current, resume_text=...)`, shows a live `N / max` counter (red when
  over) and **blocks Apply** past the max, then pushes the text into the Edit tab for review —
  it never saves directly.
  **The resume download is lazy** — `ensure_resume_loaded()` runs from `_on_tab_changed` on
  first show, not from `set_profile()`. `set_profile` used to pull (and PDF-parse) the resume
  on every profile load even though this tab is hidden by default, wasting bandwidth and extra
  Naukri requests. Keep the resume fetch off the profile-load path.
  The tab snapshots settings with `dataclasses.replace(self.settings)` before building an
  `AiClient`: the rewrite runs on a worker thread while the Settings tab mutates the shared
  `AppSettings` from the UI thread.
- `AiClient.rewrite()` wraps the resume text in `===== BEGIN/END RESUME =====` markers *inside
  the prompt* (empty text falls back to the limits-only prompt) — the old bug was requiring
  resume text but never sending it.
- **Naukri per-field char limits** live in `FIELD_LIMITS` (`{field: (min, max)}`, helper
  `field_max()`) in `src/core/ai_client.py`: **Headline (0, 250)**, **Summary (50, 1000)**.
  `rewrite()` puts the exact min/max in the prompt, asks for 90–100% of the budget, then
  **auto-clips** to the max. Update `FIELD_LIMITS` in one place to change prompt + clip + UI
  counter.
- **The AI client NEVER falls back to Ollama** — it uses `settings.ai_provider` verbatim. The
  only Ollama-specific logic is `_provider_requires_key()` / `ai_configured` treating Ollama as
  the lone key-less provider. Guardrail: `settings.base_url_misconfig(provider, base)` returns an
  actionable message when a non-Ollama provider points at the local Ollama server
  (localhost/127.0.0.1:11434); `rewrite()` and `list_models()` call it up front and raise a
  short `AiError`. Provider→URL defaults live in the single `settings.DEFAULT_BASE_URLS` map
  (imported by the Settings tab — do NOT duplicate a literal there).
- Two chat paths: **OpenAI-compatible** `{base_url}/chat/completions` (openai, gemini,
  openrouter, custom/LiteLLM, ollama) and **native Anthropic** `{base_url}/messages` (claude,
  with `anthropic-version` + `x-api-key`); the rest use `Authorization: Bearer`. Model lists
  come from `GET {base_url}/models` → `data[].id`, into an editable `QComboBox` + completer,
  reloaded on provider change and disabled until a key is entered for key-required providers.
  `_models_cache` is **class-level** and keyed by `(provider, base_url, api_key)`, written
  through `type(self)` — the UI builds a fresh `AiClient` per model load, so an instance
  attribute could never hit. Assigning to `self._models_cache` would shadow it and silently
  disable the cache again.
  Response parsing is deliberately defensive: `_parse_json_body` + `_provider_error_message`
  surface a provider `{"error": {"message": ...}}` envelope even on HTTP 200, and
  `_extract_choice_text` accepts assistant `content` as a string **or** a list of
  `{type, text}` blocks (OpenRouter/Gemini/multimodal). Any unparseable body raises a short
  `AiError` carrying at most a **200-char snippet** — never the full raw body.

## Naukri constraints you must respect

- **No public API.** Internal services (`central-login-services`, `cloudgateway-mynaukri`,
  `filevalidation.naukri.com`) can change/break without notice.
- **Sessions are IP-bound.** An IP change invalidates the login → re-login. Expected behavior,
  surfaced in the UI, not a bug.
- **Datacenter/cloud IPs (Azure, Google Cloud, GitHub Actions) are flagged** and often force MFA
  or block. Home/residential IPs are the reliable path.
- **OTP/MFA is out of MVP scope** for the login dialog; `send_otp`/`verify_otp` exist in the
  vendored client for future use.
- `nope_ri/client/session.py` uses `httpcloak` by default, or `curl_cffi` if you flip
  `USE_CURL_CFFI = True` (httpcloak can throw a permission error on some Windows setups).

## Packaging

- PyInstaller does **not** cross-compile: build each OS on that OS.
- `--paths ROOT` and `--windowed` in `build.py` are required (GUI, headless).
- **`NaukriProfileManager.spec` is generated** and gitignored (`*.spec`) — `build.py` rewrites
  it from CLI flags on every build. Don't hand-edit it; change `build.py`.
- **httpcloak's native `.so`/`.dll`/`.dylib` is NOT auto-collected by PyInstaller.**
  `build.py` locates it and `--add-binary`s it; the destination must be the bare directory
  `httpcloak/lib` (no trailing filename), or PyInstaller nests it in a subdirectory of its own
  name and loading fails. "Could not find httpcloak library" in the packaged app means this
  broke.
- **`build.py --version X` MUTATES the working tree**: `_embed_fallback_version()` rewrites
  `_FALLBACK_VERSION` in `src/core/version.py` to `X` so the About tab inside the exe matches
  the artifact name (the CI matrix builds *before* the release job bumps the repo). It's a
  no-op when equal — but check `git status` after building with an explicit `--version` and
  don't commit the accidental bump.
- **Keep `_version_info()`'s sanitizer.** Windows VERSIONINFO needs a strictly-numeric 4-part
  `filevers`/`prodvers`; PyInstaller `eval`s the file as Python, so a non-numeric segment crashes
  with `NameError` (saw `v0` from `v0.1.0` before lstrip, `master` from a branch push). Only
  bites Windows — Linux/macOS don't deserialize VERSIONINFO.
- **Install `PySide6-Essentials`, NOT `PySide6`** (the metapackage drags in `pyside6-addons`:
  Qt3D, WebEngine, QML, Multimedia). The import name is the same either way and PyInstaller's
  Qt detection is runtime introspection, so the dist name doesn't matter. This alone cut the
  release binaries ~2.5x with no bundling changes. `requirements.txt` and `pyproject.toml` both
  pin `PySide6-Essentials>=6.8`; keep them in sync.
- **Keep `--collect-all PySide6 --collect-all shiboken6`.** Since PySide6 6.9-ish the Qt6
  DLLs/.so live under `PySide6/Qt/lib/` with versioned sonames plus the `shiboken6` loader, and
  the default hooks miss them — a plain `--onefile` produced Windows exes that die at startup
  with `ImportError: DLL load failed while importing QtWidgets`. Don't "optimize" this into a
  targeted `--add-binary` unless verified on all three OSes.
- **Keep the Qt Designer plugin parking in `build.py`.** `--collect-all PySide6` copies
  `Qt/plugins/designer/libqwebengineview.so`, and on a machine with a system Qt its `ldd` walk
  drags in the whole WebEngine + Chromium FFmpeg tree (~200 MB the app never uses). `build.py`
  moves the designer dir into its tempdir before PyInstaller and restores it after; renaming it
  in place is NOT enough because `--collect-all` scans the package recursively.
- Optional root-level `app.ico` / `app.icns` / `app.png` become `--icon`. None are committed
  today, so builds log "No app.ico/app.icns/app.png found".

## CI / release (`.github/workflows/build.yml`)

- 4-job matrix: `windows-latest` (x86_64), `ubuntu-latest` (x86_64), `macos-15-intel` (x86_64),
  `macos-15` (arm64), each Python 3.12 running
  `python build.py --onefile --versioned --version <NEXT>`.
- **Every push to `master` auto-releases.** The build jobs compute the next minor version from
  `pyproject.toml` (`0.1.0` → `0.2.0`; identical on all runners so asset names line up), then
  the `release` job bumps `pyproject.toml` + `version.py._FALLBACK_VERSION`, **rewrites the
  README version strings**, commits as `chore(release): v<NEXT> [skip ci]`, pushes tag
  `v<NEXT>`, and publishes via `gh release create`.
  **Don't hand-bump version strings in `README.md`** — the bot regexes over every
  `v\d+\.\d+\.\d+` and `-\d+\.\d+\.\d+-` occurrence, so manual edits are clobbered.
- The `[skip ci]` in the bot's commit is what stops the workflow re-triggering on its own
  commit, and `on:` watches only `master` pushes (plus `workflow_dispatch`, which releases only
  if its `release` input is set). Neither the bump commit nor the tag push re-triggers it. If a
  build job fails, only that one run goes red — check the specific run, not a sibling.
- The release job has a duplicate-run guard: if tag `v<NEXT>` already exists it skips quietly.
- The release also ships a `NaukriProfileManager-<ver>-linux-x86_64.zip` because browsers stall
  on the ~150 MB extensionless Linux binary (the zip preserves the exec bit).
- **Pin `actions/upload-artifact@v4.6.2`+.** v4 has a transient
  `FinalizeArtifact 403 ... Error from intermediary` bug; it is **not** a build failure
  (PyInstaller already wrote the binary), the job just fails at upload. Don't chase `build.py`.
  Also: **`gh run upload` does not exist** — `actions/upload-artifact` is the only upload path,
  don't replace the action with a `gh` retry loop.
- Expected noise, not failures: macOS-15 deprecating Node 20 (actions forced to Node 24) for
  `checkout@v4`/`setup-python@v5`/`upload-artifact@v4`; and `Library not found: libxcb-*.so`
  **WARNING**s from the Linux onefile build (Qt xcb deps missing on the runner) — non-fatal for
  a headless bundle.
