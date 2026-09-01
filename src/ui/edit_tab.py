from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.naukri_client import NaukriManager
from src.core.worker import ApiWorker
from src.models.profile import Profile


class EditTab(QWidget):
    def __init__(self, manager: NaukriManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self._worker: ApiWorker | None = None

        self.name = QLineEdit()
        self.headline = QLineEdit()
        self.summary = QPlainTextEdit()
        self.summary.setMaximumHeight(120)

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Headline", self.headline)
        form.addRow("Summary", self.summary)

        self.save_btn = QPushButton("Save Changes")
        self.save_btn.clicked.connect(self._save)
        self.status_lbl = QLabel("")

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.save_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status_lbl)
        layout.addStretch(1)
        layout.addLayout(btn_row)

    def set_profile(self, profile: Profile) -> None:
        self.name.setText(profile.name or "")
        self.headline.setText(profile.headline or "")
        self.summary.setPlainText(profile.summary or "")
        self.status_lbl.setText("")

    def _save(self) -> None:
        name = self.name.text().strip()
        headline = self.headline.text().strip()
        summary = self.summary.toPlainText().strip()

        if not name:
            self.status_lbl.setText("Name is required.")
            return

        self.save_btn.setEnabled(False)
        self.status_lbl.setText("Saving...")
        self._worker = ApiWorker(
            lambda: self.manager.update_profile(
                headline=headline, name=name, summary=summary
            )
        )
        self._worker.succeeded.connect(self._on_saved)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_saved(self, result) -> None:
        self.save_btn.setEnabled(True)
        self.status_lbl.setText("Saved successfully.")

    def _on_error(self, exc: Exception) -> None:
        self.save_btn.setEnabled(True)
        self.status_lbl.setText(f"Save failed: {exc}")