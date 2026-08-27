# SBConnect

Link your Android phone to your Windows PC over local Wi-Fi. Phone notifications
appear as native Windows toasts, and files you share from the phone drop
straight into your PC's **Downloads** folder.

Two sides, one shared protocol (see [`PROTOCOL.md`](PROTOCOL.md)):

- **`windows/`** — the **Receiver Agent**: an ultra-lightweight Python system-tray
  app that listens on the local network, shows toasts, and saves received files.
- **`android/`** — the **Client Agent**: a single-screen Kotlin app with a
  Notification Listener + persistent foreground service that streams
  notifications and sends files to the PC.

## Quick start

1. **On the PC** (receiver):
   ```bat
   cd windows
   python -m pip install -r requirements.txt
   run.bat
   ```
   A toast shows the **pairing code** (also in the tray menu and on the status
   page at `http://localhost:45800/`).

2. **Find the PC's IP address**: `ipconfig` → IPv4 Address (e.g. `192.168.1.20`).

3. **On the phone** (client): build and install the app (see
   [`android/README.md`](android/README.md)), grant **Notification access**,
   enter the PC's IP, port `45800`, and the pairing code, then tap **Connect**.

4. Done — phone notifications now appear as Windows toasts, and **Send file**
   pushes a file into the PC's Downloads folder.

## How it works

`windows/` runs a tiny threaded HTTP server on port `45800` (configurable). The
Android app is the HTTP client and posts JSON notifications (`/notify`) and raw
file bytes (`/file`). A shared pairing code (header `X-SB-Connect-Code`)
authenticates every request. Full contract in [`PROTOCOL.md`](PROTOCOL.md).
