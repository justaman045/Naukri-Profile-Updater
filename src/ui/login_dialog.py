from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.credentials import get_credential, list_credentials, save_credential
from src.core.naukri_client import NaukriManager
from src.core.worker import ApiWorker


class LoginDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, prefill_email: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Login to Naukri")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.manager: NaukriManager | None = None
        self._worker: ApiWorker | None = None

        # --- Saved accounts ---
        self.account_combo = QComboBox()
        self.account_combo.addItem("— select a saved account —", "")
        for cred in list_credentials():
            hint = "password saved" if cred.password else "email only"
            self.account_combo.addItem(f"{cred.email}  ({hint})", cred.email)
        self.account_combo.currentIndexChanged.connect(self._on_account_selected)

        self.email = QLineEdit()
        self.email.setPlaceholderText("you@example.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.returnPressed.connect(self._on_login_clicked)

        self.remember_check = QCheckBox("Remember password to sign in automatically")
        self.remember_check.setToolTip(
            "Stored in plain text in ~/.naukri-profile-update/credentials.json, "
            "next to the saved session. Leave unchecked to save only the email."
        )

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
        layout.addWidget(self.account_combo)
        layout.addLayout(form)
        layout.addWidget(self.remember_check)
        layout.addWidget(self.error_label)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)

        # Prefill last so the combo's selection signal fills the fields.
        if prefill_email:
            self._select_account(prefill_email)
        self._set_busy(False)
        if not self.email.text().strip():
            self.email.setFocus()
        else:
            self.password.setFocus()

    def _select_account(self, email: str) -> bool:
        """Point the combo at `email` when it is a saved account."""
        index = self.account_combo.findData(email)
        if index < 0:
            index = self.account_combo.findData(email.strip().lower())
        if index < 0:
            return False
        if self.account_combo.currentIndex() == index:
            self._on_account_selected(index)
        else:
            self.account_combo.setCurrentIndex(index)
        return True

    def _on_account_selected(self, index: int) -> None:
        email = self.account_combo.itemData(index) or ""
        if not email:
            return
        cred = get_credential(email)
        if not cred:
            return
        self.email.setText(cred.email)
        if cred.password:
            self.password.setText(cred.password)
        self.remember_check.setChecked(bool(cred.password))

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.account_combo,
            self.email,
            self.password,
            self.remember_check,
            self.login_btn,
            self.cancel_btn,
        ):
            widget.setEnabled(not busy)
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
        self._persist_credential()
        self.accept()

    def _persist_credential(self) -> None:
        """Save (or update) this account for the picker and auto re-login.

        A password is only written when the checkbox is ticked; otherwise the
        email is still remembered so the account can be picked from the combo
        without the secret hitting the disk.
        """
        email = self.email.text().strip()
        if not email:
            return
        try:
            save_credential(
                email,
                self.password.text(),
                self.remember_check.isChecked(),
            )
        except OSError:
            # A failed convenience save must never block a successful login.
            pass

    def _on_login_failure(self, exc: Exception) -> None:
        self._set_busy(False)
        self._show_error(str(exc) or "Login failed. Check your credentials and network.")

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)
        self.error_label.setVisible(True)