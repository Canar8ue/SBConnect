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

ACTION_SCHEME = "sbconnect-action://"


def _xml_escape(value: str) -> str:
    """Escape a string for safe use inside a toast XML attribute."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


class ToastService:
    """Queue toasts so HTTP worker threads never block on the toast API."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="toast-worker", daemon=True)
        self._thread.start()

    def show(
        self,
        title: str,
        text: str,
        nid=None,
        can_reply: bool = False,
        actions=None,
    ) -> None:
        self._q.put((title, text, nid, can_reply, actions or []))

    def _run(self) -> None:
        while True:
            title, text, nid, can_reply, actions = self._q.get()
            try:
                self._show(title, text, nid, can_reply, actions)
            except Exception:
                log.exception("Failed to show toast")

    @staticmethod
    def _show(title: str, text: str, nid, can_reply: bool, actions) -> None:
        if not _HAVE_WINOTIFY:
            log.warning("winotify not available; toast skipped")
            return
        title = (title or "").strip()[:120] or "SBConnect"
        text = (text or "").strip()[:600]
        has_buttons = bool(actions) or can_reply
        toast = Notification(
            app_id="SBConnect",
            title=title,
            msg=text,
            duration="long" if has_buttons else "short",
        )
        # Path-based URIs (no '&') so the toast XML stays valid; the helper
        # parses the path segments. Labels are XML-escaped defensively.
        if can_reply:
            toast.add_actions("Reply", f"{ACTION_SCHEME}reply/{nid}")
        for action_id, label in actions:
            if label:
                toast.add_actions(
                    _xml_escape(label), f"{ACTION_SCHEME}click/{nid}/{action_id}"
                )
        toast.show()
