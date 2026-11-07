# Session Learnings — Naukri Profile Manager Captcha Auto-Login

## Environment gotchas

- **Broken `.venv`**: The project's `.venv` was created from `/usr/bin/python3.14`, which no longer exists. Its symlinks resolved to `/usr/bin/python3` → Python 3.15.0, so the interpreter ignored its own `site-packages` (`lib/python3.14/site-packages`) even though PySide6/pypdf/httpcloak/requests were installed there. Fix: `rm -rf .venv && python3 -m venv .venv && pip install -r requirements.txt`.
- **No test/lint tooling configured**: `pyproject.toml` has no `[tool.pytest]` etc. AGENTS.md explicitly says don't invent pytest/ruff/mypy commands. Verification = offscreen import smoke test (`QT_QPA_PLATFORM=offscreen python -c "from src.ui.main_window import MainWindow"`).

## Naukri captcha gate

- Naukri password login now returns `403` with body containing `"captchaSiteKey":"..."`. Headless HTTP can never satisfy the captcha widget (`niCaptchaWidget` + reCAPTCHA/BotGuard fallback).
- The vendored `login()` previously raised generic `NaukriAuthError("Login failed")` — dead end for the user.
- Fix: added `NaukriCaptchaError(NaukriAuthError)` in `src/core/nope_ri/exceptions/exceptions.py`; raised in `src/core/nope_ri/client/naukri_client.py` when `"captchaSiteKey" in body`.

## Auto-run browser login flow

- `LoginDialog._on_login_failure` catches `NaukriCaptchaError` and auto-spawns `python login_via_browser.py --channel chrome --verify -e <email>` via `QProcess` (non-blocking).
- On helper exit code 0 + valid `session.json` with `bearer_token`: build `NaukriManager(..., use_saved_session=True)`, adopt it, call `accept()`.
- On failure/cancel: show helper output in the wrapping error label; `reject()` kills a running helper process.
- Frozen builds can't run the helper script → show manual-run hint instead.
- `QProcess` caveat: `finished` also fires for crashes/timeouts; only `FailedToStart` happens before the process ever runs. Cleanup via `_stop_browser_login()` in `reject()`.

## UI wrapping label fix

- `error_label` was a raw `QLabel` with `setWordWrap(True)` — the exact anti-pattern AGENTS.md warns about. Long captcha hint wrapped vertically and was clipped at dialog bottom.
- Fix: use `make_wrapping_status_label()` from `src/ui/_label_utils.py` (Ignored horizontal policy + `WrappingValueLabel.heightForWidth()`) and call `self.layout().activate()` + `self.adjustSize()` in `_show_error()` so the dialog resizes to fit the wrapped text.
- `status_label` also converted to the same wrapping label.

## Missing `ensure_credential()`

- Both `login_via_browser.py` and `inject_session.py` imported `ensure_credential` from `src/core.credentials`, but it didn't exist. Added it: adds/refreshes an email-only account and **never touches an existing stored password** (uses `touch_credential` if account exists, otherwise appends email-only entry).

## Offscreen regression test patterns

- Test file: `src/tests/test_captcha_auto_login.py`, runs headless via `QT_QPA_PLATFORM=offscreen`, no pytest dependency.
- Stub `login_via_browser.py` in a temp dir: write fake `session.json` with `username`/`bearer_token`/`cookies`, `sys.exit(0)`.
- Monkeypatch `ld.ROOT` and `session_store.SESSION_FILE` to the temp dir; restore in `finally`.
- **QProcess cross-test contamination**: a `QProcess` spawned in one test leaves Qt in a state where a subsequently created dialog's error label doesn't process. Fix: run `test_captcha_missing_helper_shows_error` before any QProcess-spawning test; or flush `app.processEvents()` between tests.
- `QProcess: Destroyed while process ... is still running` warning appears but is benign (process exits before dialog cleanup).
- `result()` returns `1` for accepted (QDialog.DialogCode.Accepted enum value), `0` for rejected — assert against `QDialog.DialogCode.Accepted`, not raw `1`.

## CI pipeline (`build.yml`)

- 4-job matrix: windows-latest, ubuntu-latest, macos-15-intel, macos-15 (arm64), Python 3.12.
- Runs `python build.py --onefile --versioned --version <NEXT>` where NEXT = minor bump from pyproject.toml (0.3.0 → 0.4.0).
- `actions/upload-artifact@v4.6.2` pins; `gh run upload` does not exist.
- Release job bumps version + `_FALLBACK_VERSION`, rewrites README version strings, commits `chore(release): v<NEXT> [skip ci]`, pushes tag, publishes via `gh release create`.
- No test step in CI — only build + release. My regression test is local verification only.
- `build.py --version X` mutates `src/core/version.py._FALLBACK_VERSION` — check `git status` after building with explicit `--version`.

## AGENTS.md structure

- Sections: Commands, Wiring you can't infer from filenames, Runtime gotchas, Naukri HTTP contract (hard-won), UI conventions, Naukri constraints/storage/credentials, Update notifications, Login helper (captcha workaround), Packaging, CI/release.
- Every line answers "would an agent likely miss this without help?" — no generic advice, no tutorials, no exhaustive file trees.
