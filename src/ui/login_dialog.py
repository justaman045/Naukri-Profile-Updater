import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
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

from src.core import session_store
from src.core.credentials import get_credential, list_credentials, save_credential
from src.core.naukri_client import NaukriCaptchaError, NaukriManager
from src.core.worker import ApiWorker
from src.ui._label_utils import make_wrapping_status_label

ROOT = Path(__file__).resolve().parents[2]

NAUKRI_LOGIN_URL = "https://www.naukri.com/nlogin/login"


class LoginDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, prefill_email: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Login to Naukri")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.manager: NaukriManager | None = None
        self._worker: ApiWorker | None = None
        self._browser_proc: QProcess | None = None

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

        self.error_label = make_wrapping_status_label()
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setVisible(False)

        self.status_label = make_wrapping_status_label()

        # --- Captcha / manual session (shown when browser login is needed) ---
        self.session_input = QLineEdit()
        self.session_input.setPlaceholderText(
            "Paste your nauk_at cookie or Bearer token here"
        )
        self.session_input.setEchoMode(QLineEdit.Password)
        self.session_input.returnPressed.connect(self._on_apply_session)
        self.session_input.setVisible(False)

        self.apply_session_btn = QPushButton("Apply session")
        self.apply_session_btn.clicked.connect(self._on_apply_session)
        self.apply_session_btn.setVisible(False)

        self.session_hint = make_wrapping_status_label()
        self.session_hint.setStyleSheet("color: #6c7a89;")
        self.session_hint.setVisible(False)

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
        layout.addWidget(self.session_input)
        layout.addWidget(self.apply_session_btn)
        layout.addWidget(self.session_hint)
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
        if isinstance(exc, NaukriCaptchaError):
            # Naukri's password login is captcha-gated. Don't dead-end on an
            # error the user cannot act on — open the browser helper instead.
            self._start_browser_login()
            return
        self._show_error(str(exc) or "Login failed. Check your credentials and network.")

    def _start_browser_login(self) -> None:
        """Run ``login_via_browser.py`` when the captcha blocks password login.

        The helper opens a real browser, waits for the user to finish logging in
        (captcha included), verifies the captured cookies, and saves the session
        to ``~/.naukri-profile-update/session.json``. We then adopt that session
        and continue as if the password login had succeeded.

        In frozen (packaged) builds the helper script is not bundled, so we open
        Naukri's login page in the user's default browser and let them paste the
        captured session token back into this dialog.
        """
        if getattr(sys, "frozen", False):
            self._open_browser_for_manual_session()
            return
        script = ROOT / "login_via_browser.py"
        if not script.is_file():
            self._show_error(
                "Naukri requires a captcha, but the browser login helper "
                "(login_via_browser.py) was not found."
            )
            return
        if (
            self._browser_proc is not None
            and self._browser_proc.state() != QProcess.ProcessState.NotRunning
        ):
            return

        args = [str(script), "--channel", "chrome", "--verify"]
        email = self.email.text().strip()
        if email:
            args += ["-e", email]

        proc = QProcess(self)
        proc.setProgram(sys.executable)
        proc.setArguments(args)
        proc.setWorkingDirectory(str(ROOT))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.finished.connect(self._on_browser_login_finished)
        proc.errorOccurred.connect(self._on_browser_login_error)
        self._browser_proc = proc

        self.error_label.setVisible(False)
        self.login_btn.setEnabled(False)
        self.status_label.setText(
            "Naukri requires a captcha — opening a browser. Finish logging in "
            "there (including the captcha) and this window will continue."
        )
        proc.start()

    def _open_browser_for_manual_session(self) -> None:
        """Frozen-build fallback: open Naukri login in the default browser and
        ask the user to paste their session token."""
        self.error_label.setVisible(False)
        self.login_btn.setEnabled(False)

        # Open Naukri login page so the user can authenticate (captcha included).
        QDesktopServices.openUrl(QUrl(NAUKRI_LOGIN_URL))

        self.session_input.setVisible(True)
        self.apply_session_btn.setVisible(True)
        self.session_hint.setVisible(True)
        self.session_hint.setText(
            "Log in to Naukri in the opened browser (complete any captcha), "
            "then copy your ``nauk_at`` cookie or Bearer token and paste it "
            "below. The app will remember you across launches."
        )
        self.status_label.setText(
            "Naukri requires a captcha — please log in in the browser, then "
            "paste your session token below."
        )
        self.session_input.setFocus()
        self.layout().activate()
        self.adjustSize()

    def _parse_session_token(self, raw: str) -> tuple[str, dict[str, str]]:
        """Parse a session token pasted by the user.

        Accepts:
        * a bare token: ``eyJ...``
        * a cookie fragment: ``nauk_at=eyJ...``
        * a raw Cookie header: ``nauk_at=eyJ...; other=value``
        * a Bearer header: ``Bearer eyJ...``

        Returns ``(bearer_token, cookies_dict)``.
        """
        text = raw.strip()
        if not text:
            return "", {}

        # Strip "Bearer " prefix if present.
        if text.lower().startswith("bearer "):
            text = text[7:].strip()

        cookies: dict[str, str] = {}

        # If it looks like a cookie fragment (contains "="), extract nauk_at.
        if "=" in text:
            for part in text.replace("\n", ";").replace("\r", ";").split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                name, value = part.split("=", 1)
                name = name.strip()
                value = value.strip()
                if name.lower() == "nauk_at":
                    cookies[name] = value
                    return value, cookies
            # No nauk_at found; treat the whole thing as the token.
            cookies["nauk_at"] = text
            return text, cookies

        # Bare token.
        cookies["nauk_at"] = text
        return text, cookies

    def _on_apply_session(self) -> None:
        """Apply a session token pasted by the user (frozen-build flow)."""
        raw = self.session_input.text()
        bearer_token, cookies = self._parse_session_token(raw)
        if not bearer_token:
            self._show_error("Please paste a valid session token.")
            return

        self.login_btn.setEnabled(False)
        self.apply_session_btn.setEnabled(False)

        try:
            data = session_store.SessionData(
                username=self.email.text().strip() or "",
                bearer_token=bearer_token,
                cookies=cookies,
            )
            session_store.save_session(data)

            manager = NaukriManager(
                data.username or self.email.text().strip(),
                "",
                use_saved_session=True,
                session_data=data,
            )
            if manager.has_saved_session:
                self.manager = manager
                self.accept()
                return
            self._show_error("Saved session could not be validated.")
        except Exception as exc:  # noqa: BLE001 - surface parse/save errors
            self._show_error(f"Invalid session token: {exc}")
        finally:
            self.login_btn.setEnabled(True)
            self.apply_session_btn.setEnabled(True)

    def _on_browser_login_finished(self, exit_code: int, status) -> None:
        proc = self._browser_proc
        self._browser_proc = None
        output = ""
        if proc is not None:
            output = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace").strip()
            proc.deleteLater()
        self.login_btn.setEnabled(True)

        if status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            data = session_store.load_session()
            if data and data.bearer_token:
                manager = NaukriManager(
                    data.username or self.email.text().strip(),
                    "",
                    use_saved_session=True,
                )
                if manager.has_saved_session:
                    self.manager = manager
                    self.accept()
                    return
            self._show_error(
                "Browser login finished, but no saved Naukri session was found."
            )
            return

        tail = output[-400:].replace("\r", "")
        self._show_error(
            "Browser login failed or was cancelled."
            + (f"\n\n{tail}" if tail else "")
        )

    def _on_browser_login_error(self, error) -> None:
        # `finished` also fires for crash/timeout; only FailedToStart happens
        # before the process ever ran, so it needs its own cleanup.
        if error != QProcess.ProcessError.FailedToStart:
            return
        proc = self._browser_proc
        self._browser_proc = None
        if proc is not None:
            proc.deleteLater()
        self.login_btn.setEnabled(True)
        self._show_error(
            "Could not start the browser login helper. Run it manually: "
            "`python login_via_browser.py --channel chrome --verify`."
        )

    def _stop_browser_login(self) -> None:
        proc = self._browser_proc
        self._browser_proc = None
        if proc is None:
            return
        if proc.state() != QProcess.ProcessState.NotRunning:
            proc.kill()
            proc.waitForFinished(1000)
        proc.deleteLater()

    def reject(self) -> None:
        self._stop_browser_login()
        super().reject()

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)
        self.error_label.setVisible(True)
        # The dialog opens at its compact sizeHint; a multi-line error (e.g. the
        # captcha/cookie helper hint) would otherwise be clipped at the bottom.
        self.layout().activate()
        self.adjustSize()