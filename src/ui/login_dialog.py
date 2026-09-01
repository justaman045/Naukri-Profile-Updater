from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.naukri_client import NaukriManager
from src.core.worker import ApiWorker


class LoginDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Login to Naukri")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.manager: NaukriManager | None = None
        self._worker: ApiWorker | None = None

        self.email = QLineEdit()
        self.email.setPlaceholderText("you@example.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.returnPressed.connect(self._on_login_clicked)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.status_label = QLabel("")

        self.login_btn = QPushButton("Login")
        self.login_btn.setDefault(True)
        self.login_btn.clicked.connect(self._on_login_clicked)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)

        form = QFormLayout()
        form.addRow("Email", self.email)
        form.addRow("Password", self.password)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.login_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter your Naukri credentials"))
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)

    def _set_busy(self, busy: bool) -> None:
        self.email.setEnabled(not busy)
        self.password.setEnabled(not busy)
        self.login_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(not busy)
        self.status_label.setText("Logging in..." if busy else "")

    def _on_login_clicked(self) -> None:
        email = self.email.text().strip()
        password = self.password.text()
        if not email or not password:
            self._show_error("Please enter both email and password.")
            return
        self.error_label.setVisible(False)
        self._set_busy(True)

        manager = NaukriManager(email, password, use_saved_session=False)
        self._worker = ApiWorker(manager.login)
        self._worker.succeeded.connect(lambda: self._on_login_success(manager))
        self._worker.failed.connect(self._on_login_failure)
        self._worker.start()

    def _on_login_success(self, manager: NaukriManager) -> None:
        self.manager = manager
        self.accept()

    def _on_login_failure(self, exc: Exception) -> None:
        self._set_busy(False)
        self._show_error(str(exc) or "Login failed. Check your credentials and network.")

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)
        self.error_label.setVisible(True)