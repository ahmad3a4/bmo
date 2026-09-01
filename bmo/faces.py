#!/usr/bin/env python3
"""
BMO Faces — Fluid, parameter-based emotional face system.
Upgraded to feature smooth interpolation, micro-expressions (blinking, breathing, jitter),
and a more "alive" feel while retaining the original minimal aesthetic.
"""

import math
import random
import colorsys


def boost_color(hex_color, sat_mult=1.0, val_mult=1.0):
    """Scale a #rrggbb color's saturation/brightness — cheap compensation for
    TFT panels that wash out mid-saturation colors. 1.0 = unchanged."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = max(0.0, min(1.0, s * sat_mult))
    v = max(0.0, min(1.0, v * val_mult))
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"

# ─── State → emotion mapping ─────────────────────────────────────────────────
STATE_EMOTION = {
    "idle":       "idle",
    "listen":     "listening",
    "think":      "thinking",
    "speak":      "speaking",
    "warmup":     "warmup",
    "error":      "error",
    "capturing":  "camera",
}

RESPONSE_EMOTIONS = {
    "in_love":  ["love", "heart", "beautiful", "sweet", "adorable"],
    "laugh":    ["haha", "lol", "funny", "hilarious", "laugh"],
    "happy":    ["great", "awesome", "sure", "wonderful", "perfect", "nice", "yay", "yes"],
    "excited":  ["amazing", "incredible", "wow", "fantastic", "best"],
    "sad":      ["sorry", "unfortunate", "can't", "unable", "sad", "miss"],
    "confused": ["hmm", "unclear", "not sure", "don't know", "what"],
    "angry":    ["stop", "error", "wrong", "bad", "no!"],
    "upset":    ["upset", "mad", "frustrated", "annoyed"],
    "music":    ["playing", "spotify", "music", "song", "track", "playlist"],
    "tv":       ["tv", "television", "channel", "volume", "hdmi"],
    "meme":     ["meme", "joke"],
    "sleep":    ["sleep", "goodnight", "bye", "shutdown"],
    "rude":     [],   # triggered explicitly, not by keywords
}

# Direct [TAG] → emotion map (LLM emits these tags)
TAG_EMOTIONS = {
    "laugh":     "laugh",
    "lol":       "laugh",
    "haha":      "laugh",
    "happy":     "happy",
    "smile":     "happy",
    "angry":     "angry",
    "mad":       "angry",
    "sad":       "sad",
    "cry":       "sad",
    "confused":  "confused",
    "think":     "confused",
    "excited":   "excited",
    "love":      "in_love",
    "heart":     "in_love",
    "calm":      "happy",
    "sarcasm":   "confused",
    "sarcastic": "confused",
    "shocked":   "excited",
    "surprise":  "excited",
    "sleepy":    "sleep",
    "sleep":     "sleep",
    "music":     "music",
    "tv":        "tv",
    "meme":      "meme",
}

def emotion_from_reply(text: str) -> str:
    import re
    # First: check for [TAG] format directly — most reliable
    tags = re.findall(r"\[([A-Za-z]+)\]", text)
    for tag in tags:
        mapped = TAG_EMOTIONS.get(tag.lower())
        if mapped:
            return mapped
    # Fallback: keyword scan
    low = text.lower()
    for emotion, keywords in RESPONSE_EMOTIONS.items():
        if any(k in low for k in keywords):
            return emotion
    return None

def strip_emotion_tags(text: str) -> str:
    """Remove [TAG] tokens from text before TTS."""
    import re
    return re.sub(r"\s*\[[A-Za-z]+\]\s*", " ", text).strip()

def lerp(a, b, t):
    return a + (b - a) * t

class BMOFaces:
    C_SCREEN_BASE = "#5bd68f"  # Richer, glowing mint green
    C_SCREEN_DARK = "#4abf7d"
    C_EYE      = "#0a1a10"   # Very dark green/black
    C_MOUTH    = "#0a1a10"
    C_RED      = "#ff3366"
    C_YELLOW   = "#ffcc00"
    C_BLUE     = "#33ccff"
    C_HEADBAND = "#3399ff"   # DJ headphones
    C_BG_DOT   = "#82D4A4"   # matches the canvas background (used for "off" pulse dots)

    # Every color above gets run through boost_color() at init time using
    # sat_boost/val_boost — a cheap way to compensate for a washed-out TFT
    # panel without hand-tuning every hex value.
    _PALETTE_ATTRS = ("C_SCREEN_BASE", "C_SCREEN_DARK", "C_EYE", "C_MOUTH",
                       "C_RED", "C_YELLOW", "C_BLUE", "C_HEADBAND", "C_BG_DOT")

    def __init__(self, canvas, base_dir=None, sat_boost=1.0, val_boost=1.0):
        self._canvas   = canvas
        if sat_boost != 1.0 or val_boost != 1.0:
            for attr in self._PALETTE_ATTRS:
                setattr(self, attr, boost_color(getattr(self, attr), sat_boost, val_boost))
        self._emotion  = "idle"
        self._pulse    = 0
        self._speaking = False
        self._mouth_volume = 0.0   # 0.0–1.0, driven by real audio level
        self._mouth_open   = 0.0   # smoothed mouth openness
        
        # State parameters for interpolation
        self.params = {
            "eye_l_y": -0.25, "eye_r_y": -0.25,
            "eye_l_x": -1.3, "eye_r_x": 1.3,
            "eye_l_type": 0.0, "eye_r_type": 0.0, # 0=arc_down, 1=arc_up, 2=dot, 3=line, 4=x, 5=heart, 6=star, 7=square, 8=lens
            "mouth_w": 0.55, "mouth_y": 0.65,
            "mouth_type": 0.0, # 0=line, 1=smile, 2=frown, 3=open, 4=wavy, 5=laugh
            "brow_l_ang": 0.0, "brow_r_ang": 0.0, # 0=none, 1=sad, 2=angry, 3=upset
            "tear": 0.0,
            "sweat": 0.0,
            "face_scale": 1.0,
            "bg_color_blend": 0.0, # 0=normal, 1=red (angry), -1=blue (sad)
        }
        self.target = dict(self.params)
        
        # Micro-animation state
        self._blink_timer = random.randint(30, 100)
        self._is_blinking = False
        self._blink_dur = 0
        self._eye_jitter_x = 0.0
        self._eye_jitter_y = 0.0
        
        print("[BMO FACES] Fluid Face System Online.", flush=True)

    def preload(self): pass

    def set_emotion(self, emotion: str):
        if emotion in RESPONSE_EMOTIONS or emotion in STATE_EMOTION.values():
            self._emotion = emotion

    def emotion_for_state(self, state: str) -> str:
        return STATE_EMOTION.get(state, "idle")

    def _set_targets(self, em: str):
        # Default targets
        t = self.target
        t["eye_l_y"] = -0.25; t["eye_r_y"] = -0.25
        t["eye_l_x"] = -1.3; t["eye_r_x"] = 1.3
        t["eye_l_type"] = 0.0; t["eye_r_type"] = 0.0
        t["mouth_w"] = 0.55; t["mouth_y"] = 0.65
        t["mouth_type"] = 0.0
        t["brow_l_ang"] = 0.0; t["brow_r_ang"] = 0.0
        t["tear"] = 0.0; t["face_scale"] = 1.0
        t["bg_color_blend"] = 0.0
        
        if em == "listening":
            t["eye_l_type"] = 2.0; t["eye_r_type"] = 2.0
            t["mouth_type"] = 3.0; t["mouth_w"] = 0.3
        elif em == "thinking":
            t["eye_r_type"] = 3.0 # squint
            t["eye_l_x"] = -1.1; t["eye_r_x"] = 1.1
            t["mouth_w"] = 0.3
        elif em == "speaking":
            t["eye_l_type"] = 2.0; t["eye_r_type"] = 2.0
            t["mouth_type"] = 3.0
            t["face_scale"] = 1.05
        elif em == "happy":
            t["eye_l_type"] = 1.0; t["eye_r_type"] = 1.0
            t["mouth_type"] = 1.0
        elif em == "laugh":
            t["eye_l_type"] = 1.0; t["eye_r_type"] = 1.0
            t["mouth_type"] = 5.0
            t["face_scale"] = 1.1
        elif em == "in_love":
            t["eye_l_type"] = 5.0; t["eye_r_type"] = 5.0
            t["mouth_type"] = 1.0
            t["bg_color_blend"] = 0.3 # slightly warmer
        elif em == "excited":
            t["eye_l_type"] = 6.0; t["eye_r_type"] = 6.0
            t["mouth_type"] = 1.0
            t["face_scale"] = 1.15
        elif em == "sad":
            t["eye_l_type"] = 0.0; t["eye_r_type"] = 0.0
            t["mouth_type"] = 2.0
            t["brow_l_ang"] = 1.0; t["brow_r_ang"] = 1.0
            t["tear"] = 1.0
            t["bg_color_blend"] = -0.5
        elif em == "angry":
            t["eye_l_type"] = 0.0; t["eye_r_type"] = 0.0
            t["mouth_type"] = 0.0; t["mouth_w"] = 0.35
            t["brow_l_ang"] = 2.0; t["brow_r_ang"] = 2.0
            t["bg_color_blend"] = 0.8 # red
        elif em == "upset":
            t["mouth_type"] = 2.0
            t["brow_l_ang"] = 3.0; t["brow_r_ang"] = 3.0
        elif em == "confused":
            t["eye_r_type"] = 3.0
            t["mouth_type"] = 4.0
        elif em == "error":
            t["eye_l_type"] = 4.0; t["eye_r_type"] = 4.0
            t["mouth_type"] = 0.0; t["mouth_w"] = 0.35
            t["bg_color_blend"] = 1.0
        elif em == "music":
            t["eye_l_type"] = 1.0; t["eye_r_type"] = 1.0
            t["mouth_type"] = 9.0  # Spectrogram DJ Equalizer Mouth!
            t["mouth_w"] = 0.65   # Wider mouth for equalizer
        elif em == "tv":
            t["eye_l_type"] = 7.0; t["eye_r_type"] = 7.0
        elif em == "meme":
            t["eye_l_type"] = 3.0; t["eye_r_type"] = 3.0
            t["mouth_type"] = 1.0; t["mouth_w"] = 0.4
        elif em == "sleep":
            t["eye_l_type"] = 3.0; t["eye_r_type"] = 3.0
            t["mouth_type"] = 1.0; t["mouth_w"] = 0.45
            t["eye_l_y"] = -0.15; t["eye_r_y"] = -0.15
        elif em == "camera":
            t["eye_r_type"] = 8.0
        elif em == "rude":
            # Just show fingers on sides — no background or face change
            pass

    def _update_micro_animations(self):
        # Blinking
        if self._blink_timer <= 0:
            if not self._is_blinking:
                self._is_blinking = True
                self._blink_dur = 4 # frames to stay closed
            else:
                self._blink_dur -= 1
                if self._blink_dur <= 0:
                    self._is_blinking = False
                    self._blink_timer = random.randint(40, 150)
        else:
            self._blink_timer -= 1

        # Jitter (looking around slightly)
        if random.random() < 0.02 and self._emotion == "idle":
            self._eye_jitter_x = random.uniform(-0.1, 0.1)
            self._eye_jitter_y = random.uniform(-0.05, 0.05)
        else:
            # slowly return to center
            self._eye_jitter_x = lerp(self._eye_jitter_x, 0.0, 0.1)
            self._eye_jitter_y = lerp(self._eye_jitter_y, 0.0, 0.1)

    def set_speaking(self, speaking: bool):
        """Call this when TTS starts/stops to drive mouth animation."""
        self._speaking = speaking
        if not speaking:
            self._mouth_volume = 0.0
            self._mouth_open   = 0.0

    def set_volume(self, vol: float):
        """Feed real-time audio volume (0.0–1.0) for lip sync."""
        self._mouth_volume = min(1.0, max(0.0, vol))

    def draw(self, canvas, cx: int, cy: int, pulse: int, emotion: str = None):
        self._pulse = pulse
        em = emotion or self._emotion
        # Keep _speaking flag — set externally, not derived from emotion name
        # so mouth animates regardless of which emotion face is showing

        self._set_targets(em)
        self._update_micro_animations()

        # Smoothly interpolate all parameters
        lerp_speed = 0.3
        for k in self.params:
            self.params[k] = lerp(self.params[k], self.target[k], lerp_speed)

        w = canvas.winfo_width()  or (cx * 2)
        h = canvas.winfo_height() or (cy * 2)
        U = min(w, h) / 5

        # --- Draw Background ---
        # Calculate background color blending
        blend = self.params["bg_color_blend"]
        if blend > 0.05:
            # Blend towards red
            r = int(lerp(0x5b, 0xff, blend))
            g = int(lerp(0xd6, 0x33, blend))
            b = int(lerp(0x8f, 0x33, blend))
            bg_col = f"#{r:02x}{g:02x}{b:02x}"
        elif blend < -0.05:
            # Blend towards blue
            blend_abs = abs(blend)
            r = int(lerp(0x5b, 0x55, blend_abs))
            g = int(lerp(0xd6, 0x99, blend_abs))
            b = int(lerp(0x8f, 0xff, blend_abs))
            bg_col = f"#{r:02x}{g:02x}{b:02x}"
        else:
            bg_col = self.C_SCREEN_BASE

        canvas.create_rectangle(0, 0, w, h, fill=bg_col, outline="")

        # Scanlines (subtle)
        if U > 10:
            step = int(max(4, U * 0.08))
            for y in range(0, h, step):
                canvas.create_line(0, y, w, y, fill=self.C_SCREEN_DARK, width=1, stipple="gray50")

        # --- Draw Face ---
        scale = self.params["face_scale"]
        # Breathing effect
        if em in ("idle", "sleep", "listening"):
            breathe = math.sin(pulse * 0.05) * 0.03
            scale += breathe
            
        SU = U * scale
        
        ex_l = cx + (self.params["eye_l_x"] + self._eye_jitter_x) * SU
        ey_l = cy + (self.params["eye_l_y"] + self._eye_jitter_y) * SU
        ex_r = cx + (self.params["eye_r_x"] + self._eye_jitter_x) * SU
        ey_r = cy + (self.params["eye_r_y"] + self._eye_jitter_y) * SU
        
        my = cy + self.params["mouth_y"] * SU

        # Draw left eye
        self._draw_eye(canvas, ex_l, ey_l, SU, self.params["eye_l_type"])
        # Draw right eye
        self._draw_eye(canvas, ex_r, ey_r, SU, self.params["eye_r_type"])
        
        # Draw mouth
        self._draw_mouth(canvas, cx, my, SU)
        
        # Draw brows
        self._draw_brows(canvas, ex_l, ey_l, ex_r, ey_r, SU)
        
        # Draw extras
        if self.params["tear"] > 0.1:
            t_val = self.params["tear"]
            t_anim = (self._pulse % 30) * SU * 0.04
            r = SU * 0.10 * t_val
            canvas.create_oval(ex_l - r, ey_l + SU*0.35 + t_anim,
                               ex_l + r, ey_l + SU*0.35 + t_anim + r*2,
                               fill=self.C_BLUE, outline="")
                               
        if em == "thinking":
            self._draw_thinking_dots(canvas, cx, my, SU)
        elif em == "excited":
            self._draw_excited_marks(canvas, cx, cy, SU)
        elif em == "confused":
            self._draw_confused_marks(canvas, ex_r, ey_r, SU)
        elif em == "music":
            self._draw_music_marks(canvas, cx, cy, SU)
        elif em == "sleep":
            self._draw_sleep_marks(canvas, ex_r, ey_r, SU)

        # --- Rude overlay: fingers beside the face, no background change ---
        if em == "rude":
            fsize = min(w, h) * 0.45
            # Left finger: left edge of screen
            self._draw_middle_finger_single(canvas, w * 0.13, cy, fsize)
            # Right finger: right edge of screen (flipped)
            self._draw_middle_finger_single(canvas, w * 0.87, cy, fsize)

    def _lw(self, U):
        return max(2, int(U * 0.12))

    def _draw_eye(self, c, x, y, U, type_val):
        if self._is_blinking:
            self._closed_eye(c, x, y, U)
            return

        # Snap to nearest type for shapes (no morphing between totally different shapes yet)
        t = round(type_val)
        
        if t == 0: # arc down (idle)
            r = U * 0.32
            x0, y0 = x - r, y - r * 0.5
            x1, y1 = x + r, y + r * 0.5
            c.create_arc(x0, y0, x1, y1, start=180, extent=180, style="arc", outline=self.C_EYE, width=self._lw(U))
        elif t == 1: # arc up (happy)
            r = U * 0.32
            x0, y0 = x - r, y - r * 0.5
            x1, y1 = x + r, y + r * 0.5
            c.create_arc(x0, y0, x1, y1, start=0, extent=180, style="arc", outline=self.C_EYE, width=self._lw(U))
        elif t == 2: # dot (listening/speaking)
            r = U * 0.22
            c.create_oval(x - r, y - r * 1.2, x + r, y + r * 1.2, fill=self.C_EYE, outline="")
        elif t == 3: # line (squint/meme/sleep)
            self._closed_eye(c, x, y, U)
        elif t == 4: # x (error)
            s = U * 0.28
            lw = self._lw(U)
            c.create_line(x-s, y-s, x+s, y+s, fill=self.C_EYE, width=lw, capstyle="round")
            c.create_line(x+s, y-s, x-s, y+s, fill=self.C_EYE, width=lw, capstyle="round")
        elif t == 5: # heart
            fs = max(10, int(U * 0.9))
            c.create_text(x, y, text="♥", fill=self.C_RED, font=("Arial", fs))
        elif t == 6: # star
            s = U * 0.38
            pts = []
            for i in range(5):
                a1 = math.radians(i * 72 - 90)
                a2 = math.radians(i * 72 - 90 + 36)
                pts.extend([x + s * math.cos(a1), y + s * math.sin(a1)])
                pts.extend([x + s*0.4 * math.cos(a2), y + s*0.4 * math.sin(a2)])
            c.create_polygon(pts, fill=self.C_YELLOW, outline="")
        elif t == 7: # square (tv)
            ew, eh = U * 0.30, U * 0.22
            c.create_rectangle(x - ew, y - eh, x + ew, y + eh, fill=self.C_EYE, outline="")
        elif t == 8: # lens (camera)
            lw = self._lw(U)
            r1, r2 = U*0.38, U*0.22
            c.create_oval(x - r1, y - r1, x + r1, y + r1, outline=self.C_EYE, width=lw, fill=self.C_SCREEN_BASE)
            c.create_oval(x - r2, y - r2, x + r2, y + r2, outline=self.C_EYE, width=max(1, lw-1), fill=self.C_SCREEN_BASE)

    def _closed_eye(self, c, x, y, U):
        r = U * 0.30
        c.create_line(x - r, y, x + r, y, fill=self.C_EYE, width=self._lw(U), capstyle="round")

    def _draw_mouth(self, c, cx, cy, U):
        t = round(self.params["mouth_type"])
        mw = self.params["mouth_w"]
        lw = self._lw(U)

        # ── Volume-driven lip sync ──────────────────────────────────────────
        # When speaking, ALL mouth types animate open/close with audio volume.
        # Smooth the raw volume to avoid jitter.
        if self._speaking:
            target_open = self._mouth_volume
            self._mouth_open = lerp(self._mouth_open, target_open, 0.35)
            open_f = self._mouth_open
        else:
            self._mouth_open = lerp(self._mouth_open, 0.0, 0.2)
            open_f = self._mouth_open

        # While speaking, force open-mouth regardless of emotion type,
        # so laugh/happy/etc still show mouth movement.
        if self._speaking and t not in (3, 5, 9):
            # Override to open-mouth shape while speaking
            hw = U * mw
            if open_f < 0.08:
                c.create_line(cx - hw, cy, cx + hw, cy, fill=self.C_MOUTH, width=lw, capstyle="round")
            else:
                hh = U * 0.20 * (0.3 + open_f * 0.8)
                c.create_arc(cx - hw, cy - hh * 0.3, cx + hw, cy + hh,
                             start=180, extent=180, fill=self.C_MOUTH, outline="")
            return

        if t == 0: # line
            hw = U * mw
            c.create_line(cx - hw, cy, cx + hw, cy, fill=self.C_MOUTH, width=lw, capstyle="round")
        elif t == 1: # smile
            sw, sh = U * mw, U * 0.35
            c.create_arc(cx - sw, cy - sh, cx + sw, cy + sh, start=200, extent=140, style="arc", outline=self.C_MOUTH, width=lw)
        elif t == 2: # frown
            sw, sh = U * mw, U * 0.3
            c.create_arc(cx - sw, cy, cx + sw, cy + sh * 2, start=20, extent=140, style="arc", outline=self.C_MOUTH, width=lw)
        elif t == 3: # open (speaking)
            hw = U * 0.45
            if open_f < 0.08:
                c.create_line(cx - hw, cy, cx + hw, cy, fill=self.C_MOUTH, width=lw, capstyle="round")
            else:
                hh = U * 0.22 * (0.3 + open_f * 0.8)
                c.create_arc(cx - hw, cy - hh * 0.3, cx + hw, cy + hh, start=180, extent=180, fill=self.C_MOUTH, outline="")
        elif t == 4: # wavy (confused — stays wavy)
            pts = []
            for i in range(7):
                pts += [cx - U*0.55 + i * U*0.18, cy + (U*0.08 if i % 2 == 0 else -U*0.08)]
            c.create_line(pts, fill=self.C_MOUTH, width=lw, smooth=True, capstyle="round")
        elif t == 5: # laugh — animates open size with volume
            hw = U * 0.65
            hh = U * (0.25 + open_f * 0.30)
            c.create_arc(cx - hw, cy - hh * 0.2, cx + hw, cy + hh,
                         start=180, extent=180, style="chord", fill=self.C_MOUTH, outline="")
        elif t == 9: # Spectrogram DJ Equalizer Mouth!
            num_bars = 7
            bar_w = U * 0.12
            gap = U * 0.05
            for i in range(num_bars):
                offset = (i - (num_bars - 1) / 2) * (bar_w + gap)
                bx = cx + offset
                # Bouncing formula for visualizer heights
                freq_factor = 0.5 + 0.3 * math.sin(self._pulse * 0.4 + i * 1.6)
                jitter = 0.2 * math.cos(self._pulse * 0.95 + i * 2.7)
                bar_h = U * 0.55 * max(0.15, min(1.0, freq_factor + jitter))
                by0 = cy - bar_h / 2
                by1 = cy + bar_h / 2
                c.create_line(bx, by0, bx, by1, fill=self.C_MOUTH, width=int(bar_w), capstyle="round")

    def _draw_brows(self, c, ex_l, ey_l, ex_r, ey_r, U):
        lw = max(2, int(U * 0.13))
        # Left brow
        lang = round(self.params["brow_l_ang"])
        if lang == 1: # sad
            c.create_line(ex_l - U*0.4, ey_l - U*0.55, ex_l + U*0.4, ey_l - U*0.80, fill=self.C_EYE, width=lw, capstyle="round")
        elif lang == 2: # angry
            c.create_line(ex_l - U*0.5, ey_l - U*0.75, ex_l + U*0.35, ey_l - U*0.40, fill=self.C_EYE, width=lw, capstyle="round")
        elif lang == 3: # upset
            c.create_line(ex_l - U*0.45, ey_l - U*0.65, ex_l + U*0.30, ey_l - U*0.38, fill=self.C_EYE, width=lw, capstyle="round")
            
        # Right brow
        rang = round(self.params["brow_r_ang"])
        if rang == 1: # sad
            c.create_line(ex_r - U*0.4, ey_r - U*0.80, ex_r + U*0.4, ey_r - U*0.55, fill=self.C_EYE, width=lw, capstyle="round")
        elif rang == 2: # angry
            c.create_line(ex_r - U*0.35, ey_r - U*0.40, ex_r + U*0.5, ey_r - U*0.75, fill=self.C_EYE, width=lw, capstyle="round")
        elif rang == 3: # upset
            c.create_line(ex_r - U*0.30, ey_r - U*0.38, ex_r + U*0.45, ey_r - U*0.65, fill=self.C_EYE, width=lw, capstyle="round")

    def _draw_thinking_dots(self, c, cx, my, U):
        for i in range(3):
            col = self.C_EYE if i <= ((self._pulse // 2) % 3) else self.C_BG_DOT
            r = U * 0.07
            dx = cx + (i - 1) * U * 0.35
            c.create_oval(dx - r, my + U*0.5 - r, dx + r, my + U*0.5 + r, fill=col, outline="")

    def _draw_excited_marks(self, c, cx, cy, U):
        off = U*0.08 if (self._pulse // 2) % 8 < 4 else 0
        fs = max(10, int(U * 0.55))
        ex = U * 1.3
        ey = -U * 0.25
        c.create_text(cx - ex - U*0.7, cy + ey - U*0.6 - off, text="!", fill=self.C_YELLOW, font=("Arial", fs, "bold"))
        c.create_text(cx + ex + U*0.7, cy + ey - U*0.6 - off, text="!", fill=self.C_YELLOW, font=("Arial", fs, "bold"))

    def _draw_confused_marks(self, c, ex_r, ey_r, U):
        off = U*0.06 if (self._pulse // 2) % 8 < 4 else 0
        fs = max(10, int(U * 0.55))
        c.create_text(ex_r + U*0.65, ey_r - U*0.65 - off, text="?", fill=self.C_EYE, font=("Arial", fs, "bold"))

    def _draw_music_marks(self, c, cx, cy, U):
        # ── Draw DJ Headphones ──
        hx_l = cx - U * 2.1
        hx_r = cx + U * 2.1
        hy = cy - U * 0.25  # Ear level is eye level
        headband_color = self.C_HEADBAND  # Gorgeous retro blue headphones!
        
        # Headband arch
        c.create_arc(hx_l - U*0.2, hy - U*1.7, hx_r + U*0.2, hy + U*0.5,
                     start=0, extent=180, style="arc", outline=headband_color, width=int(U * 0.2))
        
        # Left Earcup
        c.create_line(hx_l, hy - U*0.4, hx_l, hy + U*0.4, fill=headband_color, width=int(U * 0.55), capstyle="round")
        c.create_line(hx_l + U*0.1, hy - U*0.3, hx_l + U*0.1, hy + U*0.3, fill=self.C_MOUTH, width=int(U * 0.25), capstyle="round")
        
        # Right Earcup
        c.create_line(hx_r, hy - U*0.4, hx_r, hy + U*0.4, fill=headband_color, width=int(U * 0.55), capstyle="round")
        c.create_line(hx_r - U*0.1, hy - U*0.3, hx_r - U*0.1, hy + U*0.3, fill=self.C_MOUTH, width=int(U * 0.25), capstyle="round")

        # ── Floating Music Notes ──
        emojis = ["🎵", "🎶", "🎼"]
        fs = max(12, int(U * 0.6))
        for i in range(len(emojis)):
            float_up = (self._pulse * 1.2 + i * 50) % (U * 3.5)
            drift = math.sin(self._pulse * 0.08 + i) * U * 0.4
            x_pos = cx - U * 2.2 + (i * U * 0.9) + drift
            y_pos = cy - U * 0.8 - float_up
            if float_up < U * 3.2:
                c.create_text(x_pos, y_pos, text=emojis[i], font=("Arial", fs))

    def _draw_sleep_marks(self, c, ex_r, ey_r, U):
        fs = max(8, int(U * 0.42))
        for i, ch in enumerate(["z", "Z", "Z"]):
            off = (self._pulse * 2 + i * 18) % int(U * 2.5)
            c.create_text(ex_r + U*0.3 + i * U*0.25, ey_r - U*0.4 - off, text=ch, fill=self.C_EYE, font=("Arial", int(fs + i * fs * 0.3)))

    def _draw_middle_finger_single(self, c, ox, oy, size):
        """Draw one cartoon raised-middle-finger hand at (ox, oy)."""
        s   = size * 0.42
        col = "#f5c97a"
        drk = "#c8922a"
        lw  = max(2, int(s * 0.055))

        pw = s * 0.70    # palm half-width
        ph = s * 0.48    # palm height
        pt = oy - ph * 0.3   # palm top y (center the hand vertically)
        pb = pt + ph
        fw = s * 0.14    # each finger half-width

        # x-positions of 4 fingers: pinky, ring, middle, index
        fxs = [ox - pw*0.60, ox - pw*0.20, ox + pw*0.20, ox + pw*0.60]
        fhs = [s*0.14,        s*0.18,        s*0.65,        s*0.15]

        # Draw fingers behind palm
        for fx, fh in zip(fxs, fhs):
            top = pt - fh
            c.create_rectangle(fx - fw, top + fw, fx + fw, pt + ph*0.10,
                               fill=col, outline="")
            c.create_oval(fx - fw, top, fx + fw, top + fw*2,
                          fill=col, outline=drk, width=lw)
            c.create_line(fx - fw, top + fw, fx - fw, pt + ph*0.10, fill=drk, width=lw)
            c.create_line(fx + fw, top + fw, fx + fw, pt + ph*0.10, fill=drk, width=lw)
            if fh > s * 0.5:   # knuckle on middle finger
                kly = top + fh * 0.42
                c.create_line(fx - fw*0.7, kly, fx + fw*0.7, kly,
                              fill=drk, width=max(1, lw - 1))

        # Palm over finger bases
        c.create_rectangle(ox - pw, pt, ox + pw, pb, fill=col, outline="")
        c.create_rectangle(ox - pw, pt, ox + pw, pb, fill="", outline=drk, width=lw)

        # Finger divider lines at palm top
        for fx in fxs:
            c.create_line(fx, pt, fx, pt + ph*0.16, fill=drk, width=max(1, lw-1))

        # Thumb (left side)
        tx, ty = ox - pw + fw*0.2, pt + ph*0.40
        c.create_oval(tx - fw*1.2, ty - fw*0.7, tx + fw*0.4, ty + fw*0.7,
                      fill=col, outline=drk, width=lw)

    def _draw_middle_finger(self, c, cx, cy, size):
        """Legacy: two hands (kept for compatibility)."""
        gap = size * 0.28
        self._draw_middle_finger_single(c, cx - gap, cy, size * 0.6)
        self._draw_middle_finger_single(c, cx + gap, cy, size * 0.6)

