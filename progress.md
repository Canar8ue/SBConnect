# SBConnect — Progress

> **Status:** Working prototype — revamped with authentic Android 14/15 Quick Settings & Material You design, real song album art support, and Material 3 Android settings UI.

## What this project is about

SBConnect links an Android phone to a Windows PC over local Wi-Fi. It has two
parts that talk to each other with one shared protocol:

- **Windows Receiver Agent** (`windows/`) — an ultra-lightweight Python
  system-tray app that listens on the local network, shows incoming phone
  notifications as native Windows toasts, provides a top-corner **Android Quick Settings shade**
  with full media controls, real song album artwork, quick toggles, and inline message replies,
  and saves files the phone sends into the user's **Downloads** folder.
- **Android Client Agent** (`android/`) — a Material 3 Kotlin app that uses a
  Notification Listener + persistent foreground service to capture and stream
  notifications (with album art extraction), and can send picked files to the PC.

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
- **Android client** — complete, compile-grade Kotlin source project:
  `NotificationRelayService` (filters ongoing/group-summary/self), `RelayService`
  (dataSync foreground service), `RelayClient` (HttpURLConnection singleton),
  `MainActivity` (single screen + permissions + SAF file send), `Prefs`.
- **GitHub push + CI build** — pushed the repo to
  `github.com/Canar8ue/SBConnect` (`main`, commit `e4b7eda`). The GitHub Actions
  workflow (`.github/workflows/build-android.yml`) built the debug APK
  successfully on push (JDK 17 + Gradle 8.7).
- **Notification relay hardening** — fixed RCS/chat notifications being missed:
  the listener self-configures from saved settings, and text extraction handles
  Messaging-style (chat/SMS/RCS), Inbox-style, and text-lines notifications.
- **Media controls + replies** — added PC→phone command channel (long-poll
  on `/commands`): media notifications arrive with play/pause/next buttons,
  and message notifications support inline reply from the PC.
- **Top-corner control-center shade** — custom Tkinter panel pinned to the
  top edge with gesture grabber pill, clock, utility tiles, and slide-in animations.
- **Android Quick Settings & Material You UI Revamp + Album Art Display**:
  - **Windows Quick Settings Shade (`panel.py`)**: Redesigned to look like modern
    Android 14/15 Quick Settings & Notification shade:
    - **Header**: Android digital clock (`20pt bold`), date (`Mon, Aug 31`), device status chip (`● SBConnect` with active green pulse dot), and gesture grabber handle.
    - **2-Column Quick Settings Pill Tiles**: Material You rounded pill toggles (`radius 20px`, height `54px`) for Receiver Status (`📶`), Pairing Code (`🔑`), Downloads (`📥`), and Settings (`⚙`).
    - **Android 14/15 Media Player Widget (Now Playing)**: Real album art decoding (PIL Lanczos scaling + antialiased rounded corner mask `radius 18px`), app badge (`♫ Spotify`), track title, artist name, authentic Android scrubber track with progress fill & thumb, circular secondary controls (`⏮`, `⏭`), and centerpiece circular Material You FAB play/pause button (`50x50px`, `#A8C7FA`).
    - **Material 3 Message Cards**: App icon badges, timestamp (`· now`), sender bold title, message text, and Material You inline reply input with active Send pill.
  - **Real Song Album Art Protocol & Pipeline**:
    - `NotificationRelayService.kt` extracts album artwork from `largeIcon`, `EXTRA_LARGE_ICON`, or `EXTRA_PICTURE`, scales to max 256x256, compresses to JPEG Base64, and attaches to `/notify`.
    - `PROTOCOL.md` and `server.py` updated with `MAX_NOTIFY_BYTES = 512KB` and `art` payload field.
  - **Android Settings UI Screen (`activity_main.xml`, `themes.xml`, `colors.xml`, `MainActivity.kt`)**:
    - Authentic Material 3 Android Settings design with headline header, Hero Connection Status Card with live status dot, rounded Material 3 text inputs (`16dp` corner radius), Grouped Permission Cards with action chips, and Quick File Transfer row.

## Next steps

- [ ] Push changes to GitHub repository to trigger the CI APK build.
- [ ] Download updated `SBConnect-debug.apk` with the Material 3 UI and album art relaying.
- [ ] Test playing music on phone (Spotify / YT Music) and verify album art & media controls on PC.
- [ ] Test replying to text messages from the PC Quick Settings shade.
- [ ] Allow `python.exe` through Windows Firewall on **Private** networks.

## File tree

```
SBConnect/
├── progress.md                         # project progress log
├── PROTOCOL.md                         # network protocol spec (with art support)
├── README.md                           # overview + quickstart
├── .gitignore                          # ignored build artifacts
├── .github/workflows/
│   └── build-android.yml               # CI APK build
│
├── windows/                            # Windows Receiver Agent
│   ├── README.md                       # receiver setup docs
│   ├── requirements.txt                # Python dependencies (pystray, Pillow, winotify)
│   ├── run.bat                         # double-click launcher
│   └── sbconnect_receiver/
│       ├── __init__.py                 # package metadata
│       ├── __main__.py                 # entry point (tray+server)
│       ├── config.py                   # config + pairing code
│       ├── notifications.py            # panel-vs-toast router (with art forwarding)
│       ├── panel.py                    # Android Quick Settings shade (Material You + album art)
│       ├── paths.py                    # Downloads + safe names
│       ├── server.py                   # HTTP receive server (512KB notify buffer)
│       └── toasts.py                   # native toast notifications
│
└── android/                            # Android Client Agent
    ├── README.md                       # Android build docs
    ├── settings.gradle.kts             # Gradle settings
    ├── build.gradle.kts                # root build script
    ├── gradle.properties               # Gradle JVM flags
    ├── gradle/wrapper/
    │   └── gradle-wrapper.properties   # Gradle version pin
    ├── keystore/
    │   └── debug.keystore              # pinned debug signing key
    └── app/
        ├── build.gradle.kts            # app module config
        ├── proguard-rules.pro          # release shrink rules
        └── src/main/
            ├── AndroidManifest.xml     # manifest + permissions
            ├── java/com/sbconnect/client/
            │   ├── MainActivity.kt     # Material 3 settings UI controller
            │   ├── RelayService.kt     # foreground service
            │   ├── NotificationRelayService.kt  # notification listener + album art extraction
            │   ├── RelayClient.kt      # HTTP client (art support)
            │   ├── ActionStore.kt      # action storage/execution
            │   └── Prefs.kt            # settings storage
            └── res/
                ├── layout/activity_main.xml            # Android Settings page layout
                ├── values/strings.xml                  # UI strings
                ├── values/colors.xml                   # Material You color tokens
                ├── values/themes.xml                   # Material 3 settings theme
                ├── values/ic_launcher_background.xml   # icon bg color
                ├── drawable/ic_launcher_foreground.xml # icon glyph
                ├── xml/network_security_config.xml     # allow cleartext
                └── mipmap-anydpi-v26/
                    ├── ic_launcher.xml                 # adaptive icon
                    └── ic_launcher_round.xml           # round icon
```
