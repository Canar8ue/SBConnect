# SBConnect — Android Client

Android client for **SBConnect**, which links your Android phone to a Windows PC
over the local Wi-Fi network. The phone captures incoming notifications and
relays them to the PC, and can push files to the PC's Downloads folder.

The Windows side runs an HTTP server (default port **45800**); this app is the
HTTP client. See the project root `PROTOCOL.md` for the full wire protocol.

## Prerequisites

- **Android Studio** (recent stable release, e.g. Hedgehog or later).
- **JDK 17** (bundled with recent Android Studio).
- An Android device/emulator running **Android 8.0 (API 26)** or later.
- The Windows receiver running and reachable on the same Wi-Fi network.

> This project does **not** include `gradle-wrapper.jar` (it is a binary and is
> intentionally omitted). Open the folder in Android Studio and it will
> provision the correct Gradle 8.7 distribution automatically. Alternatively,
> if you already have Gradle installed, run `gradle wrapper` from the `android/`
> directory to generate the wrapper JAR first.

## Open / build / run

1. Open **Android Studio** → **Open** → select the `android/` folder.
2. Let Gradle sync finish (it downloads Gradle 8.7, AGP 8.5.2, Kotlin 1.9.24
   and the AndroidX dependencies on first open).
3. Connect a device (or start an emulator) and press **Run**.

The app is a single screen. Toolchain: Kotlin, XML layouts + ViewBinding
(no Compose), `HttpURLConnection` for networking (no networking library).

## Setup steps (first run)

1. **Pairing** — on the Windows receiver, note its IP address and pairing code.
   In the app enter:
   - *PC IP address / hostname* (e.g. `192.168.1.50`)
   - *Port* (`45800` by default)
   - *Pairing code* (shown by the receiver)
   Then tap **Connect / Start**.
2. **Notification access** — tap **Grant notification access** and enable
   **SBConnect** in the "Notification access" list. Without this the app cannot
   read incoming notifications.
3. **POST_NOTIFICATIONS (Android 13+)** — the app requests this at runtime so
   its own foreground notification can be shown; grant it when prompted.
4. **Battery optimization** — tap **Battery optimization** and allow the
   exemption so the relay service isn't killed in the background. (The app
   checks the current state first; if already exempt it just confirms.)

## What each component does

| Component | Purpose |
| --- | --- |
| `MainActivity` | Single-screen UI: configure, start/stop, permissions, send file. |
| `RelayService` | Persistent foreground service; keeps the process + link alive; shows connection state. |
| `NotificationRelayService` | `NotificationListenerService` that captures and relays notifications. |
| `RelayClient` | `HttpURLConnection`-based client for `/ping`, `/notify`, `/file`. |
| `Prefs` | Tiny `SharedPreferences` wrapper for host/port/code. |

## Notes

- Notifications that are ongoing, group summaries, or from SBConnect itself are
  ignored.
- The app uses a fixed-size `ExecutorService` for all network I/O and delivers
  results back on the main thread; it never blocks the UI thread.
- Cleartext HTTP is allowed (required because the local receiver has no TLS);
  see `res/xml/network_security_config.xml`.
