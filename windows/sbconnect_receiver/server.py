"""HTTP server that receives notifications and files from the Android client."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .paths import unique_path

log = logging.getLogger("sbconnect.server")

MAX_NOTIFY_BYTES = 64 * 1024
CHUNK = 64 * 1024


class App:
    """Runtime state shared between the server and the tray UI."""

    def __init__(self, config, toast_service, downloads: Path) -> None:
        self.config = config
        self.toast_service = toast_service
        self.downloads = downloads
        self.started_at = datetime.now()
        self.notifications = 0
        self.files = 0


class SBConnectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SBConnect/0.1"

    # ---- helpers -------------------------------------------------------
    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def address_string(self) -> str:  # skip reverse-DNS lookups
        return self.client_address[0]

    def _authorized(self) -> bool:
        code = self.app.config.pairing_code
        if not code:
            return True
        return self.headers.get("X-SB-Connect-Code") == code

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject(self, status: int, message: str) -> None:
        self._send_json(status, {"ok": False, "error": message})

    def log_message(self, fmt, *args) -> None:
        log.info("%s - %s", self.client_address[0], fmt % args)

    # ---- routes --------------------------------------------------------
    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            return self._serve_status()
        if not self._authorized():
            return self._reject(403, "invalid pairing code")
        if path == "/ping":
            body = b"pong"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._reject(404, "not found")

    def do_POST(self) -> None:
        if not self._authorized():
            return self._reject(403, "invalid pairing code")
        path = urllib.parse.urlsplit(self.path).path
        if path == "/notify":
            self._handle_notify()
        elif path == "/file":
            self._handle_file()
        else:
            self._reject(404, "not found")

    # ---- handlers ------------------------------------------------------
    def _handle_notify(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_NOTIFY_BYTES:
            return self._reject(400, "bad content length")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._reject(400, "invalid json")

        title = str(data.get("title") or "")
        text = str(data.get("text") or "")

        if title or text:
            self.app.toast_service.show(title, text)
        self.app.notifications += 1
        self._send_json(200, {"ok": True})

    def _handle_file(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._reject(400, "missing content length")

        raw_name = self.headers.get("X-File-Name") or "received_file"
        try:
            filename = urllib.parse.unquote(raw_name)
        except Exception:
            filename = raw_name
        filename = Path(filename).name or "received_file"

        target = unique_path(self.app.downloads, filename)
        remaining = length
        try:
            with target.open("wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except Exception as exc:
            log.exception("File write failed")
            return self._reject(500, f"write failed: {exc}")

        self.app.files += 1
        self._send_json(200, {"ok": True, "path": str(target)})

    # ---- status page ---------------------------------------------------
    def _serve_status(self) -> None:
        a = self.app
        uptime = int(time.time() - a.started_at.timestamp())
        code = a.config.pairing_code or "(auth disabled)"
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>SBConnect</title></head>"
            "<body style='font-family:Segoe UI,sans-serif;margin:2rem'>"
            "<h1>SBConnect Receiver</h1>"
            f"<p>Listening on port {a.config.port}.</p><ul>"
            f"<li>Pairing code: <strong>{code}</strong></li>"
            f"<li>Uptime: {uptime}s</li>"
            f"<li>Notifications received: {a.notifications}</li>"
            f"<li>Files received: {a.files}</li>"
            f"<li>Downloads folder: {a.downloads}</li>"
            "</ul></body></html>"
        )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SBConnectServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, app: App) -> None:
        self.app = app
        super().__init__(addr, SBConnectHandler)
