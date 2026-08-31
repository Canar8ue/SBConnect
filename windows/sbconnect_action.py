"""Toast-button helper for SBConnect.

Windows launches this script (via the registered sbconnect-action:// protocol)
when the user clicks a button on a receiver toast. It parses the URI, prompts
for reply text when needed, and posts the action to the receiver's
/action-click endpoint, which queues it for the phone.

URIs (path-based so the toast XML never contains a raw '&'):
  sbconnect-action://click/<nid>/<action_id>   media button
  sbconnect-action://reply/<nid>               reply to a message
"""

import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def _config() -> dict:
    try:
        return json.loads(
            (Path.home() / ".sbconnect" / "config.json").read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def _prompt_reply() -> str:
    """Ask the user for reply text (tkinter first, PowerShell as fallback)."""
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        value = simpledialog.askstring("SBConnect Reply", "Type your reply:", parent=root)
        root.destroy()
        return (value or "").strip()
    except Exception:
        pass
    try:
        script = (
            "Add-Type -AssemblyName Microsoft.VisualBasic; "
            '[Microsoft.VisualBasic.Interaction]::InputBox("Type your reply:", "SBConnect Reply", "")'
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def main() -> None:
    if len(sys.argv) < 2:
        return
    uri = sys.argv[1]
    parts = urllib.parse.urlsplit(uri)
    segments = [s for s in parts.path.split("/") if s]
    cfg = _config()
    port = int(cfg.get("port", 45800))
    code = str(cfg.get("pairing_code", ""))

    def seg_int(index: int, default: int) -> int:
        try:
            return int(segments[index])
        except (IndexError, ValueError):
            return default

    if segments and segments[0] == "reply":
        payload = {"nid": seg_int(1, -1), "text": _prompt_reply()}
    else:
        payload = {"nid": seg_int(1, -1), "action_id": seg_int(2, -1)}

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/action-click",
        data=body,
        headers={"Content-Type": "application/json", "X-SB-Connect-Code": code},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=5)
    except Exception:
        pass  # receiver may be mid-restart; the click is dropped


if __name__ == "__main__":
    main()
