"""Toast-button helper for SBConnect.

Windows launches this script (via the registered sbconnect-action:// protocol)
when the user clicks a button on a receiver toast. It parses the URI, prompts
for reply text when needed, and posts the action to the receiver's
/action-click endpoint, which queues it for the phone.
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


def _int_param(query: dict, name: str, default: int) -> int:
    try:
        return int((query.get(name) or [str(default)])[0])
    except ValueError:
        return default


def main() -> None:
    if len(sys.argv) < 2:
        return
    uri = sys.argv[1]
    parts = urllib.parse.urlsplit(uri)
    query = urllib.parse.parse_qs(parts.query)
    cfg = _config()
    port = int(cfg.get("port", 45800))
    code = str(cfg.get("pairing_code", ""))

    nid = _int_param(query, "nid", -1)

    if parts.path == "/reply":
        payload = {"nid": nid, "text": _prompt_reply()}
    else:
        payload = {"nid": nid, "action_id": _int_param(query, "action_id", -1)}

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
