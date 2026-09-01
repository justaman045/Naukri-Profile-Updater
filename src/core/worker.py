from typing import Callable

from PySide6.QtCore import QThread, Signal, QObject


class ApiWorker(QThread):
    """Runs a blocking callable (login, fetch, update, upload) off the UI
    thread and emits the result or error via Qt signals."""

    succeeded = Signal(object)
    failed = Signal(object)  # carries the Exception instance

    def __init__(self, func: Callable[[], object], *, parent: QObject | None = None):
        super().__init__(parent)
        self.func = func
        self._error: Exception | None = None

    def run(self):
        try:
            result = self.func()
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all for UI
            self._error = exc
            self.failed.emit(exc)
        else:
            self.succeeded.emit(result)