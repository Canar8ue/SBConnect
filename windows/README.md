# SBConnect — Windows Receiver Agent

Ultra-lightweight Windows tray app that turns your PC into a receiver for your
Android phone. It listens on the local network, shows incoming phone
notifications as native Windows toasts, and saves any files your phone sends
straight into your **Downloads** folder.

## Features

- **Notifications** — phone notifications appear as native Windows toasts
  (titled with the source app).
- **Media controls** — while music plays on your phone, the toast shows the
  track with **Previous / Play / Pause / Next** buttons that control the phone
  remotely (works with Spotify, YouTube Music, etc.).
- **Reply to texts** — messages from apps with a reply action (Google Messages,
  WhatsApp, Telegram, ...) show a **Reply** button; clicking it opens a text box
  on the PC and the reply is sent from your phone.
- **File drop** — files shared from the phone land in your Downloads folder.

Media/reply buttons work over a lightweight long-poll channel the phone keeps
open — button clicks are delivered in well under a second.

## Stack

- **Python 3** (stdlib HTTP server — no web framework).
- **pystray** + **Pillow** — system-tray icon and menu.
- **winotify** — native Windows 10/11 toast notifications.

Only three third-party dependencies; everything else is the Python standard library.

## Install & run

```bat
cd windows
python -m pip install -r requirements.txt
python -m sbconnect_receiver
```

Or just double-click `run.bat`.

Useful options:

```bat
python -m sbconnect_receiver --port 45800   # change port
python -m sbconnect_receiver --no-tray      # headless (for testing)
python -m sbconnect_receiver --debug        # verbose logging
```

## Pairing with your phone

1. Start the receiver. A toast shows the **pairing code** (also in the tray menu:
   *Show pairing code*, and on the status page).
2. Find your PC's local IP (`ipconfig` → IPv4 Address, e.g. `192.168.1.20`).
3. In the Android app, enter that IP, the port (default `45800`), and the pairing code.

## Where things live

- Config + pairing code: `C:\Users\<you>\.sbconnect\config.json`
- Log: `C:\Users\<you>\.sbconnect\receiver.log`
- Received files: your real Downloads folder (auto-detected, including OneDrive
  redirection).

The config lives in the profile root (not `%APPDATA%`) because the Microsoft
Store Python silently redirects AppData writes — using `~\.sbconnect` keeps the
config and log visible and consistent across Python installs.

## Notes

- RAM target is ~20–30 MB. Python's baseline plus the tray/toast libs typically
  lands in that range; the process stays idle until a request arrives.
- The receiver binds to `0.0.0.0`, so make sure Windows Firewall allows Python
  on the local network (Windows will prompt on first run — allow it on
  *Private* networks).
- See `../PROTOCOL.md` for the exact HTTP endpoints the phone calls.
