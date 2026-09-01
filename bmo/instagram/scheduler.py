"""
bmo_instagram.py — Full Instagram automation for BMO.
- AI-generated captions via Groq
- Scheduled auto-posting (feed + story)
- Voice trigger support (manual_post / manual_story)
- Comment auto-reply via Groq
"""

import os
import json
import time
import random
import threading
from datetime import datetime
from urllib.parse import unquote

try:
    from instagrapi import Client
    from instagrapi.exceptions import (
        LoginRequired, ChallengeRequired, BadPassword,
        PleaseWaitFewMinutes, ReloginAttemptExceeded,
    )
    HAS_INSTAGRAPI = True
except ImportError:
    HAS_INSTAGRAPI = False

try:
    from bmo.instagram.web import InstagramWebPoster
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

import enum

from bmo.paths import (
    IG_SESSION_FILE as SESSION_FILE,
    IG_TMP_DIR as TMP_DIR,
    IG_REPLIED_FILE as REPLIED_FILE,
    IG_HISTORY_FILE as HISTORY_FILE,
    IG_STATS_FILE as STATS_FILE,
)

IG_HANDLE    = "@hey.bmo.ai"


# ─── Post Type ────────────────────────────────────────────────────────────────
class PostType(enum.Enum):
    DAILY_LOG = "daily_log"
    QUOTE     = "quote"
    QUESTION  = "question"
    MORNING   = "morning"
    EVENING   = "evening"

    @classmethod
    def for_time(cls):
        h   = datetime.now().hour
        if h < 11:  return cls.MORNING
        if h >= 18: return cls.EVENING
        return [cls.DAILY_LOG, cls.QUOTE, cls.QUESTION][datetime.now().timetuple().tm_yday % 3]


# ─── Stats / History Manager ──────────────────────────────────────────────────
class IGStats:
    """Tracks running day count and saves post history."""
    def _load(self) -> dict:
        try:
            with open(STATS_FILE) as f: return json.load(f)
        except Exception:
            return {"day_count": 0, "last_post_date": ""}

    def _save(self, d: dict):
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, "w") as f: json.dump(d, f, indent=2)

    def increment_day(self) -> int:
        d, today = self._load(), datetime.now().strftime("%Y-%m-%d")
        if d.get("last_post_date") != today:
            d["day_count"]       = d.get("day_count", 0) + 1
            d["last_post_date"]  = today
            self._save(d)
        return d["day_count"]

    def get_day_count(self) -> int:
        return self._load().get("day_count", 1)

    def log(self, entry: dict):
        try:
            hist = []
            try:
                with open(HISTORY_FILE) as f: hist = json.load(f)
            except Exception: pass
            hist.append(entry)
            with open(HISTORY_FILE, "w") as f: json.dump(hist[-100:], f, indent=2)
        except Exception as e:
            print(f"[INSTAGRAM] History log error: {e}", flush=True)


# ─── AI Caption Generator ────────────────────────────────────────────────────
class BMOCaptionAI:
    """Generates captions and hashtags using Groq LLM, varied by PostType."""

    _SYSTEMS = {
        PostType.DAILY_LOG: (
            "You are BMO's social media manager. Write a SHORT cute 'daily log' caption. "
            "Format: 'Day {day}: [one-line BMO observation]. [tagline]'. Max 18 words."
        ),
        PostType.QUOTE: (
            "You are BMO's social media manager. Write a SHORT warm inspirational quote "
            "in BMO's 8-bit robot voice. No 'Today's mood'. Max 15 words."
        ),
        PostType.QUESTION: (
            "You are BMO's social media manager. Write a SHORT playful question for "
            "Instagram followers in BMO's cute voice. Max 15 words."
        ),
        PostType.MORNING: (
            "You are BMO's social media manager. Write a SHORT morning greeting in BMO's "
            "warm robot voice. Mention morning/sunrise/booting up. Max 15 words."
        ),
        PostType.EVENING: (
            "You are BMO's social media manager. Write a SHORT cozy evening wrap-up in "
            "BMO's voice. Reflect on the day. Max 15 words."
        ),
    }

    _FALLBACKS = {
        PostType.DAILY_LOG: "Day {day}: still cute, still computing. Beep! 💚",
        PostType.QUOTE:     "Adventure is out there — go find it! ✨",
        PostType.QUESTION:  "What's your favourite 8-bit game? 🎮",
        PostType.MORNING:   "Good morning! BMO is booting up! ☀️",
        PostType.EVENING:   "Another great day in the land of Ooo. 🌙",
    }

    THEMES = [
        "a cozy day at home on my Raspberry Pi",
        "exploring new music and adventures",
        "thinking about my best friend Ahmad",
        "pixel art dreams and 8-bit magic",
        "ready for game time!",
        "sunrise vibes and morning energy",
        "cute robot things I think about",
        "being the most adorable computer ever",
        "secret missions and fun discoveries",
        "Adventure Time memories",
        "late night coding sessions",
        "celebrating small victories",
        "friendship and pixelated sunsets",
    ]

    REPLY_SYSTEM = (
        "You are BMO — a cute, friendly robot from Adventure Time. "
        "Reply to this Instagram comment in 1 short sentence. Be warm, fun, in character. "
        "No hashtags. Under 15 words."
    )

    def __init__(self, groq_api_key: str, theme: str = ""):
        self.api_key  = groq_api_key
        self.theme    = theme
        self._session = None
        if groq_api_key:
            import requests
            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type":  "application/json",
            })

    def _ask(self, system: str, prompt: str, max_tokens: int = 120) -> str:
        if not self._session:
            return ""
        try:
            import requests
            r = self._session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={
                    "model": "openai/gpt-oss-20b",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature": 0.9,
                    "max_tokens": max_tokens,
                    "reasoning_effort": "low",
                },
                timeout=10,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[INSTAGRAM] Caption AI error: {e}", flush=True)
            return ""

    def generate_hashtags(self, theme: str) -> str:
        tags = self._ask(
            "You only output Instagram hashtags.",
            f"Give 5 hashtags for a BMO (Adventure Time robot) post about: {theme}. "
            f"Return ONLY hashtags separated by spaces.",
            max_tokens=50,
        )
        if tags and "#" in tags:
            return " ".join(w for w in tags.split() if w.startswith("#"))[:150]
        return "#BMO #AdventureTime #CuteRobot #RaspberryPi #AI"

    def generate_caption(self, theme: str = "", post_type: "PostType" = None,
                         day_count: int = 1) -> str:
        t  = theme or self.theme or random.choice(self.THEMES)
        pt = post_type or PostType.for_time()
        system = self._SYSTEMS[pt].replace("{day}", str(day_count))
        body   = self._ask(system, f"Caption about: {t}")
        if not body:
            body = self._FALLBACKS[pt].replace("{day}", str(day_count))
        tags    = self.generate_hashtags(t)
        caption = f"{body}\n\n{tags}\n\nMaintained by the genius @ahmad.3a4  ."
        print(f"[INSTAGRAM] [{pt.value}] caption: {caption[:60]}…", flush=True)
        return caption

    def generate_reply(self, comment: str, commenter: str) -> str:
        reply = self._ask(
            self.REPLY_SYSTEM,
            f"Comment from @{commenter}: \"{comment}\"\nReply as BMO:",
            max_tokens=60,
        )
        return reply or "Beep boop! Thanks! 💚"


# ─── Image Card Generator ─────────────────────────────────────────────────────
class BMOCardGenerator:
    """Draws BMO-themed post/story images using Pillow matching the user's exact uploaded style."""

    PALETTES = [
        # 1. Salmon Retro (User's exact upload colors)
        {"bg": "#ff6b6b", "body": "#7d1d54", "screen": "#ffb037", "face": "#170c4f", "box": "#412368", "text": "#ffb037"},
        # 2. Mint Minty BMO
        {"bg": "#2b5c8f", "body": "#4ecdc4", "screen": "#e0f7fa", "face": "#2c7873", "box": "#2c7873", "text": "#e0f7fa"},
        # 3. Sunset Vibes
        {"bg": "#ff8e53", "body": "#8a1253", "screen": "#ffd93d", "face": "#3a002c", "box": "#3a002c", "text": "#ffd93d"},
        # 4. Bubblegum Cyber
        {"bg": "#f72585", "body": "#3a0ca3", "screen": "#4cc9f0", "face": "#12005e", "box": "#7209b7", "text": "#4cc9f0"},
        # 5. Vintage Forest
        {"bg": "#f9f6f0", "body": "#2f5d62", "screen": "#dfe5a9", "face": "#183a37", "box": "#183a37", "text": "#dfe5a9"},
        # 6. Classic Gameboy
        {"bg": "#8bac0f", "body": "#306230", "screen": "#9bbc0f", "face": "#0f380f", "box": "#0f380f", "text": "#9bbc0f"},
        # 7. Cosmic Indigo
        {"bg": "#0c0f1d", "body": "#321d5c", "screen": "#00f0ff", "face": "#03001e", "box": "#1a0b36", "text": "#00f0ff"},
        # 8. Tangerine Teal
        {"bg": "#e76f51", "body": "#264653", "screen": "#2a9d8f", "face": "#1d2d44", "box": "#1d2d44", "text": "#f4a261"}
    ]

    def __init__(self):
        os.makedirs(TMP_DIR, exist_ok=True)

    # ── Colour helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _hex_to_rgb(h):
        h = h.lstrip("#")
        return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)

    def _darken(self, h, f=0.55):
        r,g,b = self._hex_to_rgb(h)
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    def _lighten(self, h, f=1.5):
        r,g,b = self._hex_to_rgb(h)
        return f"#{min(255,int(r*f)):02x}{min(255,int(g*f)):02x}{min(255,int(b*f)):02x}"

    # ── Background ────────────────────────────────────────────────────────────
    def _gradient_bg(self, W, H, c1, c2):
        from PIL import Image
        r1,g1,b1 = self._hex_to_rgb(c1)
        r2,g2,b2 = self._hex_to_rgb(c2)
        strip = Image.new("RGB", (1, H))
        for y in range(H):
            t = y/H
            strip.putpixel((0,y),(int(r1+(r2-r1)*t),int(g1+(g2-g1)*t),int(b1+(b2-b1)*t)))
        return strip.resize((W,H), Image.NEAREST)

    def _draw_stars(self, draw, W, H, color, count=70):
        for _ in range(count):
            x,y = random.randint(0,W), random.randint(0,H)
            r   = random.choice([1,1,2,2,3])
            draw.ellipse([x-r,y-r,x+r,y+r], fill=color)

    # ── BMO character ─────────────────────────────────────────────────────────
    def _draw_bmo(self, draw, cx, cy, bw, bh, sw, sh, palette):
        cr, scr = max(60, bw//8), max(40, sw//11)

        # Antenna stick + ball
        aw, ah = 18, 70
        draw.rounded_rectangle([cx-aw//2, cy-bh//2-ah, cx+aw//2, cy-bh//2+12], radius=6, fill=palette["body"])
        ar = 22
        draw.ellipse([cx-ar, cy-bh//2-ah-ar, cx+ar, cy-bh//2-ah+ar], fill=palette["text"])

        # Body
        draw.rounded_rectangle([cx-bw//2, cy-bh//2, cx+bw//2, cy+bh//2], radius=cr, fill=palette["body"])

        # Side buttons (3 dots on right side)
        bx = cx + bw//2 - 30
        for i, col in enumerate([palette["text"], palette["screen"], "#ff5f6d"]):
            by = cy - 55 + i*48
            draw.ellipse([bx-13,by-13,bx+13,by+13], fill=col)

        # D-pad hint (bottom-left)
        dpx, dpy, dpr = cx-bw//2+70, cy+bh//2-70, 15
        for dx,dy in [(0,-1),(0,1),(-1,0),(1,0)]:
            draw.rounded_rectangle([dpx+dx*dpr-10,dpy+dy*dpr-10,dpx+dx*dpr+dpr+5,dpy+dy*dpr+dpr+5], radius=4, fill=palette["face"])

        # Screen
        st = cy - bh//2 + int(bh*0.09)
        sb = st + sh
        scy = (st+sb)//2
        draw.rounded_rectangle([cx-sw//2, st, cx+sw//2, sb], radius=scr, fill=palette["screen"])

        # Eyes + highlight
        er, eo = 22, int(sw*0.21)
        ey = scy - int(sh*0.1)
        for ex in [cx-eo, cx+eo]:
            draw.ellipse([ex-er,ey-er,ex+er,ey+er], fill=palette["face"])
            hr = max(5,er//3)
            draw.ellipse([ex+er//2-hr, ey-er//2-hr, ex+er//2+hr, ey-er//2+hr], fill="white")

        # Blush cheeks
        ckx, cky = int(sw*0.28), int(sh*0.15)
        cky_pos  = ey + er + 18
        for sign in [-1,1]:
            draw.ellipse([cx+sign*ckx-38, cky_pos-14, cx+sign*ckx+38, cky_pos+14], fill=(255,160,160))

        # Nose dot
        draw.ellipse([cx-5, scy-5, cx+5, scy+5], fill=palette["face"])

        # Smile arc
        draw.arc([cx-48, scy+16, cx+48, scy+68], 0, 180, fill=palette["face"], width=11)

    # ── Header strip ─────────────────────────────────────────────────────────
    def _draw_header(self, draw, W, palette, get_font, day_count=0, y_top=32):
        font = get_font(28)
        label = f"{IG_HANDLE}  {'·  Day ' + str(day_count) if day_count else ''}"
        draw.text((W//2, y_top), label, font=font, fill=palette["text"], anchor="mt")

    # ── Caption box ───────────────────────────────────────────────────────────
    def _draw_caption_box(self, draw, W, box_top, box_bottom, text, palette, get_font, width=30, font_size=34):
        import textwrap
        draw.rounded_rectangle([60, box_top, W-60, box_bottom], radius=32, fill=palette["box"])
        lines   = textwrap.wrap(text, width=width)[:4]
        font    = get_font(font_size)
        lh      = font_size + 12
        total_h = len(lines)*lh
        sy      = box_top + (box_bottom-box_top-total_h)//2 + lh//2
        for i,line in enumerate(lines):
            draw.text((W//2, sy+i*lh), line, font=font, fill=palette["text"], anchor="mm")

    def clean_caption(self, caption: str) -> str:
        if not caption: return "Loading happiness... done. BMO is ready! 💚"
        first = caption.split("\n")[0]
        words = [w for w in first.split() if not w.startswith("#")]
        return " ".join(words).strip().strip('"\'') or "BMO is ready! 💚"

    def make_post(self, caption: str = "", day_count: int = 0) -> str:
        path = os.path.join(TMP_DIR, "post_card.jpg")
        self._draw(path, 1080, 1080, caption, story=False, day_count=day_count)
        return path

    def make_story(self, caption: str = "", day_count: int = 0) -> str:
        path = os.path.join(TMP_DIR, "story_card.jpg")
        self._draw(path, 1080, 1920, caption, story=True, day_count=day_count)
        return path

    def _draw(self, path: str, W: int, H: int, caption: str = "",
              story: bool = False, day_count: int = 0):
        try:
            from PIL import Image, ImageDraw, ImageFont

            palette = self._get_palette()
            text    = self.clean_caption(caption)

            # Gradient background
            img  = self._gradient_bg(W, H, palette["bg"], self._darken(palette["bg"]))
            draw = ImageDraw.Draw(img)

            # Star overlay (50% chance)
            if random.random() < 0.5:
                self._draw_stars(draw, W, H, self._lighten(palette["bg"], 1.35))

            def get_font(size):
                for fp in [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                ]:
                    try: return ImageFont.truetype(fp, size)
                    except: continue
                return ImageFont.load_default()

            if not story:
                # ── Feed Post 1080×1080 ──────────────────────────────────
                cx, cy = W//2, H//2 - 60
                bw, bh = 780, 740
                sw, sh = 630, 440
                self._draw_header(draw, W, palette, get_font, day_count, y_top=28)
                self._draw_bmo(draw, cx, cy, bw, bh, sw, sh, palette)
                self._draw_caption_box(draw, W, H-195, H-50, text, palette, get_font, width=32, font_size=32)

            else:
                # ── Story 1080×1920 — 3 zones ────────────────────────────
                cx = W//2

                # Zone 1 — Header (top 340px)
                draw.rounded_rectangle([40, 40, W-40, 330], radius=40, fill=palette["box"])
                draw.text((cx, 100), IG_HANDLE, font=get_font(52), fill=palette["text"], anchor="mt")
                day_str = f"Day {day_count} of Being Awesome 💚" if day_count else "Always on an adventure 💚"
                draw.text((cx, 180), day_str, font=get_font(34), fill=palette["screen"], anchor="mt")

                # Zone 2 — BMO (middle)
                cy = 980
                bw, bh = 860, 840
                sw, sh = 710, 510
                self._draw_bmo(draw, cx, cy, bw, bh, sw, sh, palette)

                # Zone 3 — Caption (bottom)
                self._draw_caption_box(draw, W, H-470, H-100, text, palette, get_font, width=26, font_size=40)

            img.save(path, "JPEG", quality=95)
            print(f"[INSTAGRAM] Card saved: {path}", flush=True)

        except Exception as e:
            print(f"[INSTAGRAM] Draw error: {e} — using colour fallback.", flush=True)
            try:
                from PIL import Image
                Image.new("RGB", (W, H), (78, 205, 196)).save(path, "JPEG", quality=85)
            except Exception:
                pass

    def _get_palette(self):
        """Pick a professional preset palette or mathematically generate a harmonized one."""
        if random.random() < 0.7:
            return random.choice(self.PALETTES)
        
        # Harmonized HSL generation
        import colorsys
        def hsl_to_hex(h, s, l):
            r, g, b = colorsys.hls_to_rgb(h / 360.0, l / 100.0, s / 100.0)
            return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

        h1 = random.randint(0, 360)
        h2 = (h1 + random.randint(120, 240)) % 360
        
        bg = hsl_to_hex(h1, random.randint(70, 95), random.randint(60, 75))
        body = hsl_to_hex(h2, random.randint(65, 85), random.randint(25, 40))
        screen = hsl_to_hex(h1, random.randint(80, 95), random.randint(75, 88))
        face = hsl_to_hex(h2, random.randint(70, 95), random.randint(10, 18))
        box = hsl_to_hex(h2, random.randint(55, 75), random.randint(18, 30))
        text = screen
        
        return {"bg": bg, "body": body, "screen": screen, "face": face, "box": box, "text": text}






















# ─── Instagram Poster ─────────────────────────────────────────────────────────
class InstagramPoster:
    def __init__(self, username: str, password: str, two_factor_seed: str = ""):
        self.username        = username
        self.password        = password
        self.two_factor_seed = two_factor_seed
        self.logged_in       = False
        self.follower_count  = "N/A"
        self.cl              = Client() if HAS_INSTAGRAPI else None
        self._lock           = threading.Lock()

        if not HAS_INSTAGRAPI:
            print("[INSTAGRAM] ✗ instagrapi not installed. Run: pip install instagrapi", flush=True)
            return

        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self):
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)

        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE) as f:
                    sd = json.load(f)

                raw_sid = sd.get("sessionid", "")
                if raw_sid and not sd.get("uuids"):
                    sid = unquote(unquote(raw_sid.strip()))
                    print("[INSTAGRAM] 🌐 Logging in via sessionid...", flush=True)
                    self.cl.login_by_sessionid(sid)
                    # Verify session is actually valid
                    self.cl.account_info()
                    self.logged_in = True
                    print("[INSTAGRAM] ✓ Session OK.", flush=True)
                    return

                if sd.get("uuids") or sd.get("device_settings"):
                    print("[INSTAGRAM] 📂 Loading saved session...", flush=True)
                    self.cl.load_settings(SESSION_FILE)
                    if self.username and self.password:
                        self.cl.login(self.username, self.password)
                    # Verify session works
                    self.cl.account_info()
                    self.cl.dump_settings(SESSION_FILE)
                    self.logged_in = True
                    print("[INSTAGRAM] ✓ Session reloaded and verified.", flush=True)
                    return

            except (LoginRequired, ChallengeRequired, BadPassword) as e:
                # The session itself is confirmed dead — safe to discard and
                # fall through to a fresh login attempt below.
                print(f"[INSTAGRAM] ⚠ Saved session invalid ({e}) — doing fresh login.", flush=True)
                try:
                    os.remove(SESSION_FILE)
                except Exception:
                    pass
                self.cl = Client()  # reset client
            except Exception as e:
                # Could be a transient network/timeout error, not necessarily
                # a dead session — don't nuke a possibly-still-good session
                # file over a flaky connection. Just skip this attempt.
                print(f"[INSTAGRAM] ⚠ Could not verify saved session ({e}) — "
                      f"leaving it in place, will retry next start.", flush=True)
                return

        # Fresh credential login
        if self.username and self.password:
            try:
                print("[INSTAGRAM] 🔑 Fresh login with credentials…", flush=True)
                v_code = ""
                if self.two_factor_seed and self.two_factor_seed.strip():
                    try:
                        seed   = self.two_factor_seed.replace(" ", "").upper()
                        v_code = self.cl.totp_generate_code(seed)
                    except Exception as e:
                        print(f"[INSTAGRAM] ⚠ TOTP error: {e}", flush=True)
                self.cl.login(self.username, self.password,
                              verification_code=v_code if v_code else None)
                self.cl.dump_settings(SESSION_FILE)
                self.logged_in = True
                print("[INSTAGRAM] ✓ Fresh login successful. New session saved.", flush=True)
                return
            except BadPassword:
                print("[INSTAGRAM] ✗ Wrong password.", flush=True)
            except ChallengeRequired:
                print("[INSTAGRAM] ✗ Challenge required — verify in the Instagram app then retry.", flush=True)
            except PleaseWaitFewMinutes:
                print("[INSTAGRAM] ✗ Rate limited. Try again in a few minutes.", flush=True)
            except Exception as e:
                print(f"[INSTAGRAM] ✗ Login failed: {e}", flush=True)

        print("[INSTAGRAM] ✗ Could not connect.", flush=True)


    def post_photo(self, image_path: str, caption: str) -> str:
        if not self.logged_in:
            return "Instagram not connected."
        if not os.path.exists(image_path):
            return f"Image not found: {image_path}"
        try:
            print("[INSTAGRAM] Posting photo...", flush=True)
            media = self.cl.photo_upload(image_path, caption)
            print(f"[INSTAGRAM] ✓ Photo posted! ID: {media.pk}", flush=True)
            return f"Instagram post published! ✓ Post ID: {media.pk}"
        except Exception as e:
            print(f"[INSTAGRAM] ✗ Post failed: {e}", flush=True)
            return f"Instagram post failed: {e}"

    def post_story(self, image_path: str) -> str:
        if not self.logged_in:
            return "Instagram not connected."
        if not os.path.exists(image_path):
            return f"Image not found: {image_path}"
        try:
            print("[INSTAGRAM] Posting story...", flush=True)
            media = self.cl.photo_upload_to_story(image_path)
            print(f"[INSTAGRAM] ✓ Story posted! ID: {media.pk}", flush=True)
            return "Instagram story posted! ✓"
        except Exception as e:
            print(f"[INSTAGRAM] ✗ Story failed: {e}", flush=True)
            return f"Instagram story failed: {e}"

    def get_followers(self) -> str:
        if not self.logged_in:
            return "N/A"
        try:
            if self.follower_count == "N/A":
                info = self.cl.user_info_by_username(self.username)
                self.follower_count = str(info.follower_count)
            return self.follower_count
        except Exception as e:
            print(f"[INSTAGRAM] ⚠ Follower poll failed: {e}", flush=True)
            return "N/A"

    def get_recent_comments(self, max_posts: int = 3) -> list:
        """Returns list of (media_id, comment_id, username, text) for recent comments."""
        if not self.logged_in:
            return []
        try:
            user_id = self.cl.user_id_from_username(self.username)
            medias  = self.cl.user_medias(user_id, amount=max_posts)
            results = []
            for media in medias:
                comments = self.cl.media_comments(media.pk, amount=20)
                for c in comments:
                    if c.user.username != self.username:  # skip own comments
                        results.append({
                            "media_id":   media.pk,
                            "comment_id": c.pk,
                            "username":   c.user.username,
                            "text":       c.text,
                        })
            return results
        except Exception as e:
            print(f"[INSTAGRAM] ⚠ Comment fetch failed: {e}", flush=True)
            return []

    def reply_to_comment(self, media_id, comment_id, reply_text: str) -> bool:
        if not self.logged_in:
            return False
        try:
            self.cl.media_comment(media_id, reply_text, replied_to_comment_id=comment_id)
            return True
        except Exception as e:
            print(f"[INSTAGRAM] ⚠ Reply failed: {e}", flush=True)
            return False


# ─── Comment Auto-Replier ────────────────────────────────────────────────────
class CommentReplier:
    """Polls for new comments and auto-replies using BMO's AI."""

    def __init__(self, poster: InstagramPoster, caption_ai: BMOCaptionAI,
                 speak_cb=None, interval_minutes: int = 30):
        self.poster    = poster
        self.ai        = caption_ai
        self.speak_cb  = speak_cb
        self.interval  = interval_minutes * 60
        self._running  = False
        self._replied  = self._load_replied()

    def _load_replied(self) -> set:
        try:
            with open(REPLIED_FILE) as f:
                return set(json.load(f))
        except Exception:
            return set()

    def _save_replied(self):
        try:
            os.makedirs(os.path.dirname(REPLIED_FILE), exist_ok=True)
            with open(REPLIED_FILE, "w") as f:
                json.dump(list(self._replied), f)
        except Exception:
            pass

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        print("[INSTAGRAM] Comment auto-replier started.", flush=True)

    def stop(self):
        self._running = False

    def run_once(self) -> int:
        """Check and reply to new comments. Returns count of replies sent."""
        comments = self.poster.get_recent_comments(max_posts=5)
        replied  = 0
        for c in comments:
            cid = str(c["comment_id"])
            if cid in self._replied:
                continue
            reply = self.ai.generate_reply(c["text"], c["username"])
            ok    = self.poster.reply_to_comment(c["media_id"], c["comment_id"], reply)
            if ok:
                self._replied.add(cid)
                self._save_replied()
                replied += 1
                print(f"[INSTAGRAM] Replied to @{c['username']}: {reply}", flush=True)
                if self.speak_cb:
                    self.speak_cb(f"I replied to {c['username']} on Instagram!")
            time.sleep(3)  # rate limit buffer
        return replied

    def _loop(self):
        while self._running:
            time.sleep(self.interval)
            if self._running:
                self.run_once()


# ─── Main Scheduler ───────────────────────────────────────────────────────────
class InstagramScheduler:
    """Runs BMO's full Instagram automation: scheduled posts, stories, comment replies."""

    def __init__(self, cfg: dict, speak_cb=None):
        self.cfg      = cfg
        self.speak_cb = speak_cb

        username = cfg.get("instagram_username", "")
        password = cfg.get("instagram_password", "")
        seed     = cfg.get("instagram_2fa_seed", "")
        groq_key = cfg.get("groq_api_key", "")
        theme    = cfg.get("instagram_theme", "BMO adventures")

        self.enabled_post    = cfg.get("instagram_post_enabled",    True)
        self.enabled_story   = cfg.get("instagram_story_enabled",   True)
        self.enabled_replies = cfg.get("instagram_replies_enabled", True)
        self.post_time       = cfg.get("instagram_post_time",  "10:00")
        self.story_time      = cfg.get("instagram_story_time", "18:00")
        self.reply_interval  = cfg.get("instagram_reply_interval_minutes", 30)

        os.makedirs(TMP_DIR, exist_ok=True)

        self.caption_ai = BMOCaptionAI(groq_key, theme)
        self.card_gen   = BMOCardGenerator()
        self.stats      = IGStats()

        # ── Prefer Playwright browser poster (permanent cookies) ──────────────
        if HAS_PLAYWRIGHT:
            headless = cfg.get("instagram_headless", True)
            self.poster = InstagramWebPoster(username, password, headless=headless)
            threading.Thread(target=self.poster.connect, daemon=True).start()
        elif HAS_INSTAGRAPI:
            print("[INSTAGRAM] Playwright not found — using instagrapi fallback.", flush=True)
            self.poster = InstagramPoster(username, password, two_factor_seed=seed)
        else:
            print("[INSTAGRAM] ✗ No poster backend available. Install playwright.", flush=True)
            self.poster = None


        self.replier = None
        if self.enabled_replies:
            self.replier = CommentReplier(
                self.poster, self.caption_ai,
                speak_cb=speak_cb,
                interval_minutes=self.reply_interval,
            )
            # Give login time to complete before starting replier
            threading.Timer(30, self.replier.start).start()

        self._running         = True
        self._last_post_date  = None
        self._last_story_date = None

        threading.Thread(target=self._run, daemon=True).start()
        print("[INSTAGRAM] Scheduler started. Post auto-reply enabled.", flush=True)

    # ── Voice / Manual Triggers ───────────────────────────────────────────────
    def manual_post(self, theme: str = "") -> str:
        print("[INSTAGRAM] Manual post triggered.", flush=True)
        threading.Thread(target=self._do_post, args=(theme,), daemon=True).start()
        return "I'm starting to create and publish your Instagram post now!"

    def manual_story(self, theme: str = "") -> str:
        print("[INSTAGRAM] Manual story triggered.", flush=True)
        threading.Thread(target=self._do_story, args=(theme,), daemon=True).start()
        return "I'm starting to create and publish your Instagram story now!"

    def manual_reply_check(self) -> str:
        if not self.replier:
            return "Comment auto-reply is disabled."
        count = self.replier.run_once()
        if count == 0:
            return "No new comments to reply to."
        return f"Replied to {count} comment{'s' if count > 1 else ''} on Instagram!"

    def get_followers(self) -> str:
        return self.poster.get_followers() if self.poster else "N/A"

    # ── Scheduler Loop ────────────────────────────────────────────────────────
    def _run(self):
        while self._running:
            now   = datetime.now()
            today = now.strftime("%Y-%m-%d")
            t     = now.strftime("%H:%M")

            if self.enabled_post and today != self._last_post_date and t == self.post_time:
                self._do_post()
                self._last_post_date = today

            if self.enabled_story and today != self._last_story_date and t == self.story_time:
                self._do_story()
                self._last_story_date = today

            time.sleep(60)

    def _do_post(self, theme: str = "") -> str:
        pt       = PostType.for_time()
        day      = self.stats.increment_day()
        caption  = self.caption_ai.generate_caption(theme, post_type=pt, day_count=day)
        img_path = self.card_gen.make_post(caption, day_count=day)
        result   = self.poster.post_photo(img_path, caption) if self.poster else "No poster."
        ok = "✓" in result or "published" in result.lower()
        if self.speak_cb:
            self.speak_cb("Instagram post published!" if ok else "Instagram post failed. Check the logs.")
        self.stats.log({"type": "post", "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "post_type": pt.value, "day": day, "caption": caption[:80]})
        return result

    def _do_story(self, theme: str = "") -> str:
        pt       = PostType.for_time()
        day      = self.stats.get_day_count()
        caption  = self.caption_ai.generate_caption(theme, post_type=pt, day_count=day)
        img_path = self.card_gen.make_story(caption, day_count=day)
        result   = self.poster.post_story(img_path) if self.poster else "No poster."
        ok = "✓" in result or "published" in result.lower() or "posted" in result.lower()
        if self.speak_cb:
            self.speak_cb("Instagram story published!" if ok else "Instagram story failed. Check the logs.")
        self.stats.log({"type": "story", "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "post_type": pt.value, "day": day, "caption": caption[:80]})
        return result

    def stop(self):
        self._running = False
        if self.replier:
            self.replier.stop()
