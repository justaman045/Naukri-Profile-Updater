# Naukri Profile Manager

A cross-platform desktop app (Windows / macOS / Linux) for viewing and updating your
Naukri profile — completely **headless** (no browser window, no Selenium, no Playwright).
Everything runs over HTTP using Naukri's reverse-engineered internal services.

## Download

Pre-built executables are published as **GitHub Releases**. Every `vX.Y.Z` tag push
triggers an automated build of all platforms — grab the latest from the
[Releases page](https://github.com/justaman045/Naukri-Profile-Updater/releases/latest).

| Platform            | Architecture    | File asset / download                                            |
|---------------------|-----------------|------------------------------------------------------------------|
| Windows             | x86_64          | [NaukriProfileManager-0.1.0-windows-x86_64.exe](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.1.0/NaukriProfileManager-0.1.0-windows-x86_64.exe) |
| Linux               | x86_64          | [NaukriProfileManager-0.1.0-linux-x86_64](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.1.0/NaukriProfileManager-0.1.0-linux-x86_64) |
| macOS (Intel)       | x86_64          | [NaukriProfileManager-0.1.0-macos-x86_64](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.1.0/NaukriProfileManager-0.1.0-macos-x86_64) |
| macOS (Apple Silicon) | arm64         | [NaukriProfileManager-0.1.0-macos-arm64](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.1.0/NaukriProfileManager-0.1.0-macos-arm64) |

> The links above point at the current `v0.1.0` release. After each new tag, the
> [Releases page](https://github.com/justaman045/Naukri-Profile-Updater/releases/latest)
> always carries the newest per-OS executables.
>
> Builds are **unsigned** — Windows SmartScreen and macOS Gatekeeper may warn before
> first run. On macOS, right-click the executable → **Open** if Gatekeeper blocks it.

## Features

- **Login** — email + password, no browser and no OTP interaction needed.
- **View profile** — name, headline, summary, skills, position, experience, CTC,
  notice period, city, email, phone, resume name/format/upload date, and profile ID.
- **Edit** — update your headline, name, and summary.
- **Refresh resume** — downloads your current on-file resume, renames it to the
  `Name_Position_Month_Day_Updated.pdf` pattern, and re-uploads it to keep the profile
  active on Naukri.
- **Settings** — toggle the hidden Developer tools and configure an AI provider
  (base URL, API key, model picker with automatic model discovery).
- **Developer (hidden by default)** — experimental **AI field optimizer** that rewrites a
  profile field using your chosen provider. It auto-loads your on-file resume's full text
  so the AI drafts from your real experience, and it **respects Naukri's per-field limits**
  (Headline ≤ 250, Summary 50–1000) with a live character counter.
- **About** — application version, developer, license, credits, and session location.
- **Persistent session** — you stay logged in across launches until your token/IP changes.

## Stack

- **Python 3.10+** · **PySide6** (Qt6) for the desktop UI.
- Vendored, trimmed copy of [NopeRi](https://github.com/Traverser25/NopeRi) for Naukri
  HTTP interaction (login, profile update, resume upload), plus custom additions:
  `fetch_profile` (rich `v2/users/self` read) and resume download
  (`v1/users/self/profiles/{id}/resume`).
- **httpcloak** for the HTTP/TLS transport (native `curl_cffi` fallback on Windows).
- **pypdf** for extracting resume PDF text (feeds the AI optimizer).
- **PyInstaller** for packaging.

## Setup (from source)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python src/main.py                 # or: pip install -e . && naukri-profile-update
```

On first run, enter your Naukri email + password. Your session is saved to
`~/.naukri-profile-update/session.json`.

## Building executables

```bash
pip install pyinstaller
python build.py                          # onedir (folder) — recommended locally
python build.py --onefile                # single executable (slower startup)
python build.py --onefile --versioned --version v0.1.0
                                         # -> NaukriProfileManager-0.1.0-<os>-<arch>
```

**PyInstaller does not cross-compile.** Build Linux on Linux, Windows on Windows, and macOS
on macOS. `build.py` embeds the app version into the executable's file properties and uses
`app.ico`/`app.icns`/`app.png` as the icon when present.

### Windows (on a Windows machine)

Run `build_windows.bat` (creates a venv, installs deps, and produces
`dist\NaukriProfileManager.exe`), or manually:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
python build.py --onefile
```

### Automatic CI builds

`.github/workflows/build.yml` builds Windows, Linux, and both macOS architectures:

- **Every push to `master`** → builds all four and uploads them as (short-lived) artifacts.
- **Every `vX.Y.Z` tag push** → builds all four and publishes a **GitHub Release** with
  permanent, user-downloadable executables (what the Download table links to).
- Manual trigger via the **"Build executables"** workflow's *Run workflow* button.

## ⚠️ Important Naukri constraints

- **No public API.** This app uses Naukri's internal, undocumented services, which can
  change or break without notice.
- **Sessions are IP-bound.** Login is tied to the IP it happened on. Changing IP
  (VPN, mobile ↔ home, dynamic ISP restart) invalidates the session → re-login.
- **Hosting matters.** Datacenter/cloud IPs (Azure, GCP, GitHub Actions) are often
  flagged or force MFA. Home / residential IPs work best.
- **Use on your own account, at low frequency.** Naukri's Terms restrict automation;
  frequent bursts can trigger blocks or account action.
- **OTP/MFA** is intentionally out of MVP scope in the login dialog. `send_otp`/
  `verify_otp` exist in the vendored client for a future enhancement.

## Project layout

```
src/
├── main.py               # Entry point
├── ui/                   # PySide6 widgets
│   ├── main_window.py    # Tab host: Profile · Edit · Refresh · Settings · About · Developer
│   ├── login_dialog.py
│   ├── profile_tab.py    # View profile
│   ├── edit_tab.py       # Edit headline / name / summary
│   ├── refresh_tab.py    # Resume download + rename + re-upload
│   ├── settings_tab.py   # Developer toggle + AI provider
│   ├── about_tab.py      # App details / version / credits
│   ├── developer_tab.py  # AI field optimizer
│   └── _label_utils.py   # Wrapping-label helpers (no window-size blowups)
├── core/
│   ├── naukri_client.py  # High-level wrapper (fetch, download & refresh resume, updates)
│   ├── session_store.py  # Persist/load/clear the saved session
│   ├── settings.py       # App settings -> config.json
│   ├── ai_client.py      # Provider-agnostic chat client (AI optimizer)
│   ├── resume_text.py    # Extract on-file resume PDF text
│   ├── version.py        # App version + metadata (single source of truth)
│   ├── worker.py         # QThread wrapper for blocking network calls
│   └── nope_ri/          # Vendored NopeRi client (relative-import edits applied)
└── models/profile.py     # Profile dataclass + response parser
```

## License

MIT. Auto-apply / bulk-scraping / third-party tooling behaviour is out of scope; keep
usage personal and within Naukri's terms.

## Disclaimer

Not affiliated with Naukri / InfoEdge India Ltd. Use responsibly.