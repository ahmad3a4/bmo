#!/usr/bin/env python3
"""
BMO HUD — Persistent heads-up display overlay drawn on the tkinter canvas.

Top bar:     [clock · date]      [♫ Song — Artist]      [@handle followers]
Bottom bar:  [CPU%]  [RAM%]  [🌡 temp]

All drawing is non-blocking. Background threads poll data on their own schedule
and cache the latest values. _draw() just reads the cached values each frame.
"""

import threading
import time
import datetime
import os

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class BMOHud:
    # ── Colour palette ────────────────────────────────────────────────────────
    BAR_BG  = "#0f1f1c"    # near-black dark green bar
    FG_MAIN = "#e8f5e8"    # bright near-white for primary text
    FG_DIM  = "#78a878"    # muted green for secondary text
    FG_SONG = "#ffffff"    # pure white for song title
    FG_ACC  = "#a0d8a0"    # light mint for accent labels

    BAR_H   = 38           # pixel height of each bar

    FONT_CLOCK = ("Helvetica", 13, "bold")
    FONT_SONG  = ("Helvetica", 12)
    FONT_INSTA = ("Helvetica", 11)
    FONT_STAT  = ("Helvetica", 11)

    def __init__(self, canvas, spotify_skill=None, cfg=None):
        self._canvas    = canvas
        self._spotify   = spotify_skill
        self._cfg       = cfg or {}

        # ── Cached state (written by threads, read by draw) ───────────────
        self._time_str   = ""
        self._date_str   = ""
        self._song       = ""
        self._artist     = ""
        self._is_playing = False
        self._followers  = "..."
        self._cpu        = 0.0
        self._ram        = 0.0
        self._temp       = None

        self._stop = threading.Event()

        # Animation state for scrolling text
        self._scroll_offset = 800.0 # start off-screen right
        self._last_draw_time = time.time()

        # Start background polling threads
        threading.Thread(target=self._poll_clock,     daemon=True).start()
        threading.Thread(target=self._poll_spotify,   daemon=True).start()
        threading.Thread(target=self._poll_system,    daemon=True).start()

        print("[HUD] Heads-up display started.", flush=True)

    def stop(self):
        self._stop.set()

    # ── Background pollers ────────────────────────────────────────────────────

    def _poll_clock(self):
        while not self._stop.is_set():
            now = datetime.datetime.now()
            self._time_str = now.strftime("%I:%M %p").lstrip("0")
            self._date_str = now.strftime("%a, %b %d")
            time.sleep(1)

    def _poll_spotify(self):
        while not self._stop.is_set():
            try:
                if self._spotify and getattr(self._spotify, "sp", None):
                    info = self._spotify.current_track_info()
                    if info:
                        self._song       = info.get("name", "")
                        self._artist     = info.get("artist", "")
                        self._is_playing = info.get("is_playing", False)
                    else:
                        self._song       = ""
                        self._artist     = ""
                        self._is_playing = False
            except Exception:
                pass
            time.sleep(6)

    def _poll_system(self):
        while not self._stop.is_set():
            try:
                if HAS_PSUTIL:
                    self._cpu = psutil.cpu_percent(interval=1)
                    self._ram = psutil.virtual_memory().percent
                try:
                    with open("/sys/class/thermal/thermal_zone0/temp") as f:
                        self._temp = int(f.read().strip()) / 1000
                except Exception:
                    self._temp = None
            except Exception:
                pass
            time.sleep(5)



    # ── Draw (called every frame from aria.py _draw_ui) ──────────────────────

    def draw(self, canvas):
        """Render the HUD on top of the face. Called each animation tick."""
        try:
            w = canvas.winfo_width()  or 800
            h = canvas.winfo_height() or 480
            bh = self.BAR_H

            # Calculate time delta for smooth scrolling
            now = time.time()
            dt = now - self._last_draw_time
            self._last_draw_time = now
            
            # Scroll speed (pixels per second)
            scroll_speed = 35.0
            self._scroll_offset -= scroll_speed * dt

            # ═══════════════════ COMBINED BOTTOM BAR ════════════════════════
            canvas.create_rectangle(0, h - bh, w, h,
                                    fill=self.BAR_BG, outline="")
            canvas.create_line(0, h - bh, w, h - bh, fill="#1e3830", width=1)

            # Build the combined string
            clock_str = f"{self._time_str}   {self._date_str}"
            
            if self._song:
                icon = "▶" if self._is_playing else "⏸"
                song_str = f"{icon}  {self._song}  —  {self._artist}"
            else:
                song_str = "♫  Nothing playing"

            parts = []
            if HAS_PSUTIL:
                parts.append(f"CPU {self._cpu:.0f}%")
                parts.append(f"RAM {self._ram:.0f}%")
            if self._temp is not None:
                parts.append(f"Temp {self._temp:.1f}°C")
            stats_str = "  ·  ".join(parts) if parts else "System stats unavailable"

            # The full marquee text
            full_text = f"{clock_str}        |        {song_str}        |        {stats_str}"

            # Draw the text at the current offset
            text_id = canvas.create_text(
                int(self._scroll_offset), h - bh // 2,
                text=full_text,
                fill=self.FG_MAIN, font=self.FONT_SONG, anchor="w"
            )

            # Check if text is completely off-screen to the left
            bbox = canvas.bbox(text_id)
            if bbox and bbox[2] < 0: # right edge of text < 0
                self._scroll_offset = float(w) # Reset to right edge of screen

        except Exception:
            pass
