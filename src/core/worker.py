import logging
import time
from typing import Callable

from PySide6.QtCore import QThread, Signal, QObject

logger = logging.getLogger(__name__)

# Every live worker registers here for as long as it runs. A `QThread` that is
# garbage-collected while `run()` is still executing makes CPython destroy the
# underlying C++ object, which Qt reports as
#   "QThread: Destroyed while thread '<name>' is still running"
# and then calls abort() — an uncatchable SIGABRT that kills the process
# (exit 134) with no traceback. Callers reassign their worker attribute
# (e.g. clicking Refresh twice), so dropping the last reference mid-run is the
# normal case, not an edge case. The registry makes that impossible.
_ACTIVE: set["ApiWorker"] = set()


class ApiWorker(QThread):
    """Runs a blocking callable (login, fetch, update, upload) off the UI
    thread and emits the result or error via Qt signals."""

    succeeded = Signal(object)
    failed = Signal(object)  # carries the Exception instance

    def __init__(self, func: Callable[[], object], *, parent: QObject | None = None):
        super().__init__(parent)
        self.func = func
        self._error: Exception | None = None
        _ACTIVE.add(self)
        self.finished.connect(self._on_finished)

    def _on_finished(self) -> None:
        """Release the registry's reference once the thread is done.

        Safe against destroying a running QThread because a QThread object
        lives in the thread that created it: `finished` is emitted from the
        worker thread, so the default auto-connection queues this slot onto the
        creating (UI) thread's event loop, which can only run after
        `QThreadPrivate::finish()` has returned. If no event loop is running
        the slot never fires and the worker simply stays registered until
        `shutdown()` reaps it — still no crash.
        """
        _ACTIVE.discard(self)

    def run(self):
        try:
            result = self.func()
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all for UI
            self._error = exc
            self.failed.emit(exc)
        else:
            self.succeeded.emit(result)

    @classmethod
    def shutdown(cls, timeout_ms: int = 10_000) -> bool:
        """Drain every in-flight worker before Qt is torn down.

        Called after `app.exec()` returns. Without this, a still-running worker
        is destroyed during interpreter finalization and aborts the process.
        Waits up to `timeout_ms` total, then falls back to `terminate()` — the
        retry helper can sleep for 60s between attempts, so a bounded wait
        alone cannot guarantee a clean exit and the alternative is the SIGABRT
        this function exists to prevent. `quit()` is useless here: `run()` is
        blocked in a network read and does not pump an event loop.

        Returns True when nothing was left running.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        for worker in list(_ACTIVE):
            if not worker.isRunning():
                _ACTIVE.discard(worker)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.wait(int(remaining * 1000))

        stuck = [w for w in _ACTIVE if w.isRunning()]
        if not stuck:
            return True

        for worker in stuck:
            logger.error(
                "ApiWorker still busy after %d ms; terminating", timeout_ms
            )
            worker.terminate()
            worker.wait(500)

        stuck = [w for w in _ACTIVE if w.isRunning()]
        if stuck:
            logger.error("%d ApiWorker(s) could not be stopped", len(stuck))
        return not stuck
