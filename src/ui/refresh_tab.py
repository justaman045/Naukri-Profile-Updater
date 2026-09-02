from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.naukri_client import NaukriManager, _refresh_filename
from src.core.worker import ApiWorker
from src.models.profile import Profile
from src.ui._label_utils import make_wrapping_status_label


class RefreshTab(QWidget):
    def __init__(self, manager: NaukriManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self._worker: ApiWorker | None = None

        self.preview_lbl = make_wrapping_status_label("-")
        self.status_lbl = make_wrapping_status_label()

        self.refresh_btn = QPushButton("Download, rename & re-upload resume")
        self.refresh_btn.clicked.connect(self._refresh)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.refresh_btn)

        layout = QVBoxLayout(self)
        help_lbl = make_wrapping_status_label(
            "Keep your Naukri profile active: the app downloads your current resume, "
            "renames it in the `Name_Position_Month_Day_Updated.pdf` pattern, then "
            "re-uploads it as a fresh file.")
        layout.addWidget(help_lbl)
        layout.addWidget(QLabel("Next filename:"))
        layout.addWidget(self.preview_lbl)
        layout.addWidget(self.status_lbl)
        layout.addStretch(1)
        layout.addLayout(btn_row)

    def set_profile(self, profile: Profile) -> None:
        self.preview_lbl.setText(_refresh_filename(profile))

    def _refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.status_lbl.setText("Downloading current resume...")
        self._worker = ApiWorker(self.manager.refresh_resume)
        self._worker.succeeded.connect(self._on_done)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_done(self, result) -> None:
        self.refresh_btn.setEnabled(True)
        filename = result if isinstance(result, str) else "success"
        self.status_lbl.setText(f"Done. Resume refreshed as: {filename}")

    def _on_error(self, exc: Exception) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_lbl.setText(f"Refresh failed: {exc}")