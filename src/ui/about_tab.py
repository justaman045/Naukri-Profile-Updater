from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
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

        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addStretch(1)