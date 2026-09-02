from PySide6.QtWidgets import QMainWindow, QTabWidget, QLabel, QMessageBox

from src.core.naukri_client import NaukriManager
from src.core.settings import load_settings
from src.core.worker import ApiWorker
from src.ui.profile_tab import ProfileTab
from src.ui.edit_tab import EditTab
from src.ui.refresh_tab import RefreshTab
from src.ui.settings_tab import SettingsTab
from src.ui.developer_tab import DeveloperTab
from src.ui.about_tab import AboutTab


class MainWindow(QMainWindow):
    def __init__(self, manager: NaukriManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.settings = load_settings()
        self.setWindowTitle("Naukri Profile Manager")
        self.resize(760, 600)
        self._fetch_worker: ApiWorker | None = None
        self._last_profile = None

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

    def refresh_profile(self) -> None:
        self.status_lbl.setText("Loading profile...")
        self._fetch_worker = ApiWorker(self.manager.fetch_profile)
        self._fetch_worker.succeeded.connect(self._on_profile_loaded)
        self._fetch_worker.failed.connect(self._on_profile_error)
        self._fetch_worker.start()

    def _on_profile_loaded(self, profile) -> None:
        self._last_profile = profile
        self.profile_tab._populate(profile)
        self.edit_tab.set_profile(profile)
        self.refresh_tab.set_profile(profile)
        self.developer_tab.set_profile(profile)
        self.status_lbl.setText("")

    def _on_profile_error(self, exc: Exception) -> None:
        self.status_lbl.setText("")
        QMessageBox.warning(
            self,
            "Profile Load Error",
            f"Could not load your profile:\n{exc}\n\nThe session may have expired — use File > Logout and log in again.",
        )

    def _logout(self) -> None:
        self.manager.logout()
        self.statusBar().showMessage("Logged out.")
        QMessageBox.information(self, "Logged Out", "Your Naukri session has been cleared.")

    def closeEvent(self, event):
        # Allow in-flight workers to finish; the process will exit naturally.
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.wait(2000)
        super().closeEvent(event)