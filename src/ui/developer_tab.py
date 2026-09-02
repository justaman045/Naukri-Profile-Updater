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

from src.core.ai_client import AiClient, field_max
from src.core.naukri_client import NaukriManager
from src.core.resume_text import ResumeTextError, extract_resume_text
from src.core.settings import AppSettings
from src.core.worker import ApiWorker
from src.models.profile import Profile
from src.ui._label_utils import make_wrapping_status_label


class DeveloperTab(QWidget):
    """Unreleased / experimental tools. Hidden unless Developer options are enabled."""

    def __init__(self, manager: NaukriManager, settings: AppSettings,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self.settings = settings
        self.profile: Profile | None = None
        self._worker: ApiWorker | None = None
        self._resume_worker: ApiWorker | None = None

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
            "Resume content is auto-loaded from your on-file Naukri resume. "
            "You may edit it before generating.")
        self.resume_input.setMaximumHeight(140)

        self.load_resume_btn = QPushButton("Reload from on-file resume")
        self.load_resume_btn.clicked.connect(self._auto_load_resume)

        resume_header = QHBoxLayout()
        resume_header.addWidget(QLabel("Resume content (auto-loaded)"))
        resume_header.addStretch(1)
        resume_header.addWidget(self.load_resume_btn)

        self.result_edit = QPlainTextEdit()
        self.result_edit.setReadOnly(False)
        self.result_edit.setMaximumHeight(120)
        self.result_edit.textChanged.connect(self._update_result_count)

        self.result_count_lbl = QLabel("")
        result_header = QHBoxLayout()
        result_header.addWidget(QLabel("Generated result"))
        result_header.addStretch(1)
        result_header.addWidget(self.result_count_lbl)

        self.gen_btn = QPushButton("Generate optimized text")
        self.gen_btn.clicked.connect(self._generate)
        self.apply_btn = QPushButton("Apply to Edit tab")
        self.apply_btn.clicked.connect(self._apply)
        self.apply_btn.setEnabled(False)
        self.ai_status = make_wrapping_status_label()

        ai_form = QFormLayout()
        ai_form.addRow("Field", self.field_combo)
        ai_form.addRow(resume_header)
        ai_form.addRow(self.resume_input)

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
        ai_layout.addLayout(result_header)
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
        self._auto_load_resume()

    def _load_current(self) -> None:
        if not self.profile:
            return
        field = self.field_combo.currentText()
        if field == "Headline":
            self.result_edit.setPlainText(self.profile.headline or "")
        else:
            self.result_edit.setPlainText(self.profile.summary or "")
        self._update_result_count()

    def _update_result_count(self) -> None:
        field = self.field_combo.currentText()
        max_len = field_max(field)
        n = len(self.result_edit.toPlainText())
        if not max_len:
            self.result_count_lbl.setText(f"{n} chars")
            self.result_count_lbl.setStyleSheet("")
            return
        over = n > max_len
        self.result_count_lbl.setText(f"{n} / {max_len}")
        self.result_count_lbl.setStyleSheet("color: red;" if over else "")

    def _auto_load_resume(self) -> None:
        """Download and extract the on-file resume text in the background."""
        if self._resume_worker and self._resume_worker.isRunning():
            return
        self.load_resume_btn.setEnabled(False)
        self.ai_status.setText("Downloading & extracting on-file resume...")
        self._resume_worker = ApiWorker(lambda: extract_resume_text(self.manager))
        self._resume_worker.succeeded.connect(self._on_resume_loaded)
        self._resume_worker.failed.connect(self._on_resume_error)
        self._resume_worker.start()

    def _on_resume_loaded(self, text: str) -> None:
        self.load_resume_btn.setEnabled(True)
        self.resume_input.setPlainText(text)
        self.ai_status.setText(
            f"Resume content loaded from your on-file resume ({len(text)} chars). "
            "You may edit it before generating.")

    def _on_resume_error(self, exc: Exception) -> None:
        self.load_resume_btn.setEnabled(True)
        msg = exc.args[0] if exc.args else str(exc)
        self.ai_status.setText(f"{msg} You can paste text manually.")

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
        self._worker = ApiWorker(
            lambda: client.rewrite(field, current, resume_text=resume)
        )
        self._worker.succeeded.connect(self._on_generated)
        self._worker.failed.connect(self._on_ai_error)
        self._worker.start()

    def _on_generated(self, text: str) -> None:
        self.gen_btn.setEnabled(True)
        self.result_edit.setPlainText(text)
        self.apply_btn.setEnabled(True)
        self.ai_status.setText("")
        self._update_result_count()

    def _on_ai_error(self, exc: Exception) -> None:
        self.gen_btn.setEnabled(True)
        self.ai_status.setText(f"AI error: {exc}")

    def _apply(self) -> None:
        from src.ui.main_window import MainWindow

        field = self.field_combo.currentText()
        text = self.result_edit.toPlainText()
        max_len = field_max(field)
        if max_len and len(text) > max_len:
            self.ai_status.setText(
                f"Cannot apply: {field} is {len(text)} chars (over the {max_len} "
                "limit). Trim it in the result box first.")
            self.result_count_lbl.setStyleSheet("color: red;")
            return
        parent = self.window()
        if isinstance(parent, MainWindow):
            if field == "Headline":
                parent.edit_tab.headline.setText(text)
            else:
                parent.edit_tab.summary.setPlainText(text)
            self.ai_status.setText("Applied to Edit tab. Review and Save there.")
            parent.tabs.setCurrentWidget(parent.edit_tab)