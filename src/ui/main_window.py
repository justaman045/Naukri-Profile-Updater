from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow, QTabWidget, QLabel, QMessageBox

from src.core.credentials import credential_for_relogin
from src.core.naukri_client import NaukriManager
from src.core.nope_ri.exceptions.exceptions import NaukriAuthError
from src.core.settings import load_settings
from src.core.worker import ApiWorker
from src.ui.profile_tab import ProfileTab
from src.ui.edit_tab import EditTab
from src.ui.refresh_tab import RefreshTab
from src.ui.settings_tab import SettingsTab
from src.ui.developer_tab import DeveloperTab
from src.ui.about_tab import AboutTab


class MainWindow(QMainWindow):
    # Emitted from the worker thread that hit the dead session, so declaring it
    # as a signal is what marshals the recovery onto the UI thread (a direct
    # callback would run on the worker and touch QThread/dialog state).
    _auth_failure = Signal(object)

    def __init__(self, manager: NaukriManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.settings = load_settings()
        self.setWindowTitle("Naukri Profile Manager")
        self.resize(760, 600)
        self._fetch_worker: ApiWorker | None = None
        self._relogin_worker: ApiWorker | None = None
        self._relogin_attempted = False
        self._relogin_refetch = False
        self._last_profile = None
        self.relogin_requested = False

        self.profile_tab = ProfileTab(manager)
        self.edit_tab = EditTab(manager)
        self.refresh_tab = RefreshTab(manager)
        self.settings_tab = SettingsTab(self.settings)
        self.developer_tab = DeveloperTab(manager, self.settings)
        self.about_tab = AboutTab(manager)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.profile_tab, "Profile")
        self.tabs.addTab(self.edit_tab, "Edit")
        self.tabs.addTab(self.refresh_tab, "Refresh")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.about_tab, "About")
        self._dev_index: int | None = None
        self.setCentralWidget(self.tabs)

        self.status_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.status_lbl)
        self.statusBar().showMessage(f"Connected as {manager.username}")

        self.settings_tab.dev_check.toggled.connect(self._sync_developer_visibility)
        self._build_menu()
        self._sync_developer_visibility()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        # Any operation that ends in a dead session — not just the initial
        # profile load — offers the silent re-login.
        self.manager.set_auth_failure_hook(self._auth_failure.emit)
        self._auth_failure.connect(self._on_auth_failure)
        self.refresh_profile()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        refresh_action = menu.addAction("Refresh Profile")
        refresh_action.triggered.connect(self.refresh_profile)
        logout_action = menu.addAction("Logout")
        logout_action.triggered.connect(self._logout)
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

    def _sync_developer_visibility(self) -> None:
        show = self.settings.show_developer
        if show and self._dev_index is None:
            self._dev_index = self.tabs.addTab(self.developer_tab, "Developer")
        elif not show and self._dev_index is not None:
            self.tabs.removeTab(self._dev_index)
            self._dev_index = None

    def _on_tab_changed(self, index: int) -> None:
        if index == self.tabs.indexOf(self.refresh_tab):
            self.refresh_tab.set_profile(self._last_profile)
        elif index == self.tabs.indexOf(self.developer_tab):
            self.developer_tab.set_profile(self._last_profile)
            # First show pulls the on-file resume; a hidden tab never does.
            self.developer_tab.ensure_resume_loaded()
    def refresh_profile(self) -> None:
        # A second fetch racing the first would have both threads writing the
        # shared `profile_id` cache on the vendored client.
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        self.status_lbl.setText("Loading profile...")
        self._fetch_worker = ApiWorker(self.manager.fetch_profile)
        self._fetch_worker.succeeded.connect(self._on_profile_loaded)
        self._fetch_worker.failed.connect(self._on_profile_error)
        self._fetch_worker.start()

    def _on_auth_failure(self, exc: Exception) -> None:
        """A `NaukriAuthError` escaped any manager call — attempt recovery.

        Runs on the UI thread (see `_auth_failure`). The originating tab still
        reports its own error, which is honest: for a save or a resume refresh
        the user has unsaved input that must not be discarded behind their back.
        Recovery is a bonus here, not a substitute for the message.
        """
        if self._relogin_attempted:
            return
        # `failed_op` is set by the manager right before the hook fires, so this
        # is deterministic: a dead session on the *initial load* should re-run
        # the fetch, whereas one hit by a save/refresh must not, because a
        # profile refresh would overwrite whatever the user has typed.
        self._relogin_refetch = self.manager.failed_op == "fetch_profile"
        self._try_auto_relogin()

    def _on_profile_loaded(self, profile) -> None:
        self._last_profile = profile
        self.profile_tab._populate(profile)
        self.edit_tab.set_profile(profile)
        self.refresh_tab.set_profile(profile)
        self.developer_tab.set_profile(profile)
        self.status_lbl.setText("")

    def _on_profile_error(self, exc: Exception) -> None:
        self.status_lbl.setText("")
        # A dead session is recoverable when the user saved this account's
        # password, so `_on_auth_failure` already started a re-login; stay quiet
        # so the user does not get an error dialog for a session being renewed.
        if isinstance(exc, NaukriAuthError) and self._relogin_attempted:
            return
        self._show_session_error(exc)

    def _try_auto_relogin(self) -> bool:
        """Silently re-authenticate with the stored password for this account.

        Returns True when a re-login was actually started (its result arrives
        asynchronously via `_on_relogin_done` / `_on_relogin_failed`), and False
        when there is nothing to recover with — the caller then shows the
        session-error dialog. `_relogin_attempted` keeps a bad stored password
        (or a server-side auth change) from looping.
        """
        if self._relogin_attempted:
            return False
        if not credential_for_relogin(self.manager.username):
            return False

        self._relogin_attempted = True
        self.statusBar().showMessage("Session expired — signing back in...")
        self._relogin_worker = ApiWorker(self.manager.relogin_with_saved_password)
        self._relogin_worker.succeeded.connect(self._on_relogin_done)
        self._relogin_worker.failed.connect(self._on_relogin_failed)
        self._relogin_worker.start()
        return True

    def _on_relogin_done(self, ok) -> None:
        self.statusBar().showMessage("")
        refetch, self._relogin_refetch = self._relogin_refetch, False
        if not ok:
            self._fallback_to_login(
                "Could not sign back in automatically — the saved password is no "
                "longer accepted. Please log in again."
            )
            return
        if refetch:
            self.refresh_profile()
            return
        # The session was renewed mid-operation. Don't re-run the profile load:
        # it would overwrite whatever the user has typed into the Edit tab.
        QMessageBox.information(
            self,
            "Session Renewed",
            "Your session had expired and has been signed back in.\n\n"
            "Please try again.",
        )

    def _on_relogin_failed(self, exc: Exception) -> None:
        self._fallback_to_login(
            f"Could not sign back in automatically: {exc}\n\nPlease log in again."
        )

    def _fallback_to_login(self, message: str) -> None:
        """Hand the user back to the login dialog through the loop in main().

        `relogin_requested` + close() makes `main()` re-enter its `while True`
        loop; the dead session is cleared so `_resolve_manager()` falls through
        to `LoginDialog`, pre-filled with this account.
        """
        self.manager.logout()
        self.statusBar().showMessage("")
        QMessageBox.information(self, "Session Expired", message)
        self.relogin_requested = True
        self.close()

    def _show_session_error(self, exc: Exception) -> None:
        QMessageBox.warning(
            self,
            "Profile Load Error",
            f"Could not load your profile:\n{exc}\n\nThe session may have expired — use File > Logout and log in again.",
        )

    def _logout(self) -> None:
        self.manager.logout()
        self.statusBar().showMessage("Logged out.")
        QMessageBox.information(
            self, "Logged Out",
            "Your Naukri session has been cleared. Please log in again.",
        )
        # Ask the app to show the login dialog again instead of leaving a
        # manager with no session behind.
        self.relogin_requested = True
        self.close()

    def closeEvent(self, event):
        # Give in-flight requests a moment to settle. The real guarantee that no
        # worker outlives the event loop is `ApiWorker.shutdown()` in main();
        # because every live worker registers itself in that registry, a worker
        # added by a future tab no longer has to be remembered here.
        ApiWorker.shutdown(2000)
        super().closeEvent(event)