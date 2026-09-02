"""Single source of truth for application identity and version.

`app_version()` prefers the ``[project] version`` from ``pyproject.toml`` when
running from a source checkout, and falls back to a hardcoded constant inside a
PyInstaller bundle (the frozen app does not ship ``pyproject.toml``). Keep the
fallback in sync with ``pyproject.toml`` when bumping the release version.
"""
import re
from pathlib import Path

APP_NAME = "Naukri Profile Manager"
DEVELOPER = "Aman"
LICENSE = "MIT"
APP_DESCRIPTION = (
    "Cross-platform desktop app to view and update your Naukri profile, "
    "headless over HTTP (no browser)."
)
DISCLAIMER = "Not affiliated with Naukri / InfoEdge India Ltd. Use responsibly."
CREDITS = (
    "Vendored NopeRi (github.com/Traverser25/NopeRi) for Naukri interaction; "
    "built with PySide6, httpcloak, requests and pypdf."
)

_FALLBACK_VERSION = "0.1.0"
_PROJECT_VERSION_RE = re.compile(r"^\s*version\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)


def _project_root() -> Path:
    """Repo root when running from source; degrading gracefully when frozen."""
    here = Path(__file__).resolve()
    candidates = [here, here.parent, here.parent.parent, here.parent.parent.parent]
    for cand in candidates:
        pyproject = cand / "pyproject.toml"
        if pyproject.exists():
            return cand
    return here.parent.parent


def app_version() -> str:
    """Return the application version (from pyproject.toml or the fallback)."""
    pyproject = _project_root() / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
        match = _PROJECT_VERSION_RE.search(text)
        if match:
            return match.group(1).strip() or _FALLBACK_VERSION
    except OSError:
        pass
    return _FALLBACK_VERSION