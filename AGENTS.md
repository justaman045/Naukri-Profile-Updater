# Naukri Profile Manager — AGENTS.md

Cross-platform (Windows/macOS/Linux) PySide6 desktop app for viewing/updating a
Naukri profile, fully headless over HTTP.

## Commands

- Install deps: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Run the app: `python src/main.py` (or `pip install -e . && naukri-profile-update`). The venv guard
  in `src/main.py` aborts when not in a virtualenv, so run everything inside `.venv`.
- Headless UI import smoke test (run in the venv): `QT_QPA_PLATFORM=offscreen python -c "from src.ui.main_window import MainWindow"`
- Build executable: `python build.py` (add `--onefile` for a single file; `--versioned` implies
  `--onefile`). `build.py` auto-installs PyInstaller into the active interpreter if it is missing.
- No lint/test/typecheck tooling is configured — do not invent `pytest`/`ruff` commands.

## Key architecture facts (would cost time to rediscover)

- `src/main.py` must insert `ROOT` into `sys.path` so `src` is importable from the
  repo root and inside a PyInstaller bundle. Keep that.
- `src/main.py` also refuses to run outside a virtualenv (exits with a message to
  stderr). The guard exempts `sys.frozen` builds so the packaged app still runs —
  do not remove the frozen exemption, or the distributed executable breaks.
- `main()` is a `while True` loop so **logout returns to the LoginDialog instead of
  exiting the app** (closing the window ends the loop; `window.relogin_requested`
  drives a re-login). Don't "simplify" the loop away.
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
  **Position is NOT `role`.** It is parsed from the root-level `employments[]`
  list — the entry with `employmentType == "current"` (or `endDate` null), else
  the latest by `startDate`, reading its `designation` field. The profile-level
  `role.value` is a stale generic default ("Software Developer") and is only used
  for legacy payloads that carry no `employments` key.
- Resume **download**: `GET /v1/users/self/profiles/{profile_id}/resume` with
  `content-type: application/pdf` (Accept must stay `application/json` — setting
  `Accept: application/pdf` returns **406**). `NaukriManager.refresh_resume()`
  downloads the on-file PDF, renames it to `Name_Position_Month_Day_Updated.pdf`
  (e.g. `Aman_Ojha_Systems_Engineer_Senior_SDET_September_1_Updated.pdf`) and
  re-uploads it. The `Position` segment comes from `profile.position` (the current
  employment designation) and is sanitized by `_file_safe()` (letters/digits/
  underscore only — parentheses and commas are stripped). The renaming helper
  `_refresh_filename()` lives in `src/core/naukri_client.py`.
- **Resume upload's formKey is the `attachCV` key from the `mnj_v<NNN>` bundle, scraped
  live — never hardcoded.** There are TWO uploader keys on a page and they are different:
  the app-shell chat uploader declares `this.formKey="<key>"` in `app_v<NNN>.min.js`, while
  the **profile resume uploader** declares `c="attachCV",d="<key>"` in `mnj_v<NNN>.min.js`.
  Using the wrong one makes the filevalidation upload return a honeypot echo and the
  `advResume` attach answer `404 "Received 404 from OCS Service"`. `get_form_key2()`
  (`src/core/nope_ri/client/naukri_client.py`) reads the profile HTML, finds the `app_v`
  bundle, reads the version map `_c={app:"_v470",mnj:"_v323",...}` (regex
  `MNJ_VERSION_PATTERN`, `constants.py`) and fetches `mnj_v<NNN>.min.js`, then applies
  `RESUME_FORM_KEY_PATTERNS` via `extract_resume_form_key` (`utils/extractors.py`).
  On `formKey2 not found`, inspect the current `mnj_v*` bundle and update that pattern.
  Do NOT re-add a hardcoded bundle URL or version.
- **`_fetch_js()` must use plain `requests`, not the httpcloak session.** The shared
  httpcloak session caches static CDN assets and serves them as `304 Not Modified` with an
  **empty body**, so the scraped JS silently comes back blank (`formKey2 not found`). The
  bundles are public CDN files with no bot gate, so `requests.get(..., _JS_FETCH_HEADERS)` is correct.

- **`set_cookies()` must use httpcloak's native `session.set_cookie(...)`.** The previous
  implementation appended to `session.cookies`, which is a **copy-on-read property** — a
  silent no-op. Result: restored sessions carried ZERO cookies, so every cookie-gated
  endpoint failed (`GET /mnjuser/profile` -> redirected to the login page, and
  `/mnjapi/*` -> `401 code 4012 "Invalid scheme name"`). With `set_cookie` the same
  session loads the real profile page and `GET /mnjapi/v4/dashBoard` -> 200 (the
  cookies-only mnjapi auth is the definitive check). **Do not regress this.**
  (`cookies_to_dict` reads httpcloak's `List[Cookie]`; `get_cookie` likewise.)
- **`/mnjapi/*` auth is COOKIE-based, not header-based.** Sending `Authorization: Bearer
  <nauk_at>` to mnjapi actually triggers `401 4012 "Invalid scheme name"`; sending NO
  Authorization (cookies only) authenticates. The cloudgateway APIs are the opposite
  (Authorization Bearer, cookies optional). `formKey` is scraped from the `mnj_v<NNN>` bundle
  (see the formKey bullet above).
- **Resume re-upload (RESOLVED 2026-09-21):** the whole flow now works headlessly and is
  verified end-to-end (`refresh_resume()` changes `cvInfo.uploadDate`). The fix was the
  **formKey**: the resume uploader uses the `attachCV` key from `mnj_v<NNN>.min.js`, not the
  app-shell chat key from `app_v<NNN>.min.js` (see the formKey bullet above). With the
  correct key, `POST https://filevalidation.naukri.com/file` stores the file and the
  subsequent `POST .../resman-aggregator-services/v0/users/self/profiles/{pid}/advResume`
  (`x-http-method-override: PUT`, body
  `{"textCV":{"formKey","fileKey","textCvContent":null}}`) returns
  `200 {"description":"Request completed successfully","status":true}`. The uploader sends
  the file as multipart with fields `formKey`, `file`, `fileName`, `uploadCallback:"true"`,
  `fileKey` (appId is a HEADER `appId:105` + `systemId:fileupload`, not a form field).
  Notes: the URL template MUST be `.format(profile_id=pid)` (a missing `.format` sends the
  literal `{profile_id}` -> `400 invalid profileid/...`); `_validate_file_request` MUST use
  the httpcloak session (browser-like TLS), not plain `requests`; a 404 "OCS Service" means
  the fileKey/formKey pair was wrong (honeypot echo), not a network problem. Session tokens
  are 1h-TTL; after expiry the attach fails with an empty `401` (check `exp` first).
  Historical dead ends (do NOT re-walk): `POST /file/external` returns an OCS-style
  `U<32 hex>` key but attaching it still 404s; `/mnjapi/v1|v2/advResume` return `500`;
  `//files.naukri.com/0/saveFile.php` / `saveUrlFile.php` are dead (503/504).

- Resume **text extraction** for the AI optimizer: `src/core/resume_text.py`
  (`extract_resume_text(manager)`) downloads the on-file resume via
  `manager.download_resume()` and extracts its full text with **pypdf** (`PdfReader` +
  `extract_text` per page, all pages joined — no truncation). **PDF only**: non-PDF
  formats and PDFs with no extractable text (scanned/image PDFs, no OCR) raise
  `ResumeTextError`. The Developer tab auto-loads this text into its editable
  `resume_input` on a background `ApiWorker` (human-verifiable, editable).
- `AiClient.rewrite(field_name, current_value, resume_text="")` — passes the resume
  text to the model wrapped in `===== BEGIN/END RESUME =====` markers inside the
  prompt (empty resume falls back to the old prompt). This is the source the AI
  optimizer's rewrite is based on; it is NOT just a gate check (old bug: resume text
  was required but never sent).
- **Naukri per-field char limits** live in `FIELD_LIMITS` (a `{field: (min, max)}` map,
  helper `field_max()`) in `src/core/ai_client.py`. Verified: **Headline (0, 250)**,
  **Summary (50, 1000)** — the 1000 max comes from a live HTTP-400 save record; 250
  headline is corroborated by Naukri guides. `rewrite()` puts the exact min/max into
  the prompt and instructs the model to target **90-100%** of the budget, then
  **auto-clips** the returned text to the max (`text[:max].strip()`). The Developer tab
  shows a **live `N / max` counter** (red when over) and **blocks Apply** if the result
  exceeds the field's max. Update `FIELD_LIMITS` in one place to change prompt + clip.
- **AI chat response parsing** in `ai_client.py` is defensive: `_parse_json_body` +
  `_provider_error_message` detect a provider `{"error": {"message": ...}}` envelope even
  on HTTP 200 and surface it; `_extract_choice_text` accepts assistant `content` as a
  plain string **or** a list of `{type, text}` blocks (OpenRouter/Gemini/multimodal).
  Any malformed/unparseable body raises a short `AiError` ("AI request failed"/"Unexpected
  AI response from provider") with at most a **200-char snippet** — never the full raw body.
- **Status/error QLabels must never force the window wider.** Long unbreakable text in a
  `wordWrap` QLabel with default policy balloons the window (QLabel has no space to wrap).
  Use `src/ui/_label_utils.make_wrapping_status_label()` (horizontal `QSizePolicy.Ignored`
  + `wordWrap`) for box-layout status labels (Developer/Settings/Refresh). **But `Ignored`
  breaks a `QFormLayout` row height**: Qt then under-sizes the row and vertically clips the
  wrapped text (first line cut, last line hidden). The **Profile tab** value labels therefore
  use `make_wrapping_form_label()` (horizontal `QSizePolicy.Preferred`). Both helpers build a
  `WrappingValueLabel` (a `QLabel` subclass that overrides `heightForWidth()` to return the
  true wrapped height from `fontMetrics`), because Qt's `QLabel.heightForWidth` is unreliable
  for wrapped text in `QFormLayout`/`QScrollArea`. The Profile form also sits inside a
  `QScrollArea` so a long Summary/Skills doesn't overflow the window bottom.
- **The AI client NEVER falls back to Ollama.** It uses `settings.ai_provider` verbatim.
  The only Ollama-specific logic is `_provider_requires_key()`/`ai_configured` treating
  Ollama as the lone key-less provider. Guardrail: `settings.base_url_misconfig(provider,
  base)` (in `src/core/settings.py`) returns an actionable message if a non-Ollama
  provider has a base URL pointing at the local Ollama server (localhost/127.0.0.1:
  11434). `AiClient.rewrite()` and `AiClient.list_models()` call it up front and raise a
  short `AiError` instead of sending data to Ollama. Provider→URL defaults live in a
  single `settings.DEFAULT_BASE_URLS` map (the Settings tab imports it; do NOT duplicate
  a `_DEFAULT_BASE_URLS` literal there).
- `Profile.from_raw` in `src/models/profile.py` tolerates the rich `{user, profile: [...]}`
  shape, a bare dict, `{dashBoard: ...}`, and a single-element list `[{...}]` (the
  `fullprofiles` response shape).
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
- The UI has a **Settings** tab (always visible), an **About** tab (always visible, at
  the end) and a **Developer** tab that is **hidden unless** `settings.show_developer`
  is enabled (toggled in the Settings tab). When shown, Developer appends **after**
  About (tab-order independent). `DeveloperTab` holds experimental tools; the first is
  an **AI field optimizer** that rewrites a chosen profile field using `src/core/ai_client.py`.
- **App version/metadata** live in `src/core/version.py` (`APP_NAME`, `DEVELOPER`,
  `LICENSE`, `CREDITS`, `app_version()`). `app_version()` reads `[project] version`
  from `pyproject.toml` when running from source and falls back to a hardcoded
  `_FALLBACK_VERSION` in a frozen build (pyproject.toml is not bundled). Keep the
  fallback and `pyproject.toml` in sync on release. `build.py` imports it to generate a
  Windows `--version-file`, and the About tab uses it for the Version row.
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
- `build.py` supports `--onefile`, `--onedir`, and `--versioned` (renames the artifact to
  `NaukriProfileManager-<ver>-<os>-<arch>[.exe]` using `--version` or `app_version()`; the
  leading `v` is stripped, and `darwin`→`macos`). CI passes the computed next minor
  version (e.g. `--version 0.2.0`).
- `--paths ROOT` and `--windowed` in `build.py` are required (GUI, headless).
- `NaukriProfileManager.spec` at the repo root is a **generated** PyInstaller spec
  full of machine-local absolute paths (httpcloak lib under `.venv/...`, the
  `version_info.txt` temp path). `build.py` regenerates it on every build from its
  CLI flags — do not hand-edit it, change `build.py` instead.
- **httpcloak's native `.so`/`.dll`/`.dylib` is NOT auto-collected by PyInstaller.**
  `build.py` locates and `--add-binary`s it into `httpcloak/lib/` (matching httpcloak's
  runtime search path). If you see "Could not find httpcloak library" in the packaged
  app, that bundling step broke — do not remove it. Also, the `--add-binary` destination
  must be the bare directory `httpcloak/lib` (no trailing filename), or PyInstaller
  nests the file inside a subdirectory of its own name and loading fails.
- **CI release pipeline** (`.github/workflows/build.yml`): a 4-job matrix builds
  `windows-latest` (x86_64), `ubuntu-latest` (x86_64), `macos-15-intel` (x86_64) and
  `macos-15` (arm64). **Every push to `master` auto-releases**: the `build` jobs
  compute the next minor version from `pyproject.toml` (`0.1.0` → `0.2.0`, same
  computation on all runners → identical asset names), then the `release` job bumps
  `pyproject.toml` + `src/core/version.py._FALLBACK_VERSION`, rewrites the README
  Download table/URLs to the new version, commits that as
  `chore(release): v<NEXT> [skip ci]` (the `[skip ci]` is what stops the workflow
  re-triggering on its own commit), pushes tag `v<NEXT>`, and publishes a GitHub
  Release with the four artifacts via `gh release create ... --notes-file`.
  `workflow_dispatch` builds artifacts only unless its `release` input is set.
  macOS-13 x64 is retired — use `macos-15-intel` for Intel and `macos-15` for
  Apple Silicon.
- Unsigned macOS builds show a Gatekeeper prompt (documented in README).

### CI/build pitfalls (learned the hard way)

- **CI passes an explicit numeric version to `build.py` now** (computed from
  `pyproject.toml`, e.g. `--version 0.2.0`) — but keep `_version_info()`'s sanitizer.
  VERSIONINFO requires a **strictly-numeric 4-part** `filevers`/`prodvers`: PyInstaller
  `eval`s the VERSIONINFO file as Python, so any non-numeric segment crashes with
  `NameError: name '<x>' is not defined` (saw `v0` from `v0.1.0` before lstrip, and
  `master` from a branch push). Keep the filter that keeps only `.isdigit()` parts
  padded to 4. Note this only bites Windows — Linux/macOS don't deserialize
  VERSIONINFO.
- **Neither the bot's `[skip ci]` bump commit nor the `v<NEXT>` tag push re-triggers
  the workflow** — `on:` watches only `master` pushes (plus `workflow_dispatch`, which
  releases only if its `release` input is set). If a build job fails, only that one run
  turns red; the release job of a prior run is unaffected. Check the specific run, not
  a sibling.
- **`actions/upload-artifact@v4` has a transient `FinalizeArtifact 403` bug**:
  `##[error]Failed to FinalizeArtifact: ... (403) Forbidden: Error from intermediary`.
  It is NOT a build failure (PyInstaller already wrote the binary); the job fails at the
  upload step. **Pin `actions/upload-artifact@v4.6.2`+** — the fix for it is in that
  release. Don't chase `build.py` when you see it.
- **`gh run upload` does NOT exist** (even gh 2.98). There is no gh CLI command to
  upload artifacts from a workflow step; the only upload path is
  `actions/upload-artifact`. Don't replace the action with a `gh` retry loop.
- macOS-15 images deprecate Node 20 with a warning (`forced to run on Node 24`) for
  `actions/checkout@v4`/`setup-python@v5`/`upload-artifact@v4` — harmless, expect it.
- A PyInstaller Linux onefile build succeeds with "Library not found: libxcb-*.so"
  **WARNING**s (Qt xcb platform deps missing on the runner). These are non-fatal for a
  headless bundle — don't treat warnings as build failure.