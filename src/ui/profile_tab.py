from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.naukri_client import NaukriManager
from src.core.worker import ApiWorker
from src.models.profile import Profile


class ProfileTab(QWidget):
    def __init__(self, manager: NaukriManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self._worker: ApiWorker | None = None

        self.name_lbl = QLabel("-")
        self.headline_lbl = QLabel("-")
        self.headline_lbl.setWordWrap(True)
        self.summary_lbl = QLabel("-")
        self.summary_lbl.setWordWrap(True)
        self.skills_lbl = QLabel("-")
        self.skills_lbl.setWordWrap(True)
        self.position_lbl = QLabel("-")
        self.experience_lbl = QLabel("-")
        self.expected_ctc_lbl = QLabel("-")
        self.current_ctc_lbl = QLabel("-")
        self.notice_lbl = QLabel("-")
        self.city_lbl = QLabel("-")
        self.email_lbl = QLabel("-")
        self.phone_lbl = QLabel("-")
        self.resume_lbl = QLabel("-")
        self.resume_lbl.setWordWrap(True)
        self.pid_lbl = QLabel("-")

        form = QFormLayout()
        form.addRow("Name", self.name_lbl)
        form.addRow("Headline", self.headline_lbl)
        form.addRow("Summary", self.summary_lbl)
        form.addRow("Skills", self.skills_lbl)
        form.addRow("Position", self.position_lbl)
        form.addRow("Experience", self.experience_lbl)
        form.addRow("Current CTC", self.current_ctc_lbl)
        form.addRow("Expected CTC", self.expected_ctc_lbl)
        form.addRow("Notice Period", self.notice_lbl)
        form.addRow("City", self.city_lbl)
        form.addRow("Email", self.email_lbl)
        form.addRow("Phone", self.phone_lbl)
        form.addRow("Resume", self.resume_lbl)
        form.addRow("Profile ID", self.pid_lbl)
        form.setLabelAlignment(Qt.AlignRight)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.status_lbl = QLabel("")

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.refresh_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addWidget(self.status_lbl)
        layout.addLayout(btn_row)

    def refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.status_lbl.setText("Loading profile...")
        self._worker = ApiWorker(self.manager.fetch_profile)
        self._worker.succeeded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_loaded(self, profile: Profile) -> None:
        self._populate(profile)
        self.refresh_btn.setEnabled(True)
        self.status_lbl.setText("")

    def _on_error(self, exc: Exception) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_lbl.setText(f"Failed to load profile: {exc}")

    def _populate(self, profile: Profile) -> None:
        self.name_lbl.setText(profile.name or "-")
        self.headline_lbl.setText(profile.headline or "-")
        self.summary_lbl.setText(profile.summary or "-")
        self.skills_lbl.setText(profile.skills or "-")
        self.position_lbl.setText(profile.position or "-")
        exp = []
        if profile.experience_years:
            exp.append(f"{profile.experience_years} yr")
        if profile.experience_months:
            exp.append(f"{profile.experience_months} mon")
        self.experience_lbl.setText(" ".join(exp) or "-")
        self.expected_ctc_lbl.setText(profile.expected_ctc or "-")
        self.current_ctc_lbl.setText(profile.current_ctc or "-")
        self.notice_lbl.setText(profile.notice_period or "-")
        self.city_lbl.setText(profile.city or "-")
        self.email_lbl.setText(profile.email or "-")
        self.phone_lbl.setText(profile.phone or "-")
        resume_parts = [p for p in (
            profile.resume_name,
            profile.resume_format.upper() if profile.resume_format else "",
            profile.resume_upload_date,
        ) if p]
        self.resume_lbl.setText(" &middot; ".join(resume_parts) if resume_parts else "-")
        self.pid_lbl.setText(profile.profile_id or "-")