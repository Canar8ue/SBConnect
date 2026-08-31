"""Android Quick Settings & Control Center shade (Material You / Material 3).

A sleek, borderless, always-on-top window pinned to the user's chosen corner.
When idle it collapses to an Android-style gesture grabber pill; hover and scroll
with two fingers (or click it) and the full shade drops down, styled like modern
Android 14/15 Quick Settings:

- Top Header: Android digital clock + date, device status chip, and gesture handle
- Quick Settings Tiles: 2-column Material You pill toggles (Status, Pairing Code, Files, Settings)
- "Now Playing" Media Card: Full Android 14/15 media output player with real album art,
  app badge, track title, artist, seek scrubber visual, and Material You playback controls
- Message Cards: Material 3 notification containers with app icon, sender, text, and inline reply
- Utility / Power action for quick exit

Simple one-way notifications are surfaced via native Windows toasts.
This module runs on its own thread; HTTP workers hand work to it through a thread-safe queue.
"""

from __future__ import annotations

import base64
import io
import logging
import queue
import threading
import time

log = logging.getLogger("sbconnect.panel")

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from PIL import Image, ImageDraw, ImageTk

    _HAVE_TK = True
except Exception:  # pragma: no cover - tkinter/Pillow ship with standard environment
    _HAVE_TK = False

# ---- Material You Dark Palette ---------------------------------------
MAGIC = "#FF00FE"           # Windows transparency key (reserved)
SURFACE = "#121316"         # Android quick settings root surface
SURFACE_OUTLINE = "#2B2D33" # Outer panel border
CARD = "#1E2026"            # Material You surface container
CARD_HOVER = "#272930"      # Elevated card hover state
CARD_OUTLINE = "#2D3038"    # Subtle card border
TILE_BG = "#26282E"         # Quick Settings pill toggle background
TILE_HOVER = "#32353D"      # Quick Settings pill hover
TILE_ACTIVE = "#A8C7FA"     # Active toggle / Material You primary
TILE_ACTIVE_FG = "#041E49"  # On-primary dark text
FG = "#F2F2F7"              # High emphasis text
FG_MUTED = "#9C9DA6"        # Medium emphasis text / subtitles
FG_DIM = "#6E7079"          # Low emphasis / hints
ACCENT = "#A8C7FA"          # Material You dynamic soft blue
ACCENT_GREEN = "#80DCA0"    # Material You connection / success green
GRABBER = "#4E5058"         # Gesture bar / handle
GRABBER_HOVER = "#8E909A"   # Gesture bar hover

ART_GRADIENTS = [
    ("#E57373", "#C2185B"),
    ("#BA68C8", "#512DA8"),
    ("#7986CB", "#1976D2"),
    ("#4FC3F7", "#00838F"),
    ("#4DB6AC", "#004D40"),
    ("#81C784", "#2E7D32"),
    ("#FFB74D", "#E65100"),
    ("#FF8A65", "#D84315"),
]

# ---- Geometry ---------------------------------------------------------
WIDTH = 400
RADIUS = 28
MARGIN = 14
CARD_W = WIDTH - 2 * MARGIN
PAD = 14
INNER_W = CARD_W - 2 * PAD

CARD_RADIUS = 24
TILE_RADIUS = 20
ART_RADIUS = 18

KNOB_W = 96
KNOB_H = 18
KNOB_PILL_W = 56
KNOB_PILL_H = 6

MIN_OPACITY = 0.30
MAX_OPACITY = 1.0
EDGE_MARGIN = 150
MAX_MESSAGES = 5
_SPI_GETWORKAREA = 0x0030


def _work_area() -> tuple[int, int, int, int]:
    """Primary monitor work area (screen minus taskbar) as (l, t, r, b)."""
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return 0, 0, 1920, 1040


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a smooth rounded rectangle on a Tkinter canvas."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return canvas.create_polygon(
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        smooth=True, **kw,
    )


def _map_media_actions(actions) -> dict:
    """Map media action labels to {play, pause, prev, next} action ids."""
    m: dict = {}
    for action_id, label in actions:
        l = (label or "").lower()
        if "pause" in l:
            m.setdefault("pause", action_id)
        elif "play" in l or "resume" in l:
            m.setdefault("play", action_id)
        elif "previous" in l or "prev" in l or "rewind" in l or "back" in l:
            m.setdefault("prev", action_id)
        elif "next" in l or "forward" in l or "skip" in l:
            m.setdefault("next", action_id)
    return m


def _process_album_art(art_b64: str, size: int = 76, radius: int = 18) -> ImageTk.PhotoImage | None:
    """Decode, crop to square, resize and round corners of album art via PIL."""
    if not art_b64:
        return None
    try:
        raw = base64.b64decode(art_b64)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")

        # Center crop to square if needed
        w, h = img.size
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))

        # High quality resize
        img = img.resize((size, size), Image.Resampling.LANCZOS)

        # Anti-aliased rounded mask
        scale = 4
        mask = Image.new("L", (size * scale, size * scale), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, size * scale, size * scale), radius=radius * scale, fill=255)
        mask = mask.resize((size, size), Image.Resampling.LANCZOS)

        img.putalpha(mask)
        return ImageTk.PhotoImage(img)
    except Exception as exc:
        log.warning("Failed to render album artwork: %s", exc)
        return None


class NotificationPanel:
    """Owns the Android Quick Settings shade on a dedicated Tk thread."""

    def __init__(
        self,
        on_command=None,
        on_status=None,
        on_code=None,
        on_downloads=None,
        on_quit=None,
        opacity=0.92,
        position="top-right",
        on_settings_save=None,
    ) -> None:
        self.on_command = on_command
        self.on_status = on_status
        self.on_code = on_code
        self.on_downloads = on_downloads
        self.on_quit = on_quit
        self.on_settings_save = on_settings_save
        try:
            self.opacity = max(MIN_OPACITY, min(MAX_OPACITY, float(opacity)))
        except (TypeError, ValueError):
            self.opacity = 0.92
        self.position = position or "top-right"
        self._h_align, self._v_align = self._parse_position(self.position)

        self._ops: "queue.Queue[tuple]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self.available = False

        self._media: dict | None = None
        self._messages: list[dict] = []
        self._open = False
        self._hover = False
        self._animating = False
        self._content_h = KNOB_H
        self._auto_close_id = None
        self._update_pending = False
        self._settings_win: tk.Toplevel | None = None
        self._save_after_id = None
        self._pos_var = None

        self._root: tk.Tk | None = None
        self._window: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._frames: list = []
        self._image_cache: list[ImageTk.PhotoImage] = []
        self._clock_time_lbl: tk.Label | None = None
        self._clock_date_lbl: tk.Label | None = None
        self._work = (0, 0, 1920, 1040)

    # ---- Public API (Thread-Safe) ---------------------------------------
    def start(self) -> None:
        if not _HAVE_TK:
            log.warning("tkinter/Pillow not available; notification panel disabled")
            return
        self._thread = threading.Thread(target=self._run, name="panel", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._ops.put(("stop",))

    def show(self, type_, nid, app, title, text, can_reply, actions, art="") -> None:
        self._ops.put(("show", type_, nid, app, title, text, can_reply, actions or [], art or ""))

    # ---- Panel Thread ---------------------------------------------------
    def _run(self) -> None:
        try:
            root = tk.Tk()
        except Exception:
            log.exception("Failed to create tkinter root; panel disabled")
            return
        self._root = root
        root.withdraw()
        self._work = _work_area()
        self._build_fonts()

        window = tk.Toplevel(root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=MAGIC)
        try:
            window.wm_attributes("-transparentcolor", MAGIC)
            window.wm_attributes("-alpha", self.opacity)
        except Exception:
            log.warning("Transparent/alpha not supported; fallback to standard frame")
        self._window = window

        canvas = tk.Canvas(window, bg=MAGIC, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        self._canvas = canvas

        self._bind_events()
        self._render()
        self._apply_geometry()
        self.available = True
        log.info("Android Quick Settings panel ready")
        root.after(60, self._pump)
        root.after(10000, self._tick_clock)
        root.mainloop()

    def _build_fonts(self) -> None:
        self._f_clock_time = tkfont.Font(family="Segoe UI", size=20, weight="bold")
        self._f_clock_date = tkfont.Font(family="Segoe UI", size=9)
        self._f_chip = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self._f_title = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self._f_body = tkfont.Font(family="Segoe UI", size=10)
        self._f_small = tkfont.Font(family="Segoe UI", size=9)
        self._f_tile_title = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._f_tile_sub = tkfont.Font(family="Segoe UI", size=8)
        self._f_glyph = tkfont.Font(family="Segoe UI Symbol", size=14)
        self._f_tile_glyph = tkfont.Font(family="Segoe UI Symbol", size=15)
        self._f_fab_glyph = tkfont.Font(family="Segoe UI Symbol", size=18, weight="bold")

    # ---- Event Bindings -------------------------------------------------
    def _bind_events(self) -> None:
        self._root.bind_all("<MouseWheel>", self._on_wheel)
        self._window.bind("<Enter>", self._on_enter)
        self._window.bind("<Leave>", self._on_leave)
        self._window.bind("<FocusOut>", self._on_focus_out)

    def _on_wheel(self, event) -> None:
        if not self._open:
            self._open_shade()
            return
        if getattr(event, "delta", 0) > 0:
            self._close_shade()

    def _on_enter(self, event=None) -> None:
        if self._hover:
            return
        self._hover = True
        if not self._open:
            self._render()

    def _on_leave(self, event=None) -> None:
        self._hover = False
        if not self._open:
            self._render()

    def _on_focus_out(self, event=None) -> None:
        if self._open and not self._settings_open():
            self._root.after(150, self._close_shade)

    # ---- Event Loop & Message Pumping -----------------------------------
    def _pump(self) -> None:
        while True:
            try:
                op = self._ops.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle(op)
            except Exception:
                log.exception("Panel op failed: %s", op[0])
        if self._root is not None:
            self._root.after(60, self._pump)

    def _handle(self, op: tuple) -> None:
        kind = op[0]
        if kind == "show":
            _, type_, nid, app, title, text, can_reply, actions, art = op
            self._ingest(type_, nid, app, title, text, can_reply, actions, art)
        elif kind == "stop":
            if self._root is not None:
                try:
                    self._root.destroy()
                except Exception:
                    pass

    def _ingest(self, type_, nid, app, title, text, can_reply, actions, art) -> None:
        if type_ == "media":
            self._media = {
                "nid": nid,
                "app": app,
                "title": title,
                "text": text,
                "actions": actions,
                "art": art,
            }
        elif type_ == "message":
            msg = {
                "nid": nid,
                "app": app,
                "title": title,
                "text": text,
                "can_reply": can_reply,
                "art": art,
            }
            self._messages = [m for m in self._messages if m.get("nid") != nid]
            self._messages.insert(0, msg)
            self._messages = self._messages[:MAX_MESSAGES]
        self._update()

    def _tick_clock(self) -> None:
        if self._root is None:
            return
        if self._open:
            if self._clock_time_lbl is not None:
                try:
                    self._clock_time_lbl.config(text=time.strftime("%I:%M").lstrip("0"))
                except Exception:
                    pass
            if self._clock_date_lbl is not None:
                try:
                    self._clock_date_lbl.config(text=time.strftime("%a, %b %d"))
                except Exception:
                    pass
        self._root.after(10000, self._tick_clock)

    # ---- Open / Close & Animations --------------------------------------
    def _parse_position(self, pos: str) -> tuple[str, str]:
        p = (pos or "top-right").strip().lower().replace("_", "-")
        h = "left" if p in ("top-left", "bottom-left") else "right"
        v = "bottom" if p in ("bottom-right", "bottom-left") else "top"
        return h, v

    def _edge_x(self, side: str) -> int:
        return self._work[0] if side == "left" else self._work[2]

    def _edge_y(self, side: str) -> int:
        return self._work[1] if side == "top" else self._work[3]

    def _x_margin(self) -> int:
        return EDGE_MARGIN if (self._h_align == "right" and self._v_align == "top") else 8

    def _x_for(self, width: int) -> int:
        margin = self._x_margin()
        if self._h_align == "right":
            return self._edge_x("right") - margin - width
        return self._edge_x("left") + margin

    def _y_for(self, height: int) -> int:
        if self._v_align == "top":
            return self._edge_y("top")
        return self._edge_y("bottom") - height

    def _slide_span(self, h: int) -> tuple[int, int]:
        if self._v_align == "top":
            return self._edge_y("top") - h, self._edge_y("top")
        return self._edge_y("bottom"), self._edge_y("bottom") - h

    def _open_shade(self) -> None:
        if self._animating:
            return
        self._open = True
        self._render()
        self._animating = True
        w, h, x = self._panel_geometry()
        start_y, target_y = self._slide_span(h)
        self._window.geometry(f"{w}x{h}+{x}+{start_y}")
        self._window.deiconify()
        self._window.lift()
        self._window.attributes("-topmost", True)
        self._focus()
        self._arm_auto_close()
        self._slide_to(w, h, x, start_y, target_y, done=lambda: setattr(self, "_animating", False))

    def _close_shade(self) -> None:
        if not self._open or self._animating:
            return
        self._animating = True
        self._cancel_auto_close()
        w, h, x = self._panel_geometry()
        target_y, start_y = self._slide_span(h)

        def done() -> None:
            self._animating = False
            self._open = False
            self._render()
            self._apply_geometry()

        self._slide_to(w, h, x, start_y, target_y, done=done)

    def _panel_geometry(self) -> tuple[int, int, int]:
        w = WIDTH
        h = max(self._content_h, KNOB_H)
        x = self._x_for(w)
        return w, h, x

    def _apply_geometry(self) -> None:
        if self._open:
            w, h, x = self._panel_geometry()
            y = self._y_for(h)
        else:
            w, h, x = KNOB_W, KNOB_H, self._x_for(KNOB_W)
            y = self._y_for(KNOB_H)
        self._window.geometry(f"{w}x{h}+{x}+{y}")
        self._window.deiconify()

    def _slide_to(self, w, h, x, start_y, target_y, done=None, steps=12, ms=14) -> None:
        dy = (target_y - start_y) / steps

        def tick(i: int) -> None:
            if i >= steps:
                self._window.geometry(f"{w}x{h}+{x}+{target_y}")
                if done:
                    done()
                return
            self._window.geometry(f"{w}x{h}+{x}+{int(start_y + dy * i)}")
            self._root.after(ms, tick, i + 1)

        tick(1)

    def _focus(self) -> None:
        try:
            self._window.focus_force()
        except Exception:
            pass

    def _arm_auto_close(self) -> None:
        self._cancel_auto_close()
        self._auto_close_id = self._root.after(90000, self._close_shade)

    def _cancel_auto_close(self) -> None:
        if self._auto_close_id is not None:
            try:
                self._root.after_cancel(self._auto_close_id)
            except Exception:
                pass
            self._auto_close_id = None

    def _update(self) -> None:
        if not self._open or self._update_pending:
            return
        self._update_pending = True
        self._root.after(40, self._flush_update)

    def _flush_update(self) -> None:
        self._update_pending = False
        if self._open and not self._animating:
            self._render()
            self._apply_geometry()

    # ---- Rendering Pipeline ---------------------------------------------
    def _render(self) -> None:
        canvas = self._canvas

        if not self._open:
            canvas.delete("all")
            for frame in self._frames:
                try:
                    frame.destroy()
                except Exception:
                    pass
            self._frames = []
            self._image_cache = []
            self._clock_time_lbl = None
            self._clock_date_lbl = None
            self._draw_knob()
            self._content_h = KNOB_H
            return

        new_frames: list = []
        self._image_cache = []
        blocks: list[tuple] = []
        y = 24

        # 1. Android Header (Clock + Date + Status Chip)
        header_cv, h_header = self._build_header()
        new_frames.append(header_cv)
        blocks.append((header_cv, h_header, "header"))

        # 2. Quick Settings 2-Column Pill Tiles
        tiles_cv, h_tiles = self._build_quick_tiles()
        new_frames.append(tiles_cv)
        blocks.append((tiles_cv, h_tiles, "tiles"))

        # 3. Media Player Widget (Now Playing)
        if self._media:
            media_cv, h_media = self._build_media_card(self._media)
            new_frames.append(media_cv)
            blocks.append((media_cv, h_media, "card"))
        else:
            ph_cv, h_ph = self._build_placeholder()
            new_frames.append(ph_cv)
            blocks.append((ph_cv, h_ph, "card"))

        # 4. Message Notifications
        for msg in self._messages:
            msg_cv, h_msg = self._build_message_card(msg)
            new_frames.append(msg_cv)
            blocks.append((msg_cv, h_msg, "card"))

        # Compute total height
        gap = 10
        total = y
        for _, h, _ in blocks:
            total += h + gap
        total = total - gap + 20

        # Atomic swap
        canvas.delete("all")
        for frame in self._frames:
            try:
                frame.destroy()
            except Exception:
                pass
        self._frames = new_frames
        self._content_h = total

        # Outer background panel (Material You rounded surface)
        _rounded_rect(canvas, 0, 0, WIDTH, total, RADIUS, fill=SURFACE, outline=SURFACE_OUTLINE)

        # Android Gesture Bar Handle (Top pill)
        gx = WIDTH // 2
        _rounded_rect(canvas, gx - KNOB_PILL_W // 2, 8, gx + KNOB_PILL_W // 2, 8 + KNOB_PILL_H,
                      KNOB_PILL_H // 2,
                      fill=GRABBER_HOVER if self._hover else GRABBER, outline="")
        canvas.tag_bind(canvas.create_rectangle(gx - 48, 2, gx + 48, 22, outline="", fill=""),
                        "<Button-1>", lambda e: self._close_shade())

        # Place child blocks
        cy = y
        for widget, h, _ in blocks:
            canvas.create_window(MARGIN, cy, anchor="nw", window=widget)
            cy += h + gap

    def _draw_knob(self) -> None:
        color = GRABBER_HOVER if self._hover else GRABBER
        x = (KNOB_W - KNOB_PILL_W) // 2
        y = (KNOB_H - KNOB_PILL_H) // 2
        _rounded_rect(self._canvas, x, y, x + KNOB_PILL_W, y + KNOB_PILL_H, KNOB_PILL_H // 2,
                      fill=color, outline="")
        self._canvas.tag_bind(
            self._canvas.create_rectangle(0, 0, KNOB_W, KNOB_H, outline="", fill=""),
            "<Button-1>", lambda e: self._open_shade(),
        )

    # ---- Header (Android Clock + Status Chip) ----------------------------
    def _build_header(self) -> tuple[tk.Canvas, int]:
        cv = tk.Canvas(self._canvas, bg=SURFACE, highlightthickness=0, bd=0)
        h = 44
        cv.config(width=CARD_W, height=h)

        # Time & Date on Left
        time_str = time.strftime("%I:%M").lstrip("0")
        date_str = time.strftime("%a, %b %d")

        time_lbl = tk.Label(cv, text=time_str, bg=SURFACE, fg=FG, font=self._f_clock_time)
        time_lbl.place(x=4, y=0, anchor="nw")
        self._clock_time_lbl = time_lbl

        date_lbl = tk.Label(cv, text=date_str, bg=SURFACE, fg=FG_MUTED, font=self._f_clock_date)
        date_lbl.place(x=6, y=28, anchor="nw")
        self._clock_date_lbl = date_lbl

        # Status & Power Chip on Right
        chip_w = 126
        chip_h = 32
        chip_x = CARD_W - chip_w
        chip_y = 6
        _rounded_rect(cv, chip_x, chip_y, chip_x + chip_w, chip_y + chip_h, 16, fill=TILE_BG, outline=CARD_OUTLINE)

        # Green pulse dot + text
        cv.create_oval(chip_x + 12, chip_y + 11, chip_x + 22, chip_y + 21, fill=ACCENT_GREEN, outline="")
        chip_lbl = tk.Label(cv, text="SBConnect", bg=TILE_BG, fg=FG, font=self._f_chip)
        chip_lbl.place(x=chip_x + 28, y=chip_y + 16, anchor="w")

        # Power / Quit button
        quit_x = chip_x - 38
        _rounded_rect(cv, quit_x, chip_y, quit_x + 32, chip_y + chip_h, 16, fill=TILE_BG, outline=CARD_OUTLINE)
        q_btn = tk.Label(cv, text="⏻", bg=TILE_BG, fg=FG_MUTED, font=self._f_glyph, cursor="hand2")
        q_btn.place(x=quit_x + 16, y=chip_y + 16, anchor="center")
        q_btn.bind("<Button-1>", lambda e: self._fire(self.on_quit))

        return cv, h

    # ---- Quick Settings 2-Column Pill Tiles ------------------------------
    def _build_quick_tiles(self) -> tuple[tk.Canvas, int]:
        specs = [
            ("Receiver", "Port 45800", "📶", self.on_status),
            ("Pairing Code", "Tap to View", "🔑", self.on_code),
            ("Downloads", "Open Folder", "📥", self.on_downloads),
            ("Settings", "Opacity/Pos", "⚙", self._open_settings),
        ]
        gap = 8
        cols = 2
        tile_w = (CARD_W - gap) // cols
        tile_h = 54
        rows = (len(specs) + cols - 1) // cols
        total_h = rows * tile_h + (rows - 1) * gap

        cv = tk.Canvas(self._canvas, bg=SURFACE, highlightthickness=0, bd=0)
        cv.config(width=CARD_W, height=total_h)

        for i, (title, sub, icon, cb) in enumerate(specs):
            r = i // cols
            c = i % cols
            x = c * (tile_w + gap)
            y = r * (tile_h + gap)

            tile = self._create_tile_widget(cv, tile_w, tile_h, icon, title, sub, cb)
            cv.create_window(x, y, anchor="nw", window=tile, width=tile_w, height=tile_h)

        return cv, total_h

    def _create_tile_widget(self, parent, w, h, icon, title, sub, cb) -> tk.Canvas:
        cv = tk.Canvas(parent, bg=SURFACE, highlightthickness=0, bd=0)
        cv.config(width=w, height=h)

        # Pill background
        _rounded_rect(cv, 0, 0, w, h, TILE_RADIUS, fill=TILE_BG, outline=CARD_OUTLINE)

        # Left Icon Circle
        icon_size = 34
        ix = 8
        iy = (h - icon_size) // 2
        _rounded_rect(cv, ix, iy, ix + icon_size, iy + icon_size, icon_size // 2, fill="#32353E", outline="")
        icon_lbl = tk.Label(cv, text=icon, bg="#32353E", fg=ACCENT, font=self._f_tile_glyph)
        icon_lbl.place(x=ix + icon_size // 2, y=iy + icon_size // 2, anchor="center")

        # Right Text Column
        tx = ix + icon_size + 10
        t_lbl = tk.Label(cv, text=title, bg=TILE_BG, fg=FG, font=self._f_tile_title, anchor="w")
        t_lbl.place(x=tx, y=h // 2 - 8, anchor="w")

        s_lbl = tk.Label(cv, text=sub, bg=TILE_BG, fg=FG_MUTED, font=self._f_tile_sub, anchor="w")
        s_lbl.place(x=tx, y=h // 2 + 10, anchor="w")

        # Click handlers & Hover
        widgets = (cv, icon_lbl, t_lbl, s_lbl)
        for widget in widgets:
            widget.bind("<Button-1>", lambda e, cb=cb: self._fire(cb))
            widget.configure(cursor="hand2")

        return cv

    # ---- Media Card (Android 14/15 Now Playing Widget) -------------------
    def _build_media_card(self, media: dict) -> tuple[tk.Canvas, int]:
        title = (media.get("title") or "Now playing").strip()[:100]
        artist = (media.get("text") or media.get("app") or "").strip()[:100]
        app_name = (media.get("app") or "Music").strip()
        actions = _map_media_actions(media.get("actions") or [])
        nid = media.get("nid")
        art_b64 = media.get("art") or ""

        cv = tk.Canvas(self._canvas, bg=SURFACE, highlightthickness=0, bd=0)
        inner = tk.Frame(cv, bg=CARD)

        # 1. Header (App Badge + Output Device Chip)
        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x", padx=12, pady=(12, 6))

        app_icon_cv = tk.Canvas(top, width=18, height=18, bg=CARD, highlightthickness=0)
        app_icon_cv.pack(side="left")
        _rounded_rect(app_icon_cv, 0, 0, 18, 18, 9, fill="#32353E", outline="")
        app_icon_cv.create_text(9, 9, text="♫", fill=ACCENT, font=self._f_small)

        tk.Label(top, text=app_name[:20], bg=CARD, fg=FG_MUTED, font=self._f_small).pack(side="left", padx=(6, 0))

        # Output chip on right ("🔊 Phone")
        out_chip = tk.Frame(top, bg="#2A2D35", padx=8, pady=2)
        out_chip.pack(side="right")
        tk.Label(out_chip, text="🔊 Phone", bg="#2A2D35", fg=ACCENT, font=self._f_small).pack()

        # 2. Main Row: Album Art (Left) + Track Info (Right)
        mid = tk.Frame(inner, bg=CARD)
        mid.pack(fill="x", padx=12, pady=(4, 8))

        art_size = 76
        art_cv = tk.Canvas(mid, width=art_size, height=art_size, bg=CARD, highlightthickness=0)
        art_cv.pack(side="left")

        # Process real album artwork or fallback gradient
        photo = _process_album_art(art_b64, size=art_size, radius=ART_RADIUS)
        if photo is not None:
            self._image_cache.append(photo)
            art_cv.create_image(0, 0, anchor="nw", image=photo)
        else:
            grad_idx = sum(ord(c) for c in app_name) % len(ART_GRADIENTS)
            c1, _ = ART_GRADIENTS[grad_idx]
            _rounded_rect(art_cv, 0, 0, art_size, art_size, ART_RADIUS, fill=c1, outline="")
            art_cv.create_text(art_size // 2, art_size // 2, text="♫", fill="#FFFFFF",
                               font=tkfont.Font(family="Segoe UI Symbol", size=32))

        # Track text column
        textcol = tk.Frame(mid, bg=CARD)
        textcol.pack(side="left", fill="both", expand=True, padx=(12, 0))
        wrap_w = INNER_W - art_size - 12

        tk.Label(textcol, text=title, bg=CARD, fg=FG, anchor="w", justify="left",
                 font=self._f_title, wraplength=wrap_w).pack(fill="x")
        if artist and artist != title:
            tk.Label(textcol, text=artist, bg=CARD, fg=FG_MUTED, anchor="w", justify="left",
                     font=self._f_body, wraplength=wrap_w).pack(fill="x", pady=(3, 0))

        # 3. Android-style Scrubber Bar Visual
        scrub_cv = tk.Canvas(inner, width=INNER_W, height=14, bg=CARD, highlightthickness=0)
        scrub_cv.pack(padx=12, pady=(2, 6))
        track_y = 6
        _rounded_rect(scrub_cv, 0, track_y, INNER_W, track_y + 4, 2, fill="#32353E", outline="")
        prog_w = int(INNER_W * 0.42)
        _rounded_rect(scrub_cv, 0, track_y, prog_w, track_y + 4, 2, fill=ACCENT, outline="")
        # Scrubber thumb
        scrub_cv.create_oval(prog_w - 4, track_y - 3, prog_w + 6, track_y + 7, fill=ACCENT, outline="")

        # 4. Playback Controls Row
        controls = tk.Frame(inner, bg=CARD)
        controls.pack(pady=(4, 12))

        # Prev button
        if actions.get("prev") is not None:
            self._build_icon_btn(controls, 42, "⏮", lambda: self._on_media(nid, actions["prev"]))
        else:
            self._spacer(controls, 42)

        # Centerpiece Play/Pause FAB
        if actions.get("pause") is not None:
            self._build_fab(controls, 50, "pause", lambda: self._on_media(nid, actions["pause"]))
        elif actions.get("play") is not None:
            self._build_fab(controls, 50, "play", lambda: self._on_media(nid, actions["play"]))
        else:
            self._spacer(controls, 50)

        # Next button
        if actions.get("next") is not None:
            self._build_icon_btn(controls, 42, "⏭", lambda: self._on_media(nid, actions["next"]))
        else:
            self._spacer(controls, 42)

        return self._finish_card(cv, inner)

    def _build_fab(self, parent, size: int, mode: str, command) -> None:
        """Create a prominent Material You circular FAB button for play/pause."""
        cv = tk.Canvas(parent, width=size, height=size, bg=CARD, highlightthickness=0, bd=0)
        cv.pack(side="left", padx=14)
        cv.create_oval(0, 0, size, size, fill=ACCENT, outline="")

        c = size // 2
        if mode == "play":
            cv.create_polygon(c - 5, c - 9, c - 5, c + 9, c + 9, c, fill=TILE_ACTIVE_FG, outline="")
        else:
            cv.create_rectangle(c - 7, c - 8, c - 2, c + 8, fill=TILE_ACTIVE_FG, outline="")
            cv.create_rectangle(c + 2, c - 8, c + 7, c + 8, fill=TILE_ACTIVE_FG, outline="")

        cv.configure(cursor="hand2")
        cv.bind("<Button-1>", lambda e: command())

    def _build_icon_btn(self, parent, size: int, glyph: str, command) -> None:
        """Create a rounded secondary playback control button."""
        cv = tk.Canvas(parent, width=size, height=size, bg=CARD, highlightthickness=0, bd=0)
        cv.pack(side="left", padx=8)
        _rounded_rect(cv, 0, 0, size, size, size // 2, fill="#2A2D35", outline=CARD_OUTLINE)
        cv.create_text(size // 2, size // 2, text=glyph, fill=FG, font=self._f_glyph)
        cv.configure(cursor="hand2")
        cv.bind("<Button-1>", lambda e: command())

    def _spacer(self, parent, size: int) -> None:
        tk.Frame(parent, width=size, height=size, bg=CARD).pack(side="left", padx=8)

    def _build_placeholder(self) -> tuple[tk.Canvas, int]:
        cv = tk.Canvas(self._canvas, bg=SURFACE, highlightthickness=0, bd=0)
        inner = tk.Frame(cv, bg=CARD)
        tk.Label(inner, text="Nothing playing", bg=CARD, fg=FG_MUTED, font=self._f_body).pack(fill="x", pady=16)
        return self._finish_card(cv, inner)

    # ---- Notification Cards (Android Notification Shade Style) -----------
    def _build_message_card(self, msg: dict) -> tuple[tk.Canvas, int]:
        cv = tk.Canvas(self._canvas, bg=SURFACE, highlightthickness=0, bd=0)
        inner = tk.Frame(cv, bg=CARD)

        nid = msg.get("nid")
        app = msg.get("app") or "SBConnect"
        title = (msg.get("title") or "").strip()
        text = (msg.get("text") or "").strip()
        can_reply = bool(msg.get("can_reply"))
        art_b64 = msg.get("art") or ""

        # Top Header (App Icon + App Name + Timestamp)
        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x", padx=12, pady=(12, 4))

        icon_cv = tk.Canvas(top, width=22, height=22, bg=CARD, highlightthickness=0)
        icon_cv.pack(side="left")
        grad_idx = sum(ord(c) for c in app) % len(ART_GRADIENTS)
        c1, _ = ART_GRADIENTS[grad_idx]
        _rounded_rect(icon_cv, 0, 0, 22, 22, 11, fill=c1, outline="")
        icon_cv.create_text(11, 11, text=(app[:1].upper() or "●"), fill="#FFFFFF", font=self._f_small)

        tk.Label(top, text=app[:24], bg=CARD, fg=FG_MUTED, font=self._f_small).pack(side="left", padx=(6, 0))
        tk.Label(top, text="· now", bg=CARD, fg=FG_DIM, font=self._f_small).pack(side="left")

        # Content Row (Title + Text + optional Picture)
        content_frame = tk.Frame(inner, bg=CARD)
        content_frame.pack(fill="x", padx=12, pady=(4, 8))

        text_col = tk.Frame(content_frame, bg=CARD)
        text_col.pack(side="left", fill="both", expand=True)

        if title:
            tk.Label(text_col, text=title[:120], bg=CARD, fg=FG, anchor="w", justify="left",
                     font=self._f_title, wraplength=INNER_W - 24).pack(fill="x")
        if text:
            tk.Label(text_col, text=text[:400], bg=CARD, fg=FG_MUTED, anchor="w", justify="left",
                     font=self._f_body, wraplength=INNER_W - 24).pack(fill="x", pady=(2, 0))

        # Inline Picture if attached
        if art_b64:
            art_img = _process_album_art(art_b64, size=52, radius=12)
            if art_img:
                self._image_cache.append(art_img)
                pic_cv = tk.Canvas(content_frame, width=52, height=52, bg=CARD, highlightthickness=0)
                pic_cv.pack(side="right", padx=(8, 0))
                pic_cv.create_image(0, 0, anchor="nw", image=art_img)

        # Inline Reply (Android Material 3 input pill)
        if can_reply:
            reply_row = tk.Frame(inner, bg=CARD)
            reply_row.pack(fill="x", padx=12, pady=(6, 12))

            entry_box = tk.Frame(reply_row, bg="#16181D", highlightbackground=CARD_OUTLINE, highlightthickness=1)
            entry_box.pack(side="left", fill="x", expand=True)

            entry = tk.Entry(entry_box, bg="#16181D", fg=FG, insertbackground=FG,
                             relief="flat", bd=0, font=self._f_body)
            entry.pack(fill="x", ipady=6, padx=8)

            send_btn = tk.Button(reply_row, text="Reply", bg=ACCENT, fg=TILE_ACTIVE_FG,
                                 activebackground="#D3E3FD", activeforeground=TILE_ACTIVE_FG,
                                 bd=0, relief="flat", font=self._f_small, cursor="hand2", padx=14, pady=4)
            send_btn.pack(side="left", padx=(8, 0))

            def send_reply(event=None):
                txt = entry.get().strip()
                if txt:
                    self._on_reply(nid, txt)

            entry.bind("<Return>", send_reply)
            entry.bind("<Button-1>", lambda e: entry.focus_set())
            send_btn.configure(command=send_reply)

        return self._finish_card(cv, inner)

    # ---- Card Container Helper ------------------------------------------
    def _finish_card(self, cv: tk.Canvas, inner: tk.Frame) -> tuple[tk.Canvas, int]:
        inner.update_idletasks()
        h = inner.winfo_reqheight()
        cv.config(width=CARD_W, height=h)
        _rounded_rect(cv, 0, 0, CARD_W, h, CARD_RADIUS, fill=CARD, outline=CARD_OUTLINE)
        cv.create_window(0, 0, anchor="nw", window=inner, width=CARD_W, height=h)
        return cv, h

    # ---- Actions & Dispatch ---------------------------------------------
    def _fire(self, cb) -> None:
        if cb:
            cb()

    def _on_media(self, nid, action_id) -> None:
        if self.on_command and nid is not None and action_id is not None:
            self.on_command({"type": "action", "nid": nid, "action_id": action_id})
        self._arm_auto_close()

    def _on_reply(self, nid, text: str) -> None:
        if self.on_command and nid is not None:
            self.on_command({"type": "reply", "nid": nid, "text": text})
        self._messages = [m for m in self._messages if m.get("nid") != nid]
        self._update()

    # ---- Settings Dialog ------------------------------------------------
    def _settings_open(self) -> bool:
        return self._settings_win is not None and self._settings_win.winfo_exists()

    def _open_settings(self) -> None:
        if self._settings_open():
            self._settings_win.lift()
            return
        win = tk.Toplevel(self._root)
        win.title("SBConnect Preferences")
        win.configure(bg=SURFACE)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        self._settings_win = win

        tk.Label(win, text="Panel Opacity", bg=SURFACE, fg=FG, font=self._f_title, anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        scale = tk.Scale(
            win, from_=MIN_OPACITY, to=MAX_OPACITY, resolution=0.01, orient="horizontal",
            length=220, showvalue=True, command=self._on_opacity_change,
            bg=SURFACE, fg=FG, troughcolor=CARD, highlightthickness=0, bd=0,
            activebackground=ACCENT,
        )
        scale.set(self.opacity)
        scale.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))

        tk.Label(win, text="Screen Position", bg=SURFACE, fg=FG, font=self._f_title, anchor="w").grid(
            row=2, column=0, sticky="w", padx=16, pady=(6, 4))
        self._pos_var = tk.StringVar(value=self.position)
        for i, pos in enumerate(["top-right", "top-left", "bottom-right", "bottom-left"]):
            rb = tk.Radiobutton(
                win, text=pos, variable=self._pos_var, value=pos,
                command=self._on_position_change,
                bg=SURFACE, fg=FG, selectcolor=CARD, activebackground=CARD,
                highlightthickness=0, bd=0, font=self._f_body, anchor="w",
            )
            rb.grid(row=3 + i, column=0, sticky="w", padx=16, pady=2)

        tk.Frame(win, height=14, bg=SURFACE).grid(row=7, column=0)

    def _on_opacity_change(self, value) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        self.opacity = max(MIN_OPACITY, min(MAX_OPACITY, v))
        try:
            self._window.attributes("-alpha", self.opacity)
        except Exception:
            pass
        self._save_settings()

    def _on_position_change(self) -> None:
        pos = self._pos_var.get() if self._pos_var is not None else self.position
        self.set_position(pos)
        self._save_settings()

    def set_position(self, pos: str) -> None:
        self.position = pos
        self._h_align, self._v_align = self._parse_position(pos)
        self._apply_geometry()

    def _save_settings(self) -> None:
        if self.on_settings_save is None:
            return
        if self._save_after_id is not None:
            try:
                self._root.after_cancel(self._save_after_id)
            except Exception:
                pass
        self._save_after_id = self._root.after(300, self._do_save_settings)

    def _do_save_settings(self) -> None:
        self._save_after_id = None
        if self.on_settings_save is not None:
            self.on_settings_save(self.opacity, self.position)
