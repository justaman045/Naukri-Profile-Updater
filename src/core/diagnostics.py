"""Crash diagnostics for the packaged app.

The Windows build ships as a windowed (``--windowed``) PyInstaller executable:
there is no console, and an unhandled exception surfaces as a bare
"Failed to execute script: main" message box. That tells the user nothing,
and it tells us nothing either — every report ends up as "some DLL is not
found" with no detail.

This module gives the app a real diagnostic trail:

* every log record goes to ``~/.naukri-profile-update/app.log``;
* an unhandled exception — on the main thread *or* on a worker thread — is
  written with its full traceback to ``~/.naukri-profile-update/error.log``
  and shown in a dialog that points at that file.

Install it as early as possible (before importing PySide6): a missing or
mismatched DLL in a packaged build raises *during import*, and that is
exactly the failure this exists to capture.
"""

import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.core.session_store import APP_DIR

LOG_FILE = APP_DIR / "app.log"
ERROR_FILE = APP_DIR / "error.log"

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_configured = False


def error_log_path() -> str:
    """Absolute path of the crash log, as shown to the user."""
    return str(ERROR_FILE)


def setup_logging(level: int = logging.INFO) -> None:
    """Send log records to ``~/.naukri-profile-update/app.log``.

    Never raises: a read-only home directory must not stop the app from
    starting. Rotating at 1 MB keeps the file small enough to attach to a
    bug report.
    """
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(level)

    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
    except OSError:
        # No writable home directory — keep logging to stderr only.
        pass

    # A console handler is harmless in a windowed build (stderr is simply not
    # attached) and invaluable when running from source.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(stream)


def _append_error_log(exc_type, exc_value, tb) -> Path:
    """Append a formatted traceback to ``error.log`` and return its path."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    body = "".join(traceback.format_exception(exc_type, exc_value, tb))
    with ERROR_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"\n===== {stamp} =====\n{body}")
    return ERROR_FILE


def _show_critical(title: str, text: str) -> None:
    """Best-effort error dialog. Never raises, never aborts.

    ``QMessageBox`` needs a live ``QApplication``; constructing one just to
    show a dialog is not safe here (Qt aborts the process rather than raising
    when a widget is created without an application), so fall back to the
    Win32 dialog when there is no application yet.
    """
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            QMessageBox.critical(None, title, text)
            return
    except Exception:  # noqa: BLE001 - diagnostics must never fail
        pass

    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
            return
    except Exception:  # noqa: BLE001 - diagnostics must never fail
        pass

    print(f"{title}\n{text}", file=sys.stderr)


def install_excepthooks() -> None:
    """Route unhandled exceptions (main thread and worker threads) to disk.

    Worker threads matter here: the app does all of its network I/O on an
    ``ApiWorker`` thread, so a crash in that thread would otherwise vanish
    without a trace.
    """
    previous_hook = sys.excepthook

    def _hook(exc_type, exc_value, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous_hook(exc_type, exc_value, tb)
            return
        try:
            path = _append_error_log(exc_type, exc_value, tb)
        except Exception:  # noqa: BLE001 - diagnostics must never fail
            path = ERROR_FILE
        logging.getLogger(__name__).critical(
            "unhandled exception", exc_info=(exc_type, exc_value, tb)
        )
        _show_critical(
            "Naukri Profile Manager - unexpected error",
            "Something went wrong and the app could not continue.\n\n"
            f"Details were written to:\n{path}\n\n"
            "Please send that file along with your report so the problem can "
            "be fixed.",
        )

    sys.excepthook = _hook

    def _thread_hook(args) -> None:
        _hook(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = _thread_hook


def log_startup_info() -> None:
    """Record the build/runtime fingerprint that makes a report actionable."""
    logger = logging.getLogger(__name__)
    logger.info("frozen=%s executable=%s cwd=%s", getattr(sys, "frozen", False),
                sys.executable, os.getcwd())
    logger.info("python=%s platform=%s", sys.version.split()[0], sys.platform)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        logger.info("bundle root=%s", meipass)
