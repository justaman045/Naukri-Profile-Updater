from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.ai_client import AiClient
from src.core.naukri_client import NaukriManager
from src.core.settings import AppSettings
from src.core.worker import ApiWorker
from src.models.profile import Profile


class DeveloperTab(QWidget):
    """Unreleased / experimental tools. Hidden unless Developer options are enabled."""

    def __init__(self, manager: NaukriManager, settings: AppSettings,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self.settings = settings
        self.profile: Profile | None = None
        self._worker: ApiWorker | None = None

        self.title = QLabel("Experimental Developer Tools")
        self.title.setWordWrap(True)

        # --- AI Optimizer ---
        ai_group = QGroupBox("AI field optimizer")
        ai_hint = QLabel("Optimize a profile field using your configured AI provider "
                         "(set it up in the Settings tab). The optimized text is applied "
                         "to the Edit tab for you to review before saving.")
        ai_hint.setWordWrap(True)

        self.field_combo = QComboBox()
        self.field_combo.addItems(["Headline", "Summary"])
        self.field_combo.currentIndexChanged.connect(self._load_current)

        self.resume_input = QPlainTextEdit()
        self.resume_input.setPlaceholderText(
            "Paste your resume text here, or select a resume file / upload path. "
            "(Resume source method to be finalized.)")
        self.resume_input.setMaximumHeight(140)

        self.result_edit = QPlainTextEdit()
        self.result_edit.setReadOnly(False)
        self.result_edit.setMaximumHeight(120)

        self.gen_btn = QPushButton("Generate optimized text")
        self.gen_btn.clicked.connect(self._generate)
        self.apply_btn = QPushButton("Apply to Edit tab")
        self.apply_btn.clicked.connect(self._apply)
        self.apply_btn.setEnabled(False)
        self.ai_status = QLabel("")
        self.ai_status.setWordWrap(True)

        ai_form = QFormLayout()
        ai_form.addRow("Field", self.field_combo)
        ai_form.addRow("Resume content", self.resume_input)

        gen_row = QHBoxLayout()
        gen_row.addStretch(1)
        gen_row.addWidget(self.gen_btn)
        apply_row = QHBoxLayout()
        apply_row.addStretch(1)
        apply_row.addWidget(self.apply_btn)

        ai_layout = QVBoxLayout(ai_group)
        ai_layout.addWidget(ai_hint)
        ai_layout.addLayout(ai_form)
        ai_layout.addWidget(self.gen_btn)
        ai_layout.addWidget(self.result_edit)
        ai_layout.addLayout(apply_row)
        ai_layout.addWidget(self.ai_status)

        # --- Reserved for future tools ---
        future = QGroupBox("Coming soon")
        future_layout = QVBoxLayout(future)
        future_layout.addWidget(QLabel("More experimental tools will appear here."))

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(ai_group)
        layout.addWidget(future)
        layout.addStretch(1)

    def set_profile(self, profile: Profile) -> None:
        self.profile = profile
        self._load_current()

    def _load_current(self) -> None:
        if not self.profile:
            return
        field = self.field_combo.currentText()
        if field == "Headline":
            self.result_edit.setPlainText(self.profile.headline or "")
        else:
            self.result_edit.setPlainText(self.profile.summary or "")

    def _generate(self) -> None:
        resume = self.resume_input.toPlainText().strip()
        if not resume:
            self.ai_status.setText("Please provide resume content first.")
            return
        field = self.field_combo.currentText()
        current = self.result_edit.toPlainText().strip()
        client = AiClient(self.settings)
        self.gen_btn.setEnabled(False)
        self.ai_status.setText("Generating...")
        self._worker = ApiWorker(lambda: client.rewrite(field, current))
        self._worker.succeeded.connect(self._on_generated)
        self._worker.failed.connect(self._on_ai_error)
        self._worker.start()

    def _on_generated(self, text: str) -> None:
        self.gen_btn.setEnabled(True)
        self.result_edit.setPlainText(text)
        self.apply_btn.setEnabled(True)
        self.ai_status.setText("")

    def _on_ai_error(self, exc: Exception) -> None:
        self.gen_btn.setEnabled(True)
        self.ai_status.setText(f"AI error: {exc}")

    def _apply(self) -> None:
        from src.ui.main_window import MainWindow

        parent = self.window()
        if isinstance(parent, MainWindow):
            text = self.result_edit.toPlainText()
            field = self.field_combo.currentText()
            if field == "Headline":
                parent.edit_tab.headline.setText(text)
            else:
                parent.edit_tab.summary.setPlainText(text)
            self.ai_status.setText("Applied to Edit tab. Review and Save there.")
            parent.tabs.setCurrentWidget(parent.edit_tab)