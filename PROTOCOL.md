# SBConnect Protocol — v1

The Windows receiver is the **HTTP server**; the Android app is the **HTTP client**.
Both communicate over the local Wi-Fi network using plain HTTP/1.1 (TCP).

- Default port: **45800** (configurable on the receiver).
- Receiver binds to `0.0.0.0` so the phone can reach it on any local interface.

## Authentication

Every request (except `GET /`) must carry the shared pairing code:

```
X-SB-Connect-Code: <pairing code>
```

- The receiver generates a random pairing code on first run and stores it in its config.
- If the receiver has a code configured and a request's code is missing or wrong → `403`.
- If the receiver has an empty code (auth disabled) → requests are accepted without a code.

## Endpoints

### `GET /ping`
Connectivity / pairing check.
- Response: `200` with body `pong` (text/plain).

### `POST /notify`
Relay a phone notification → the receiver shows a native Windows toast.
- `Content-Type: application/json`
- Body (JSON):
  ```json
  {
    "title":     "Optional title string",
    "text":      "Optional body text",
    "app":       "Optional app/package name",
    "nid":       3,
    "type":      "media | message | normal",
    "actions":   [ {"id": 0, "label": "Pause"}, {"id": 1, "label": "Next"} ],
    "can_reply": true
  }
  ```
  `title`, `text` and `app` are optional and may be empty strings. `nid` is a
  stable numeric id the phone uses to route command clicks back to the right
  notification (only needed when `actions` or `can_reply` are set). `actions`
  lists media buttons as `{id, label}` pairs; `can_reply` is true when the app
  exposes a RemoteInput reply action (Google Messages, WhatsApp, Telegram, ...).
- Response: `200` → `{"ok": true}`.

### `POST /file`
Send a file → the receiver saves it to the user's Downloads folder.
- Headers:
  - `X-File-Name: <filename>` (the original file name; may be percent-encoded)
  - `Content-Length: <bytes>`
- Body: raw file bytes.
- Response: `200` → `{"ok": true, "path": "<absolute saved path>"}`.
- On name collision the receiver appends ` (1)`, ` (2)`, etc. before the extension.

### `GET /commands`
PC → phone command channel (long-poll). The phone keeps one of these open at
all times; when a toast button is clicked the receiver returns a command
immediately, otherwise it holds the connection for ~30s and returns an empty
result, after which the phone re-polls.
- Response: `200` → `{"command": {...} | null}`
- Command payloads (sent to the phone):
  ```json
  // a media button was clicked on the PC
  {"type": "action", "nid": 3, "action_id": 0}
  // a reply was sent from the PC
  {"type": "reply",  "nid": 4, "text": "on my way"}
  ```

### `POST /action-click`
Called by the Windows toast-button helper (the registered `sbconnect-action://`
protocol) when the user clicks a button on a receiver toast. Queues a command
for the phone's next `/commands` poll.
- `Content-Type: application/json`
- Body (JSON): a body with a `text` field becomes a `reply` command, otherwise
  it becomes an `action` command:
  ```json
  {"nid": 3, "action_id": 0}
  {"nid": 4, "text": "on my way"}
  ```
- Response: `200` → `{"ok": true}`.

### `GET /`
Human-readable status page (no auth required) — convenient for browser testing.
Shows server name, uptime, and counters for notifications and files received.

## Errors

Non-success responses return JSON with the right HTTP status:

```json
{ "ok": false, "error": "message" }
```

- `403` — bad/missing pairing code
- `405` — wrong method
- `400` — malformed request
- `500` — server error

## Concurrency

The receiver must handle multiple simultaneous requests (threaded server).
File uploads are streamed to disk in chunks rather than buffered fully in memory.
The `/commands` long-poll holds one connection open for up to 30s; other
requests are served by other threads while it waits.
