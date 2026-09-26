from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.naukri_client import NaukriManager
from src.core.session_store import APP_DIR
from src.core.version import (
    APP_DESCRIPTION,
    APP_NAME,
    CREDITS,
    DEVELOPER,
    DISCLAIMER,
    LICENSE,
    app_version,
)
from src.ui._label_utils import make_wrapping_form_label


class AboutTab(QWidget):
    """Read-only tab showing application details, version and credits."""

    # The tab owns no network logic: MainWindow owns the worker, the settings
    # and the notification dialog, and pushes status text back in through
    # `set_update_status`. Mirrors the existing `relogin_requested` /
    # `_auth_failure` signal pattern rather than reaching across tabs.
    check_requested = Signal()

    def __init__(self, manager: NaukriManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager

        form = QFormLayout()
        form.addRow("Application", make_wrapping_form_label(APP_NAME))
        form.addRow("Version", make_wrapping_form_label(app_version()))
        form.addRow("Developer", make_wrapping_form_label(DEVELOPER))
        form.addRow("License", make_wrapping_form_label(LICENSE))
        form.addRow("Description", make_wrapping_form_label(APP_DESCRIPTION))
        form.addRow("Credits", make_wrapping_form_label(CREDITS))
        form.addRow("Data directory", make_wrapping_form_label(str(APP_DIR)))
        form.addRow("Logged in as", make_wrapping_form_label(manager.username or "-"))
        form.addRow("Disclaimer", make_wrapping_form_label(DISCLAIMER))

        # --- Updates ---
        update_group = QGroupBox("Updates")
        self.update_status = make_wrapping_form_label("")
        self.check_btn = QPushButton("Check for updates")
        # `clicked` carries a bool; `check_requested` is a no-arg signal, so
        # connect through an explicit lambda rather than relying on PySide
        # quietly dropping the extra argument.
        self.check_btn.clicked.connect(lambda _checked=False: self.check_requested.emit())
        update_btns = QHBoxLayout()
        update_btns.addWidget(self.update_status, 1)
        update_btns.addWidget(self.check_btn)
        update_layout = QVBoxLayout(update_group)
        update_layout.addLayout(update_btns)

        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addWidget(update_group)
        layout.addStretch(1)

    def set_update_status(self, text: str) -> None:
        """Show a short update status line.

        Keep the text SHORT. This label sits in a `QFormLayout` using
        `make_wrapping_form_label`, whose horizontal size policy is `Preferred`,
        so a long unbreakable token (a release URL, for instance) would widen the
        whole window. Full URLs and release notes belong in the notification
        dialog, which is its own window.
        """
        self.update_status.setText(text)

    def set_check_enabled(self, enabled: bool) -> None:
        self.check_btn.setEnabled(enabled)
