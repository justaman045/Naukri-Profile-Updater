"""Check GitHub Releases for a newer build of the app.

Deliberately standalone, NOT a `NaukriManager` method. Two reasons:

* A GitHub 403 (rate limit) or 404 must never be mistaken for a dead Naukri
  session, so this must not run behind `NaukriManager._guard_auth`.
* It uses plain `requests`, never the shared httpcloak session. That session
  serves cached static assets as `304 Not Modified` with an empty body (it
  already broke the formKey scrape), it is IP-bound, and it is fingerprinted
  by Naukri -- there is no reason to touch it for an unauthenticated public
  API call.

It also must not be wrapped in `with_exponential_retry`. That helper sleeps up
to 60s between attempts, which would guarantee `ApiWorker.shutdown()` has to
fall back to `terminate()` on quit. A failed update check is not worth
retrying: the next launch tries again.
"""

import logging
import sys
import time
from dataclasses import dataclass

import requests

from src.core.settings import AppSettings

logger = logging.getLogger(__name__)

REPO = "justaman045/Naukri-Profile-Updater"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

# At most one outbound request per day. GitHub allows 60/hr unauthenticated per
# IP, so this is far below the limit and keeps the app from phoning home on
# every launch.
UPDATE_CHECK_INTERVAL = 24 * 3600

# Short by design: this runs on startup, and `MainWindow.closeEvent` only waits
# 2s for workers (see `ApiWorker.shutdown`). The manual "Check now" path passes
# a longer timeout because the user is waiting on it deliberately.
AUTO_CHECK_TIMEOUT = 5
MANUAL_CHECK_TIMEOUT = 15

_HEADERS = {
    # GitHub's REST docs still require a User-Agent (they used to reject the
    # request outright without one). Verified 2026-09: the endpoint currently
    # answers 200 even with every header cleared, and `requests` injects its own
    # `python-requests/<x>` by default -- so this is about identifying the app
    # and not breaking if GitHub restores enforcement, not about fixing a 403
    # we can currently reproduce.
    "User-Agent": "NaukriProfileManager-update-check",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class UpdateCheckError(Exception):
    """Raised when the update check could not be completed.

    Every network/protocol problem surfaces as this so the UI has a single,
    non-fatal branch to take. Nothing about a failed check is worth a dialog.
    """


@dataclass
class UpdateInfo:
    """A release newer than the running build."""

    version: str  # "0.4.0", no leading "v"
    url: str  # the release's own html_url, straight from the API
    notes: str  # release body, clipped


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Return a comparable ``(major, minor, patch)`` tuple, or None.

    The release workflow computes versions as strict ``X.Y.Z`` integers, so
    there is no need for a `packaging` dependency. Anything that is not three
    numeric components (a ``v1.0-beta1`` tag, an empty string, the literal
    ``"master"`` after a branch push) yields None so an odd tag can never crash
    the app or produce a bogus "update available".
    """
    if not text:
        return None
    cleaned = str(text).strip().lstrip("vV")
    parts = cleaned.split(".")
    if len(parts) != 3:
        return None
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError:
        return None
    if major < 0 or minor < 0 or patch < 0:
        return None
    return major, minor, patch


def is_newer(remote: str, current: str) -> bool:
    """True when `remote` is a strictly newer, parseable version than `current`."""
    parsed_remote = parse_version(remote)
    parsed_current = parse_version(current)
    if parsed_remote is None:
        return False
    if parsed_current is None:
        # Running an unparseable version (a dev checkout on a tagged branch):
        # do not claim an update.
        return False
    return parsed_remote > parsed_current


def _clip(text: str, limit: int = 800) -> str:
    """Trim release notes to a length that is safe to put in a dialog."""
    if not isinstance(text, str):
        return ""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "..."


def check_for_update(
    current_version: str, timeout: int = AUTO_CHECK_TIMEOUT
) -> UpdateInfo | None:
    """Return info about a newer release, or None when already up to date.

    Raises `UpdateCheckError` for anything that went wrong talking to GitHub.
    A tag that is not a plain ``X.Y.Z`` version is treated as "no update" rather
    than an error, since `/releases/latest` already excludes drafts and
    prereleases and a well-formed tag is the only case worth surfacing.
    """
    try:
        resp = requests.get(API_LATEST, headers=_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise UpdateCheckError(f"could not reach GitHub: {exc}") from exc

    if resp.status_code != 200:
        raise UpdateCheckError(f"GitHub returned HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise UpdateCheckError("GitHub returned a non-JSON response") from exc

    if not isinstance(data, dict):
        raise UpdateCheckError("GitHub returned an unexpected payload")

    tag = data.get("tag_name") or ""
    if not is_newer(tag, current_version):
        return None

    url = data.get("html_url") or RELEASES_PAGE
    return UpdateInfo(
        version=str(tag).strip().lstrip("vV"),
        url=str(url),
        notes=_clip(data.get("body") or ""),
    )


def should_check(settings: AppSettings, *, force: bool = False) -> bool:
    """True when an update check is allowed to run right now.

    Encapsulates the gates that can be known without talking to GitHub:

    * the user left the feature enabled,
    * the last check was more than `UPDATE_CHECK_INTERVAL` ago (unless forced),
    * and a source checkout is skipped -- the repo's `pyproject.toml` version
      lags the newest tag until CI's bump commit lands, so a developer on master
      would be nagged about a version they are literally building.

    The per-version "remind me later" gate cannot live here, because deciding it
    requires knowing the latest version. The caller applies it on the result.
    """
    if not settings.check_for_updates:
        return False
    if not getattr(sys, "frozen", False):
        return False
    if not force:
        age = time.time() - float(settings.last_update_check or 0.0)
        if age < UPDATE_CHECK_INTERVAL:
            return False
    return True
