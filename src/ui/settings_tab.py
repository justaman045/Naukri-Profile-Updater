from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.ai_client import AiClient, _provider_requires_key
from src.core.settings import AppSettings, DEFAULT_BASE_URLS, PROVIDER_LABELS, save_settings
from src.core.worker import ApiWorker
from src.ui._label_utils import make_wrapping_status_label


class SettingsTab(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings
        self._model_worker: ApiWorker | None = None

        # --- Developer options ---
        dev_group = QGroupBox("Developer options")
        self.dev_check = QCheckBox("Enable Developer options (hidden/experimental tools)")
        self.dev_check.setChecked(self.settings.show_developer)
        self.dev_check.toggled.connect(self._on_dev_toggled)
        dev_layout = QVBoxLayout(dev_group)
        dev_layout.addWidget(self.dev_check)

        # --- AI provider ---
        ai_group = QGroupBox("AI optimizer")
        self.provider_combo = QComboBox()
        for key in PROVIDER_LABELS:
            self.provider_combo.addItem(PROVIDER_LABELS[key], key)
        idx = self.provider_combo.findData(self.settings.ai_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

        self.base_url = QLineEdit(self.settings.effective_base_url)
        self.base_url.setPlaceholderText("https://.../v1")
        self.api_key = QLineEdit(self.settings.ai_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.textChanged.connect(self._update_load_button_state)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        if self.settings.ai_model:
            self.model_combo.addItem(self.settings.ai_model)
            self.model_combo.setCurrentText(self.settings.ai_model)
        self.model_combo.setPlaceholderText("Select or type a model")

        self._model_completer = QCompleter(self.model_combo)
        self._model_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._model_completer.setFilterMode(Qt.MatchContains)
        self._model_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._model_completer.setMaxVisibleItems(12)
        self._model_completer.setModel(QStringListModel())
        self.model_combo.setCompleter(self._model_completer)

        self.load_models_btn = QPushButton("Load models")
        self.load_models_btn.clicked.connect(self._load_models)

        model_row = QHBoxLayout()
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.load_models_btn)

        ai_form = QFormLayout(ai_group)
        ai_form.addRow("Provider", self.provider_combo)
        ai_form.addRow("Base URL", self.base_url)
        ai_form.addRow("Model", model_row)
        ai_form.addRow("API key", self.api_key)

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self._save)
        self.status_lbl = make_wrapping_status_label()

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.save_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(dev_group)
        layout.addWidget(ai_group)
        layout.addWidget(self.status_lbl)
        layout.addStretch(1)
        layout.addLayout(btn_row)

        self._update_load_button_state()

    #
    # UI helpers
    #
    def _working_settings(self) -> AppSettings:
        """Build an AppSettings snapshot from the current form values."""
        s = AppSettings(
            show_developer=self.dev_check.isChecked(),
            ai_provider=self.provider_combo.currentData(),
            ai_base_url=self.base_url.text().strip(),
            ai_model=self.model_combo.currentText().strip(),
            ai_api_key=self.api_key.text().strip(),
        )
        return s

    def _on_provider_changed(self) -> None:
        key = self.provider_combo.currentData()
        dflt = DEFAULT_BASE_URLS.get(key, "")
        base = self.base_url.text().strip()
        if dflt and (not base or base == self.settings.effective_base_url):
            self.base_url.setText(dflt)
        self._update_load_button_state()
        self._auto_load_models()

    def _update_load_button_state(self) -> None:
        provider = self.provider_combo.currentData()
        needs_key = _provider_requires_key(provider)
        self.load_models_btn.setEnabled((not needs_key) or bool(self.api_key.text().strip()))

    def _auto_load_models(self) -> None:
        if not self.base_url.text().strip():
            return
        self._load_models()

    def _load_models(self) -> None:
        if self._model_worker and self._model_worker.isRunning():
            return
        if not self.base_url.text().strip():
            self.status_lbl.setText("Enter a base URL before loading models.")
            return
        client = AiClient(self._working_settings())
        self.load_models_btn.setEnabled(False)
        self.status_lbl.setText("Loading models...")
        self._model_worker = ApiWorker(client.list_models)
        self._model_worker.succeeded.connect(self._on_models_loaded)
        self._model_worker.failed.connect(self._on_models_error)
        self._model_worker.start()

    def _on_models_loaded(self, models: list) -> None:
        current = self.model_combo.currentText().strip()
        self.model_combo.clear()
        self._model_completer.setModel(QStringListModel(models))
        for m in models:
            self.model_combo.addItem(m)
        if current and current in models:
            self.model_combo.setCurrentText(current)
        elif models:
            self.model_combo.setCurrentText(models[0])
        self._update_load_button_state()
        self.status_lbl.setText(f"Loaded {len(models)} model(s).")

    def _on_models_error(self, exc: Exception) -> None:
        self._update_load_button_state()
        self.status_lbl.setText(f"Could not load models: {exc}")

    #
    # Save
    #
    def _on_dev_toggled(self, checked: bool) -> None:
        self.settings.show_developer = checked

    def _save(self) -> None:
        self.settings.ai_provider = self.provider_combo.currentData()
        self.settings.ai_base_url = self.base_url.text().strip()
        self.settings.ai_model = self.model_combo.currentText().strip()
        self.settings.ai_api_key = self.api_key.text().strip()
        self.settings.show_developer = self.dev_check.isChecked()
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.status_lbl.setText(f"Could not save settings: {exc}")
            return
        self.status_lbl.setText("Settings saved.")