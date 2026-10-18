"""Selfie: live camera preview on BMO's screen, a spoken 5-second countdown, then save the shot."""
import datetime
import functools
import hashlib
import io
import json
import os
import shutil
import subprocess
import threading
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps

from bmo.camera import CameraBusy, exclusive, has_camera
from bmo.paths import CACHE_DIR, SELFIES_DIR

# 1296x972 is the OV5647's full-field-of-view mode; MJPEG frames double as the photo,
# so the shot is exactly the frame on screen when the countdown hits zero.
STREAM_CMD = ["rpicam-vid", "-t", "0", "--codec", "mjpeg", "--width", "1296", "--height", "972",
              "--framerate", "15", "-q", "92", "--nopreview", "-o", "-"]
PREVIEW_SIZE = (648, 486)
COUNTDOWN    = 5
SHOW_PHOTO_S = 4
FONT_PATH    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
INTRO        = "Selfie time! Look at my camera eye!"
NUMBERS      = ["Five!", "Four!", "Three!", "Two!", "One!"]


@functools.lru_cache(maxsize=4)
def _font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default(size=size)


class _Stream:
    """rpicam-vid MJPEG on stdout, keeping only the newest complete frame."""

    def __init__(self):
        self.latest = None
        self._proc = subprocess.Popen(STREAM_CMD, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = b""
        while True:
            chunk = self._proc.stdout.read1(65536)
            if not chunk:
                return
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                if start < 0:
                    buf = b""
                    break
                end = buf.find(b"\xff\xd9", start + 2)
                if end < 0:
                    buf = buf[start:]
                    break
                self.latest = buf[start:end + 2]
                buf = buf[end + 2:]

    def wait_first(self, timeout):
        deadline = time.time() + timeout
        while self.latest is None and time.time() < deadline and self._proc.poll() is None:
            time.sleep(0.05)
        return self.latest is not None

    def close(self):
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class SelfieSkill:
    def __init__(self, speak, get_media):
        self.speak = speak          # BMO's TTS queue (fallback when clips aren't ready)
        self.get_media = get_media  # MediaDisplay, or None when headless
        self._shot_id = 0
        self._play = None
        self._clips = None
        self._shutter = None

    def set_voice(self, voice):
        """Spoken countdown through the TTS queue lagged the on-screen numbers, so the
        lines are pre-rendered once (cached on disk) and played directly on cue."""
        if hasattr(voice, "render_clips"):
            threading.Thread(target=self._prepare_clips, args=(voice,), daemon=True).start()

    def _prepare_clips(self, voice):
        lines = [INTRO] + NUMBERS
        key = hashlib.sha1(json.dumps([voice.voice_onnx, voice.robotic_fx, lines]).encode()).hexdigest()[:12]
        out_dir = os.path.join(CACHE_DIR, "selfie_voice", key)
        clips = {t: os.path.join(out_dir, f"clip{i}.wav") for i, t in enumerate(lines)}
        if not all(os.path.exists(p) for p in clips.values()):
            clips = voice.render_clips(lines, out_dir)
        if len(clips) != len(lines):
            print("[SELFIE] Couldn't pre-render the countdown; will use normal speech.", flush=True)
            return
        shutter = os.path.join(out_dir, "shutter.wav")
        if not os.path.exists(shutter) and shutil.which("sox"):
            subprocess.run(["sox", "-n", "-r", "22050", "-c", "1", "-b", "16", shutter,
                            "synth", "0.07", "whitenoise", "fade", "q", "0.001", "0.07", "0.06", "vol", "0.5"],
                           capture_output=True, timeout=10)
        self._shutter = shutter if os.path.exists(shutter) else None
        self._play = voice.play_file
        self._clips = clips
        print("[SELFIE] Countdown voice ready.", flush=True)

    def take(self):
        if not has_camera():
            return "I don't have a camera hooked up right now."
        try:
            with exclusive(timeout=10):
                return self._shoot()
        except CameraBusy:
            return "My camera is busy right now. Try again in a second!"

    def _shoot(self):
        media = self.get_media()
        self._shot_id += 1
        shot_id = self._shot_id
        stream = _Stream()
        try:
            if not stream.wait_first(timeout=6):
                return "My camera eye wouldn't open. Try again?"
            clips = self._clips
            if clips:
                intro = self._play(clips[INTRO])
                self._preview(stream, media, 5.0, None, until=lambda: intro.poll() is not None)
                self._preview(stream, media, 0.3, None)
            else:
                self.speak(INTRO)
                self._preview(stream, media, 2.2, None)
            # Fixed schedule from t0 so the numbers never drift from one second apart.
            t0 = time.time()
            for i, n in enumerate(range(COUNTDOWN, 0, -1)):
                if clips:
                    self._play(clips[NUMBERS[i]])
                else:
                    self.speak(str(n))
                self._preview(stream, media, t0 + i + 1 - time.time(), str(n))
            shot = stream.latest
            if clips and self._shutter:
                self._play(self._shutter)
        except Exception as e:
            print(f"[SELFIE] Error: {e}", flush=True)
            if media:
                media.clear()
            return "Oops, my camera hiccuped. Try again?"
        finally:
            stream.close()

        path = os.path.join(SELFIES_DIR, datetime.datetime.now().strftime("selfie_%Y-%m-%d_%H-%M-%S.jpg"))
        os.makedirs(SELFIES_DIR, exist_ok=True)
        with open(path, "wb") as f:
            f.write(shot)
        print(f"[SELFIE] Saved {path}", flush=True)

        if media:
            self._show(media, Image.new("RGB", PREVIEW_SIZE, "white"))  # shutter flash
            time.sleep(0.15)
            photo = Image.open(io.BytesIO(shot))
            photo.draft("RGB", PREVIEW_SIZE)
            self._show(media, photo.convert("RGB"))
            threading.Timer(SHOW_PHOTO_S, self._clear_if_current, args=(media, shot_id)).start()
        count = len([f for f in os.listdir(SELFIES_DIR) if f.startswith("selfie_")])
        return f"Click! Got it. That's selfie number {count} in my album!"

    def _preview(self, stream, media, seconds, label, until=None):
        deadline = time.time() + seconds
        shown = None  # so the new label is drawn immediately, not on the next camera frame
        while time.time() < deadline and not (until and until()):
            jpg = stream.latest
            if media and jpg is not None and jpg is not shown:
                shown = jpg
                media.show_frame(self._frame(jpg, label))
            time.sleep(0.03)

    @staticmethod
    def _frame(jpg, label):
        img = Image.open(io.BytesIO(jpg))
        img.draft("RGB", PREVIEW_SIZE)
        img = ImageOps.mirror(img.convert("RGB"))  # preview acts like a mirror; the saved photo doesn't
        if label:
            ImageDraw.Draw(img).text(
                (img.width // 2, img.height // 2), label, font=_font(img.height // 2), anchor="mm",
                fill="white", stroke_width=max(2, img.height // 60), stroke_fill="black")
        return img

    @staticmethod
    def _show(media, img):
        # show_frame drops frames while one is still drawing; these two must land.
        deadline = time.time() + 1.0
        while not media.show_frame(img) and time.time() < deadline:
            time.sleep(0.02)

    def _clear_if_current(self, media, shot_id):
        if shot_id == self._shot_id:
            media.clear()
