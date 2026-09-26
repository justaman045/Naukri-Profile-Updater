import logging
import sys
import os
from pathlib import Path

# Refuse to run when not inside a virtualenv (packaged/frozen builds are exempt).
def _require_venv() -> bool:
    if getattr(sys, "frozen", False):
        return True
    if os.environ.get("VIRTUAL_ENV"):
        return True
    if sys.prefix != sys.base_prefix:
        return True
    return bool(getattr(sys, "real_prefix", None))

if not _require_venv():
    print(
        "This app must be run inside a virtual environment.\n"
        "  python3 -m venv .venv && source .venv/bin/activate\n"
        "  pip install -r requirements.txt && python src/main.py",
        file=sys.stderr,
    )
    sys.exit(1)

# Ensure `src` is importable whether we run from repo root or from a
# PyInstaller one-file bundle (where the package lives under _MEIPASS).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from src.core.naukri_client import NaukriManager
from src.core import session_store
from src.core.worker import ApiWorker
from src.ui.login_dialog import LoginDialog
from src.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def _login_interactively(prefill_email: str = "") -> NaukriManager | None:
    dlg = LoginDialog(prefill_email=prefill_email)
    if dlg.exec() != LoginDialog.Accepted:
        return None
    return dlg.manager


def _resolve_manager(prefill_email: str = "") -> NaukriManager | None:
    saved = session_store.load_session()
    if saved and saved.bearer_token:
        manager = NaukriManager(saved.username, "", use_saved_session=True)
        if manager.has_saved_session:
            return manager
    return _login_interactively(prefill_email)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Naukri Profile Manager")

    # Loop so that logging out can return to the login dialog without the user
    # having to restart the app. Closing the window ends the loop. `prefill_email`
    # remembers which account just lost its session so the login dialog can
    # pre-select it (and its saved password) on the next pass.
    prefill_email = ""
    while True:
        manager = _resolve_manager(prefill_email)
        if manager is None:
            return 0  # user cancelled login
        prefill_email = manager.username

        window = MainWindow(manager)
        window.show()
        app.exec()

        # The event loop has stopped, so Qt is about to be torn down (or the
        # window replaced below). A worker still blocked in a network call would
        # be destroyed during finalization, which aborts the process with
        # "QThread: Destroyed while thread is still running" (exit 134) after
        # main() has already returned cleanly. Drain them first.
        if not ApiWorker.shutdown():
            logger.error("exiting while a worker is still running")

        if not window.relogin_requested:
            return 0
        prefill_email = window.manager.username
        window.deleteLater()


if __name__ == "__main__":
    sys.exit(main())