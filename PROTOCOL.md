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
    "title": "Optional title string",
    "text":  "Optional body text",
    "app":   "Optional app/package name"
  }
  ```
  All three fields are optional and may be empty strings.
- Response: `200` → `{"ok": true}`.

### `POST /file`
Send a file → the receiver saves it to the user's Downloads folder.
- Headers:
  - `X-File-Name: <filename>` (the original file name; may be percent-encoded)
  - `Content-Length: <bytes>`
- Body: raw file bytes.
- Response: `200` → `{"ok": true, "path": "<absolute saved path>"}`.
- On name collision the receiver appends ` (1)`, ` (2)`, etc. before the extension.

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
