# Naukri Profile Manager

A cross-platform desktop app (Windows / macOS / Linux) for viewing and updating your
Naukri profile — completely **headless** (no browser window, no Selenium, no Playwright).
Everything runs over HTTP using Naukri's reverse-engineered internal services.

## Features (MVP)

- **Login** with email + password (no browser, no OTP requiring interaction).
- **View** your full profile: name, headline, summary, skills, position, experience,
  CTC, notice period, city, email, phone, plus resume name/format/upload date.
- **Edit** your headline, name, and summary.
- **Refresh resume** — downloads your current on-file resume, renames it to the
  `Name_Position_Month_Day_Updated.pdf` pattern, and re-uploads it to keep the
  profile active.
- **Settings** — toggle hidden Developer options (experimental/unfinished tools) and
  configure an AI provider (base URL, API key) for the field optimizer. The **Model**
  dropdown auto-fetches the provider's available models so you just pick one.
- **Developer** (hidden by default, enable in Settings) — experimental AI optimizer
  that rewrites a profile field (headline/summary) using your chosen provider. The
  optimizer automatically downloads and **loads your on-file resume's full text** into
  an editable box so the AI drafts the rewrite from your real experience, and it
  **respects Naukri's per-field character limits** (Headline ≤250, Summary 50–1000),
  aiming for ~90-100% of the budget and showing a live character counter.
- **Persistent session** — you stay logged in across launches until your token/IP changes.

## Stack

- Python 3.11+ (tested on 3.14) + **PySide6** (Qt6) for the UI.
- Vendored, trimmed copy of [NopeRi](https://github.com/Traverser25/NopeRi) for Naukri
  HTTP interaction (login, update profile, resume upload) plus custom read-profile
  (`fetch_profile`, using the rich `v2/users/self` endpoint) and resume download
  (`v1/users/self/profiles/{id}/resume`) additions that upstream doesn't provide.
- **pypdf** for extracting resume PDF text (feeds the AI optimizer).
- **PyInstaller** for packaging.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python src/main.py                 # or: pip install -e . && naukri-profile-update
```

On first run, enter your Naukri email + password. Your session is saved to
`~/.naukri-profile-update/session.json`.

## Packaging

```bash
pip install pyinstaller
python build.py                    # onedir (folder) — recommended
python build.py --onefile          # single executable (slower startup)
```

**PyInstaller does not cross-compile.** Build the Windows `.exe` on Windows, the macOS
`.app` on macOS, and the Linux binary on Linux. Unsigned macOS builds trigger a
Gatekeeper "Open anyway" prompt (right-click → Open).

`build.py` embeds the app version (from `pyproject.toml`) into the executable's
File Properties and uses `app.ico`/`app.icns`/`app.png` as the icon when present.

### Windows `.exe`

On a Windows machine, either run:

```bat
build_windows.bat
```

or manually:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
python build.py --onefile
```

The single-file executable is written to `dist\NaukriProfileManager.exe`.

A **GitHub Actions workflow** (`.github/workflows/build.yml`) builds Windows `.exe`,
Linux binary and macOS `.app` **on every push to `master`** (and manually via the
"Build executables" workflow), then uploads each as a downloadable artifact.

## ⚠️ Important Naukri constraints

- **No public API.** This app uses Naukri's internal, undocumented services. They can
  change without notice and break things.
- **Sessions are IP-bound.** Login is tied to the IP it happened on. Changing IP
  (VPN, mobile ↔ home, restart on dynamic ISP) invalidates the session → re-login.
- **Hosting matters.** Datacenter/cloud IPs (Azure, GCP, GitHub Actions) are often
  blocked or force MFA. Home broadband / residential IPs work best.
- **Use on your own account, low frequency.** Naukri's Terms of Service restrict
  automation; frequent bursts may trigger blocks or account action.
- **OTP/MFA** is intentionally skipped in the MVP login dialog. `send_otp`/`verify_otp`
  exist in the vendored client for a future enhancement.

## Project layout

```
src/
├── main.py               # Entry point
├── ui/                   # PySide6 widgets (login, profile, edit, refresh, settings, developer, main window)
├── core/
│   ├── naukri_client.py  # High-level wrapper (fetch_profile, download & refresh resume)
│   ├── session_store.py  # Persist/load/clear the saved session
│   ├── settings.py       # App settings (Developer toggle + AI provider) -> config.json
│   ├── ai_client.py      # Provider-agnostic OpenAI-compatible chat client (AI optimizer)
│   ├── resume_text.py    # Extract on-file resume PDF text for the AI optimizer
│   ├── worker.py         # QThread wrapper for blocking network calls
│   └── nope_ri/          # Vendored NopeRi client (relative-import edits applied)
└── models/profile.py     # Profile dataclass + response parser
```

## License

MIT. Auto-apply / bulk-scraping / third-party tooling behaviour is out of scope; keep
usage personal and within Naukri's terms.

## Disclaimer

Not affiliated with Naukri / InfoEdge India Ltd. Use responsibly.