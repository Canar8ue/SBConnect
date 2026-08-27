# SBConnect — Progress

> **Status:** Working prototype — both sides built; Android APK built via GitHub Actions CI.

## What this project is about

SBConnect links an Android phone to a Windows PC over local Wi-Fi. It has two
parts that talk to each other with one shared protocol:

- **Windows Receiver Agent** (`windows/`) — an ultra-lightweight Python
  system-tray app that listens on the local network, shows incoming phone
  notifications as native Windows toasts, and saves files the phone sends into
  the user's **Downloads** folder.
- **Android Client Agent** (`android/`) — a single-screen Kotlin app that uses a
  Notification Listener + persistent foreground service to capture and stream
  notifications, and can send a picked file over to the PC.

The phone is the HTTP client; the PC is the HTTP server (port `45800` by
default). Every request is authenticated with a shared pairing code.

## Project rules

1. **Update `progress.md` at the end of every change** — every time anything is
   added or modified, this file (including the file tree) must be updated.
2. **`PROTOCOL.md` is the single source of truth** — any protocol change must be
   applied to *both* the Windows receiver and the Android client.
3. **Windows = server, Android = client** — the receiver listens; the phone
   connects and pushes (no inbound connection to the phone).
4. **Keep it lightweight** — minimal dependencies, near-zero idle resource use.
5. **Native, minimal UI** — Windows toast + tray; Android single clean screen.
6. _More rules can be added here as the project evolves._

## Progress so far

- **Protocol** — designed and documented the full HTTP contract in
  `PROTOCOL.md` (`/ping`, `/notify`, `/file`, `/`, pairing-code auth, error
  shape, concurrency).
- **Windows receiver** — built as a small Python package (stdlib HTTP server +
  `pystray`/`Pillow`/`winotify`). **Tested live**: `ping` → `pong`, wrong code →
  `403`, `/notify` fires a real toast, `/file` lands in Downloads, status page
  renders. Pairing code persists across restarts. Config stored at
  `~\.sbconnect\` (chosen to avoid the Microsoft Store Python's AppData
  virtualization).
- **Android client** — complete, compile-grade Kotlin source project (22 files):
  `NotificationRelayService` (filters ongoing/group-summary/self), `RelayService`
  (dataSync foreground service), `RelayClient` (HttpURLConnection singleton),
  `MainActivity` (single screen + permissions + SAF file send), `Prefs`. Not yet
  compiled locally — no JDK/Android SDK on this machine.
- **GitHub push + CI build** — pushed the repo to
  `github.com/Canar8ue/SBConnect` (`main`, commit `e4b7eda`). The GitHub Actions
  workflow (`.github/workflows/build-android.yml`) built the debug APK
  successfully on push (JDK 17 + Gradle 8.7) — the first real compile of the
  Android code passed. The APK was downloaded locally as `SBConnect-debug.apk`
  (~5.8 MB).

## Next steps

- [x] Build the Android APK in CI (GitHub Actions workflow added).
- [x] Download the built APK (saved locally as `SBConnect-debug.apk`).
- [ ] Install the APK on a phone; grant Notification access + battery exemption.
- [ ] Run both sides together on a real phone + PC over Wi-Fi and verify pairing.
- [ ] Allow `python.exe` through Windows Firewall on **Private** networks.
- [ ] Nice-to-haves: auto-start the receiver on login, auto-reconnect on Android,
      mDNS auto-discovery of the PC, TLS instead of plain HTTP.

## File tree

```
SBConnect/
├── progress.md                         # project progress log
├── PROTOCOL.md                         # network protocol spec
├── README.md                           # overview + quickstart
├── .gitignore                          # ignored build artifacts
├── .github/workflows/
│   └── build-android.yml               # CI APK build
│
├── windows/                            # Windows Receiver Agent
│   ├── README.md                       # receiver setup docs
│   ├── requirements.txt                # Python dependencies
│   ├── run.bat                         # double-click launcher
│   └── sbconnect_receiver/
│       ├── __init__.py                 # package metadata
│       ├── __main__.py                 # entry point (tray+server)
│       ├── config.py                   # config + pairing code
│       ├── paths.py                    # Downloads + safe names
│       ├── server.py                   # HTTP receive server
│       └── toasts.py                   # toast notifications
│
└── android/                            # Android Client Agent
    ├── README.md                       # Android build docs
    ├── settings.gradle.kts             # Gradle settings
    ├── build.gradle.kts                # root build script
    ├── gradle.properties               # Gradle JVM flags
    ├── gradle/wrapper/
    │   └── gradle-wrapper.properties   # Gradle version pin
    └── app/
        ├── build.gradle.kts            # app module config
        ├── proguard-rules.pro          # release shrink rules
        └── src/main/
            ├── AndroidManifest.xml     # manifest + permissions
            ├── java/com/sbconnect/client/
            │   ├── MainActivity.kt     # main UI screen
            │   ├── RelayService.kt     # foreground service
            │   ├── NotificationRelayService.kt  # notification listener
            │   ├── RelayClient.kt      # HTTP client
            │   └── Prefs.kt            # settings storage
            └── res/
                ├── layout/activity_main.xml            # screen layout
                ├── values/strings.xml                  # UI strings
                ├── values/colors.xml                   # theme colors
                ├── values/themes.xml                   # app theme
                ├── values/ic_launcher_background.xml   # icon bg color
                ├── drawable/ic_launcher_foreground.xml # icon glyph
                ├── xml/network_security_config.xml     # allow cleartext
                └── mipmap-anydpi-v26/
                    ├── ic_launcher.xml                 # adaptive icon
                    └── ic_launcher_round.xml           # round icon
```
