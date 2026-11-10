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
| Windows             | x86_64          | [NaukriProfileManager-0.7.0-windows-x86_64.exe](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.7.0/NaukriProfileManager-0.7.0-windows-x86_64.exe) · [one-folder zip](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.7.0/NaukriProfileManager-0.7.0-windows-x86_64-ondir.zip) |
| Linux               | x86_64          | [NaukriProfileManager-0.7.0-linux-x86_64.zip](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.7.0/NaukriProfileManager-0.7.0-linux-x86_64.zip) · [raw binary](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.7.0/NaukriProfileManager-0.7.0-linux-x86_64) |
| macOS (Intel)       | x86_64          | [NaukriProfileManager-0.7.0-macos-x86_64](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.7.0/NaukriProfileManager-0.7.0-macos-x86_64) |
| macOS (Apple Silicon) | arm64         | [NaukriProfileManager-0.7.0-macos-arm64](https://github.com/justaman045/Naukri-Profile-Updater/releases/download/v0.7.0/NaukriProfileManager-0.7.0-macos-arm64) |

> The links above point at the current `v0.7.0` release. After each new tag, the
> [Releases page](https://github.com/justaman045/Naukri-Profile-Updater/releases/latest)
> always carries the newest per-OS executables.
>
> **Windows:** download the `.exe` for the normal case. If it refuses to start,
> grab the **one-folder zip** instead — it runs straight from its own folder
> and never unpacks itself into `%TEMP%`, which is where antivirus software
> most often gets in the way.
>
> **Linux:** if your browser stalls on the download, use the terminal instead —
> `gh release download --repo justaman045/Naukri-Profile-Updater --pattern '*-linux-*'`
> or `curl -LO https://github.com/justaman045/Naukri-Profile-Updater/releases/latest/download/NaukriProfileManager-0.7.0-linux-x86_64.zip`.
> Then `unzip`, `chmod +x NaukriProfileManager-*-linux-x86_64`, and run it.
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

- **Python 3.10+** · **PySide6-Essentials** (Qt6) for the desktop UI.
- Vendored, trimmed copy of [NopeRi](https://github.com/Traverser25/NopeRi) for Naukri
  HTTP interaction (login, profile update, resume upload), plus custom additions:
  `fetch_profile` (rich `v2/users/self` read) and resume download
  (`v1/users/self/profiles/{id}/resume`).
- **httpcloak** for the HTTP/TLS transport. It ships a native library
  (`libhttpcloak-<os>-<arch>`) that the packaged build has to bundle — see
  [Packaging notes](#packaging-notes).
- **pypdf** for extracting resume PDF text (feeds the AI optimizer).
- **PyInstaller** for packaging.

## Troubleshooting

### The app does not start (Windows)

The packaged build is a windowed executable, so it has no console. Every run
still leaves a trail in your home directory:

| File | Contents |
|------|----------|
| `~/.naukri-profile-update/app.log` | the full application log |
| `~/.naukri-profile-update/error.log` | the traceback of any crash that was not handled |

If the app dies on start-up, send us `error.log` — it names the exact failing
step (a missing native library, a network error, …) instead of the generic
"Failed to execute script" message box.

Two things worth trying first:

1. **Use the one-folder zip.** The single-file `.exe` unpacks itself into
   `%TEMP%` on every launch. Antivirus software sometimes quarantines files
   there, and a blocked extraction looks exactly like a missing DLL. The
   one-folder build never extracts anything.
2. **Clear the extraction cache.** Delete everything under
   `%TEMP%\_MEI*` and start again.

### "Could not find httpcloak library"

The native library that httpcloak needs was not found. This is a packaging
problem in the build, not something you can fix on your machine — please
report it together with `error.log`.

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
python build.py --onefile --versioned --version v0.7.0
                                         # -> NaukriProfileManager-0.7.0-<os>-<arch>
```

**PyInstaller does not cross-compile.** Build Linux on Linux, Windows on Windows, and macOS
on macOS. `build.py` embeds the app version into the executable's file properties and uses
`app.ico`/`app.icns`/`app.png` as the icon when present.

### Packaging notes

httpcloak is a native extension: it ships a platform-specific shared library
(`libhttpcloak-windows-amd64.dll` and friends) that PyInstaller does not
collect on its own. `build.py` bundles it into `httpcloak/lib/` — the exact
directory httpcloak searches at runtime — and then **verifies the artifact it
just produced**:

```bash
python tools/verify_bundle.py dist/NaukriProfileManager-0.7.0-linux-x86_64
```

The check confirms the native library is present *and* that every dependency
of that library is in the bundle too. On Windows that second part matters: the
httpcloak DLL is built with MinGW and needs `libgcc_s_seh-1.dll` and a few
OpenSSL DLLs. A bundle missing those builds fine, loads fine on the build
machine, and then fails on every user's machine with
`The specified module could not be found` — an error that never names the
DLL that is actually missing.

`build.py` runs this check automatically and refuses to produce a release
artifact that fails it, so CI cannot publish a broken executable.

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

- **Every push to `master`** → builds all four platforms, bumps the minor version
  (`0.1.0` → `0.2.0`), rewrites this Download table and the About-tab version,
  tags `vX.Y.Z`, and publishes a **GitHub Release** with permanent assets.
- Manual trigger via the **"Build executables"** workflow's *Run workflow* button
  builds artifacts only, unless its `release` input is enabled.

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
│   ├── native_lib.py     # Locate/load httpcloak's native library (frozen builds)
│   ├── diagnostics.py    # app.log + error.log, crash hooks for the windowed build
│   ├── session_store.py  # Persist/load/clear the saved session
│   ├── settings.py       # App settings -> config.json
│   ├── ai_client.py      # Provider-agnostic chat client (AI optimizer)
│   ├── resume_text.py    # Extract on-file resume PDF text
│   ├── version.py        # App version + metadata (single source of truth)
│   ├── worker.py         # QThread wrapper for blocking network calls
│   └── nope_ri/          # Vendored NopeRi client (relative-import edits applied)
└── models/profile.py     # Profile dataclass + response parser
tools/
└── verify_bundle.py      # CI gate: the bundle really contains httpcloak's native lib
```

## License

MIT. Auto-apply / bulk-scraping / third-party tooling behaviour is out of scope; keep
usage personal and within Naukri's terms.

## Disclaimer

Not affiliated with Naukri / InfoEdge India Ltd. Use responsibly.