#!/usr/bin/env python3
"""
BMO Media Display — Show images, memes, and GIFs on screen.
=============================================================
BMO can display:
  - Random memes (fetched from Reddit/Imgur via public APIs)
  - Local images from a folder
  - Downloaded images by URL
  - BMO face reactions (Rosto images) in full-screen mode

The display uses tkinter fullscreen overlay when the GUI is active,
or saves images for external viewing in headless mode.

Usage:
    from bmo_media import MediaDisplay
    media = MediaDisplay(canvas, base_dir)
    media.show_meme()           # fetch + display random meme
    media.show_image(path)      # display a local image
    media.show_image_url(url)   # download + display image from URL
    media.clear()               # return to BMO face display
"""

import os, threading, time, random, requests, io, tempfile

from bmo.paths import PROJECT_ROOT

# ─── Optional deps ────────────────────────────────────────────────────────────
try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("[MEDIA] Pillow not installed — image display limited.", flush=True)

try:
    import tkinter as tk
    HAS_TK = True
except ImportError:
    HAS_TK = False


# ─── Meme sources (public no-auth APIs) ──────────────────────────────────────
MEME_SOURCES = [
    "https://meme-api.com/gimme",
    "https://meme-api.com/gimme/ProgrammerHumor",
    "https://meme-api.com/gimme/dankmemes",
    "https://meme-api.com/gimme/wholesomememes",
    "https://meme-api.com/gimme/me_irl",
]

# ─── Topic → subreddit mapping ───────────────────────────────────────────────
TOPIC_SUBREDDIT = {
    "cats":        "cats",
    "cat":         "cats",
    "dogs":        "dogmemes",
    "dog":         "dogmemes",
    "gaming":      "gaming",
    "games":       "gaming",
    "programming": "ProgrammerHumor",
    "coding":      "ProgrammerHumor",
    "code":        "ProgrammerHumor",
    "python":      "ProgrammerHumor",
    "food":        "AdviceAnimals",
    "anime":       "Animemes",
    "wholesome":   "wholesomememes",
    "dark":        "dankmemes",
    "dank":        "dankmemes",
    "sports":      "sports",
    "relatable":   "me_irl",
    "school":      "me_irl",
    "work":        "ProgrammerHumor",
    "music":       "AdviceAnimals",
    "adventure time": "adventuretime",
    "bmo":         "adventuretime",
}


def fetch_meme(topic: str = "") -> dict:
    """
    Fetch a meme from the public meme-api.com.
    If topic is given, try to match it to a known subreddit.
    Returns dict with 'url', 'title', 'subreddit' or empty dict on failure.
    """
    if topic:
        # Exact match first, then partial
        sub = TOPIC_SUBREDDIT.get(topic.lower())
        if not sub:
            for key, val in TOPIC_SUBREDDIT.items():
                if key in topic.lower() or topic.lower() in key:
                    sub = val
                    break
        url = f"https://meme-api.com/gimme/{sub}" if sub else random.choice(MEME_SOURCES)
    else:
        url = random.choice(MEME_SOURCES)

    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return {
                "url":       data.get("url", ""),
                "title":     data.get("title", ""),
                "subreddit": data.get("subreddit", ""),
                "author":    data.get("author", ""),
                "nsfw":      data.get("nsfw", False),
            }
    except Exception as e:
        print(f"[MEDIA] Meme fetch error: {e}", flush=True)
    return {}


def download_image(url: str, save_path: str) -> bool:
    """Download an image from a URL. Returns True on success."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"}
        r = requests.get(url, headers=headers, timeout=15, stream=True)
        if r.status_code == 200 and "image" in r.headers.get("Content-Type", ""):
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return True
        print(f"[MEDIA] Download failed: HTTP {r.status_code}", flush=True)
        return False
    except Exception as e:
        print(f"[MEDIA] Download error: {e}", flush=True)
        return False


# ─── Image overlay helper ─────────────────────────────────────────────────────
class MediaDisplay:
    """
    Manages fullscreen image/meme display on the BMO GUI canvas.
    Images are shown as an overlay; calling clear() restores the face.
    """

    TMP_DIR = "/tmp/bmo_media"

    def __init__(self, canvas=None, root=None, base_dir=None, status_cb=None):
        """
        canvas    — tkinter.Canvas (can be None for headless)
        root      — tkinter.Tk root window
        base_dir  — project root directory
        status_cb — callable(text) to update status label
        """
        self._canvas    = canvas
        self._root      = root
        self._base_dir  = base_dir or PROJECT_ROOT
        self._status_cb = status_cb
        self._img_id    = None          # current canvas image item id
        self._tk_img    = None          # tk.PhotoImage ref (prevent GC)
        self._active    = False
        self._lock      = threading.Lock()

        os.makedirs(self.TMP_DIR, exist_ok=True)

    # ─── Public API ──────────────────────────────────────────────────────────

    def show_meme(self, callback=None, topic: str = "") -> str:
        """
        Fetch and display a meme. If topic is given, try to find
        a topical meme (e.g. "cats", "gaming", "programming").
        Non-blocking — runs in background thread.
        callback(result_text) called when done.
        """
        def _run():
            meme = fetch_meme(topic=topic)
            if not meme or not meme.get("url"):
                msg = "Could not fetch a meme right now."
                if callback:
                    callback(msg)
                return

            if meme.get("nsfw"):
                msg = "That meme was marked NSFW, skipping it."
                if callback:
                    callback(msg)
                return

            save = os.path.join(self.TMP_DIR, "current_meme.jpg")
            ok   = download_image(meme["url"], save)
            if not ok:
                msg = "Could not download the meme image."
                if callback:
                    callback(msg)
                return

            self._display_image(save)
            sub    = meme.get("subreddit", "Reddit")
            title  = meme.get("title", "")
            result = f"Here's a{'n ' + topic if topic else ' random'} meme from r/{sub}: {title}"
            if callback:
                callback(result)

        threading.Thread(target=_run, daemon=True).start()
        return f"Fetching {'a ' + topic + ' ' if topic else 'a '}meme for you!"

    def show_image(self, path: str) -> str:
        """Display a local image file on screen."""
        if not os.path.exists(path):
            return f"Image not found: {path}"
        self._display_image(path)
        return f"Showing image: {os.path.basename(path)}"

    def show_image_url(self, url: str, callback=None) -> str:
        """Download and display an image from a URL."""
        def _run():
            save = os.path.join(self.TMP_DIR, "url_image.jpg")
            ok   = download_image(url, save)
            if ok:
                self._display_image(save)
                if callback:
                    callback("Image displayed.")
            else:
                if callback:
                    callback("Could not load the image from that URL.")

        threading.Thread(target=_run, daemon=True).start()
        return "Loading image…"

    def show_random_local(self, folder: str = None) -> str:
        """Display a random image from a local folder."""
        search_dir = folder or os.path.join(self._base_dir, "pictures")
        if not os.path.isdir(search_dir):
            return f"Pictures folder not found: {search_dir}"
        exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
        images = [f for f in os.listdir(search_dir)
                  if f.lower().endswith(exts)]
        if not images:
            return "No pictures found in the pictures folder."
        chosen = random.choice(images)
        path   = os.path.join(search_dir, chosen)
        self._display_image(path)
        return f"Showing: {chosen}"

    def clear(self) -> str:
        """Remove image overlay and return to normal BMO face."""
        with self._lock:
            self._active = False
            if self._canvas and self._img_id:
                try:
                    self._canvas.after(0, self._canvas.delete, self._img_id)
                except Exception:
                    pass
                self._img_id = None
                self._tk_img = None
        return "Image display cleared."

    def is_active(self) -> bool:
        """Return True if an image is currently being displayed."""
        return self._active

    # ─── Internal rendering ──────────────────────────────────────────────────

    def _display_image(self, path: str):
        """Render an image on the canvas. Must schedule on Tk main thread."""
        if not self._canvas or not HAS_TK:
            print(f"[MEDIA] Would display: {path}", flush=True)
            return

        def _render():
            try:
                c = self._canvas
                w = c.winfo_width()  or 800
                h = c.winfo_height() or 480

                if HAS_PIL:
                    img = Image.open(path).convert("RGB")
                    img.thumbnail((w, h - 60), Image.LANCZOS)
                    tk_img = ImageTk.PhotoImage(img)
                else:
                    tk_img = tk.PhotoImage(file=path)

                with self._lock:
                    if self._img_id:
                        c.delete(self._img_id)
                    cx, cy = w // 2, (h - 60) // 2
                    self._img_id = c.create_image(cx, cy, image=tk_img, anchor="center")
                    self._tk_img = tk_img  # hold reference
                    self._active = True

            except Exception as e:
                print(f"[MEDIA] Render error: {e}", flush=True)

        # Schedule on Tk main thread
        try:
            self._canvas.after(0, _render)
        except Exception as e:
            print(f"[MEDIA] Schedule error: {e}", flush=True)


# ─── Meme text overlay (draw caption on image) ───────────────────────────────
def add_meme_text(image_path: str, top_text: str = "", bottom_text: str = "",
                  out_path: str = None) -> str:
    """
    Add Impact-style meme caption text to an image.
    Returns path to the output image.
    """
    if not HAS_PIL:
        return image_path

    out_path = out_path or image_path.replace(".jpg", "_meme.jpg")
    try:
        img  = Image.open(image_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        W, H = img.size

        # Try to load Impact font, fall back to default
        font_size = max(36, W // 12)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                                      font_size)
        except Exception:
            font = ImageFont.load_default()

        def draw_text_with_outline(text, y_pos, anchor="mt"):
            for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
                draw.text((W // 2 + dx, y_pos + dy), text, font=font,
                          fill=(0, 0, 0, 255), anchor=anchor, align="center")
            draw.text((W // 2, y_pos), text, font=font,
                      fill=(255, 255, 255, 255), anchor=anchor, align="center")

        if top_text:
            draw_text_with_outline(top_text.upper(), 10, anchor="mt")
        if bottom_text:
            draw_text_with_outline(bottom_text.upper(), H - 10, anchor="mb")

        img.convert("RGB").save(out_path, "JPEG", quality=90)
        return out_path
    except Exception as e:
        print(f"[MEDIA] Text overlay error: {e}", flush=True)
        return image_path
