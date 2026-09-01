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
from src.ui.login_dialog import LoginDialog
from src.ui.main_window import MainWindow


def _login_interactively() -> NaukriManager | None:
    dlg = LoginDialog()
    if dlg.exec() != LoginDialog.Accepted:
        return None
    return dlg.manager


def _resolve_manager() -> NaukriManager | None:
    saved = session_store.load_session()
    if saved and saved.bearer_token:
        manager = NaukriManager(saved.username, "", use_saved_session=True)
        if manager.has_saved_session:
            return manager
    return _login_interactively()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Naukri Profile Manager")

    manager = _resolve_manager()
    if manager is None:
        return 0  # user cancelled login

    window = MainWindow(manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())