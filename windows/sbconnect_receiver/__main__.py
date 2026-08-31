"""Entry point: starts the HTTP server and the system-tray icon."""

from __future__ import annotations

import argparse
import logging
import os
import threading
import webbrowser

from .config import Config, config_dir
from .notifications import NotificationService
from .paths import downloads_dir
from .server import App, SBConnectServer

log = logging.getLogger("sbconnect")


def setup_logging(level: int = logging.INFO) -> None:
    log_file = config_dir() / "receiver.log"
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def make_tray_icon():
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([3, 3, 61, 61], radius=14, fill=(0, 120, 212, 255))
    try:
        font = ImageFont.load_default(size=34)
    except TypeError:  # older Pillow
        font = ImageFont.load_default()
    d.text((13, 13), "SB", fill=(255, 255, 255, 255), font=font)
    return img


def _open_status(app: App) -> None:
    webbrowser.open(f"http://localhost:{app.config.port}/")


def _show_code(app: App) -> None:
    app.notification_service.show("SBConnect pairing code", app.config.pairing_code)


def _open_downloads(app: App) -> None:
    os.startfile(str(app.downloads))  # type: ignore[attr-defined]


def _quit(app: App) -> None:
    """Stop the tray icon (if running) and signal the main loop to exit."""
    icon = getattr(app, "tray_icon", None)
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass
    app.quit_event.set()


def _save_panel_settings(config, opacity, position) -> None:
    config.panel_opacity = opacity
    config.panel_position = position
    config.save()


def run_tray(app: App) -> None:
    import pystray

    icon = pystray.Icon(
        "SBConnect",
        make_tray_icon(),
        "SBConnect Receiver",
        menu=pystray.Menu(
            pystray.MenuItem("Open status page", lambda icon, item: _open_status(app)),
            pystray.MenuItem("Show pairing code", lambda icon, item: _show_code(app)),
            pystray.MenuItem(
                "Open Downloads folder", lambda icon, item: _open_downloads(app)
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: icon.stop()),
        ),
    )
    app.tray_icon = icon
    icon.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="SBConnect Windows Receiver")
    parser.add_argument("--port", type=int, default=None, help="override port")
    parser.add_argument("--host", default=None, help="override bind address")
    parser.add_argument("--no-tray", action="store_true", help="run headless (no tray icon)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.debug else logging.INFO)
    log = logging.getLogger("sbconnect")

    config = Config.load()
    if args.port:
        config.port = args.port
    if args.host:
        config.host = args.host
    config.save()

    downloads = downloads_dir()
    app = App(config, None, downloads)

    # The panel needs to enqueue commands for the phone and reach the tray
    # actions, so wire it to the app and then attach the service.
    notifications = NotificationService(
        on_command=app.command_queue.put,
        on_status=lambda: _open_status(app),
        on_code=lambda: _show_code(app),
        on_downloads=lambda: _open_downloads(app),
        on_quit=lambda: _quit(app),
        opacity=config.panel_opacity,
        position=config.panel_position,
        on_settings_save=lambda opacity, position: _save_panel_settings(
            config, opacity, position
        ),
    )
    app.notification_service = notifications
    notifications.start()

    server = SBConnectServer((config.host, config.port), app)
    thread = threading.Thread(target=server.serve_forever, name="http-server", daemon=True)
    thread.start()

    log.info("Listening on %s:%s", config.host, config.port)
    log.info("Pairing code: %s", config.pairing_code)
    log.info("Downloads folder: %s", downloads)

    if args.no_tray:
        log.info("Running headless. Press Ctrl+C to stop.")
        try:
            app.quit_event.wait()
        except KeyboardInterrupt:
            pass
    else:
        notifications.show(
            "SBConnect is ready",
            f"Pairing code: {config.pairing_code}\nPort: {config.port}",
        )
        run_tray(app)

    server.shutdown()
    server.server_close()
    notifications.stop()


if __name__ == "__main__":
    main()
