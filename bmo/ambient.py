#!/usr/bin/env python3
"""
BMO Ambient Mode — Relax mode with lo-fi music and a happy musical face.
"""

import os
import threading
import subprocess
import random
import time
import requests

# A more robust list of Lo-Fi streams (Removed dead ones)
LOFI_STREAMS = [
    "https://lofi.stream.laut.fm/lofi",
    "http://usa9.fastcast4u.com:8000/lowfimusic",
    "https://ice6.nowplaying.radio/lofi.mp3"
]

class AmbientMode:
    def __init__(self, media_display, face_system=None):
        self.media = media_display
        self.face  = face_system
        self._music_proc = None
        self._active = False
        self._lock = threading.Lock()

    def start(self) -> str:
        with self._lock:
            if self._active:
                return "Ambient mode is already active."
            self._active = True

        # Shuffle streams to try different ones
        streams = list(LOFI_STREAMS)
        random.shuffle(streams)

        success = False
        tried_urls = []

        for stream_url in streams:
            print(f"[AMBIENT] Trying stream: {stream_url}", flush=True)
            tried_urls.append(stream_url)
            
            # Quick check if URL is reachable
            try:
                # Use a small timeout for the head request
                r = requests.head(stream_url, timeout=3, allow_redirects=True)
                if r.status_code >= 400:
                    print(f"[AMBIENT] Stream returned {r.status_code}, skipping.", flush=True)
                    continue
            except Exception as e:
                print(f"[AMBIENT] Could not reach stream {stream_url}: {e}", flush=True)
                continue

            try:
                # Try starting with mpv
                self._music_proc = subprocess.Popen(
                    ["mpv", "--no-video", "--volume=70", stream_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                # Give it a bit more time to buffer and see if it stays alive
                time.sleep(1.0)
                if self._music_proc.poll() is None:
                    success = True
                    print(f"[AMBIENT] Successfully started {stream_url}", flush=True)
                    break
                else:
                    print(f"[AMBIENT] mpv failed to play {stream_url} (process died)", flush=True)
            except Exception as e:
                print(f"[AMBIENT] Error starting mpv: {e}", flush=True)
                # Fallback to cvlc
                try:
                    self._music_proc = subprocess.Popen(
                        ["cvlc", "--no-video", "--gain=0.7", stream_url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    time.sleep(1.0)
                    if self._music_proc.poll() is None:
                        success = True
                        print(f"[AMBIENT] Successfully started {stream_url} with cvlc", flush=True)
                        break
                except Exception:
                    continue

        if not success:
            self._active = False
            return "Could not find a working music stream. Please check your internet connection."

        # 2. Clear Visuals (as per user request to stop using GIFs/pics)
        if self.media:
            self.media.clear()

        # 3. Change Face to music
        if self.face:
            self.face.set_emotion("music")

        return "Starting Ambient Mode. Relax and enjoy the lo-fi vibes."

    def stop(self) -> str:
        with self._lock:
            if not self._active:
                return "Ambient mode is not active."
            self._active = False

        if self._music_proc:
            print("[AMBIENT] Stopping music process...", flush=True)
            try:
                self._music_proc.terminate()
                self._music_proc.wait(timeout=2)
            except:
                try:
                    self._music_proc.kill()
                except:
                    pass
            self._music_proc = None

        if self.media:
            self.media.clear()

        if self.face:
            self.face.set_emotion("idle")

        return "Ambient Mode stopped. Welcome back!"

    def is_active(self) -> bool:
        return self._active
