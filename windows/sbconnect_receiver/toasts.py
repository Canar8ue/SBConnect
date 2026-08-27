"""Native Windows toast notifications, serialized on a single worker thread."""

from __future__ import annotations

import logging
import queue
import threading

log = logging.getLogger("sbconnect.toasts")

try:
    from winotify import Notification

    _HAVE_WINOTIFY = True
except Exception:  # pragma: no cover - degraded mode if dependency missing
    _HAVE_WINOTIFY = False


class ToastService:
    """Queue toasts so HTTP worker threads never block on the toast API."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="toast-worker", daemon=True)
        self._thread.start()

    def show(self, title: str, text: str) -> None:
        self._q.put((title, text))

    def _run(self) -> None:
        while True:
            title, text = self._q.get()
            try:
                self._show(title, text)
            except Exception:
                log.exception("Failed to show toast")

    @staticmethod
    def _show(title: str, text: str) -> None:
        if not _HAVE_WINOTIFY:
            log.warning("winotify not available; toast skipped")
            return
        title = (title or "").strip()[:120] or "SBConnect"
        text = (text or "").strip()[:600]
        toast = Notification(app_id="SBConnect", title=title, msg=text, duration="short")
        toast.show()
