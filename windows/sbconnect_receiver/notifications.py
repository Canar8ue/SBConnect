"""Route incoming notifications to the right surface.

Interactive notifications (media controls, message replies) go to the
Android-style panel; simple one-way notifications go to native Windows toasts.
If the panel is unavailable (e.g. tkinter missing), interactive notifications
degrade to a plain toast.
"""

from __future__ import annotations

import logging

from .panel import NotificationPanel
from .toasts import ToastService

log = logging.getLogger("sbconnect.notifications")

INTERACTIVE_TYPES = {"media", "message"}


class NotificationService:
    def __init__(
        self,
        on_command=None,
        on_status=None,
        on_code=None,
        on_downloads=None,
        on_quit=None,
        opacity=0.90,
        position="top-right",
        on_settings_save=None,
    ) -> None:
        self.toasts = ToastService()
        self.panel = NotificationPanel(
            on_command=on_command,
            on_status=on_status,
            on_code=on_code,
            on_downloads=on_downloads,
            on_quit=on_quit,
            opacity=opacity,
            position=position,
            on_settings_save=on_settings_save,
        )

    def start(self) -> None:
        self.panel.start()

    def stop(self) -> None:
        self.panel.stop()

    @property
    def panel_available(self) -> bool:
        return self.panel.available

    def show(
        self,
        title: str = "",
        text: str = "",
        app: str = "",
        nid=None,
        type: str = "normal",
        can_reply: bool = False,
        actions=None,
        art: str = "",
    ) -> None:
        type_ = (type or "normal").lower()
        if type_ in INTERACTIVE_TYPES and self.panel.available:
            self.panel.show(
                type_,
                nid,
                app or "",
                title or "",
                text or "",
                bool(can_reply),
                actions or [],
                art=art or "",
            )
            return

        # Native toast for simple notifications (and as a fallback).
        toast_title = (app or title or "SBConnect").strip()
        parts = []
        if title and title.strip() != toast_title:
            parts.append(title.strip())
        if text and text.strip() != title:
            parts.append(text.strip())
        body = "\n".join(parts) if parts else "(no text)"
        self.toasts.show(toast_title, body)
