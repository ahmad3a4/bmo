#!/usr/bin/env python3
"""
ARIA — Advanced Raspberry Intelligence Assistant
Main agent: wake word detection, voice pipeline, GPIO LEDs, sound FX.

Usage:
  python aria.py              # normal mode
  python aria.py --headless   # no GUI (Raspberry Pi without screen)
  python aria.py --test       # self-test and exit
"""
import os, sys, re, json, wave, time, threading, traceback, argparse, subprocess, glob, shutil
import sounddevice as sd
import numpy as np
try:
    from openwakeword.model import Model as OWWModel
    HAS_OWW = True
except ImportError:
    OWWModel = None
    HAS_OWW = False
    print("[OWW] openwakeword not installed — PTT mode only (press Enter).", flush=True)

from bmo.brain  import STT, OllamaAI, BMOBrain, ARIAVoice, GroqVoice, is_whisper_phantom
from bmo.skills import SkillsRouter
from bmo.alarms import AlarmManager
from bmo.journal import JournalManager, CHECKIN_QUESTIONS
from bmo.semantic_memory import SemanticMemory
from bmo.voiceprint import VoiceIDManager
from bmo.face_id import FaceIDManager
from bmo.life import LifeEngine
from bmo.vad import Endpointer
from bmo.config import load_config
from bmo.paths import PROJECT_ROOT, VOICES_DIR, WAKEWORD_DIR, FACES_DIR

# ─── BMO Extended Modules (graceful fallback if missing) ────────────────────
try:
    from bmo.faces import BMOFaces
    HAS_BMO_FACES = True
except ImportError:
    HAS_BMO_FACES = False

try:
    from bmo.hud import BMOHud
    HAS_BMO_HUD = True
except ImportError:
    HAS_BMO_HUD = False



try:
    from bmo.media import MediaDisplay
    HAS_MEDIA = True
except ImportError:
    HAS_MEDIA = False

try:
    from bmo.games import GamesLauncher
    HAS_GAMES = True
except ImportError:
    HAS_GAMES = False

try:
    from bmo.ambient import AmbientMode
    HAS_AMBIENT = True
except ImportError:
    HAS_AMBIENT = False

try:
    from bmo.instagram.scheduler import InstagramScheduler
    HAS_INSTAGRAM = True
except ImportError:
    HAS_INSTAGRAM = False

# ─── Config ───────────────────────────────────────────────────────────────────
CFG     = load_config()
TMP_WAV = "/tmp/aria_in.wav"

# ─── Audio device helpers ─────────────────────────────────────────────────────
def resolve_device(key, inp=True):
    req = CFG.get(key)
    if req in (None, "", "default"):
        return None
    try:
        devs = sd.query_devices()
        ck   = "max_input_channels" if inp else "max_output_channels"
        if str(req).isdigit():
            idx = int(req)
            return idx if 0 <= idx < len(devs) else None
        low = str(req).lower()
        for i, d in enumerate(devs):
            if d.get(ck, 0) > 0 and low in d.get("name", "").lower():
                return i
    except Exception:
        pass
    return None

def get_in_dev():
    return resolve_device("input_device", inp=True)

def best_sr(dev):
    for r in [CFG.get("input_sample_rate"), 48000, 44100, 16000]:
        if not r:
            continue
        try:
            sd.check_input_settings(device=dev, samplerate=r,
                                     channels=1, dtype="int16")
            return r
        except Exception:
            pass
    return 44100

# ─── LED helper (optional gpiozero) ──────────────────────────────────────────
class LEDController:
    def __init__(self, cfg):
        self.enabled = cfg.get("led_enabled", False)
        self.leds    = {}
        if not self.enabled:
            return
        try:
            from gpiozero import LED
            pins = {
                "idle":  cfg.get("led_idle_pin",   17),
                "listen": cfg.get("led_listen_pin", 27),
                "think": cfg.get("led_think_pin",   22),
                "speak": cfg.get("led_speak_pin",   23),
            }
            self.leds = {name: LED(pin) for name, pin in pins.items()}
            print("[LED] GPIO LEDs ready.", flush=True)
        except Exception as e:
            print(f"[LED] GPIO unavailable: {e}", flush=True)
            self.enabled = False

    def set(self, state):
        if not self.enabled:
            return
        for name, led in self.leds.items():
            if name == state:
                led.on()
            else:
                led.off()

    def off(self):
        for led in self.leds.values():
            try:
                led.off()
            except Exception:
                pass

# ─── Sound Effects ────────────────────────────────────────────────────────────
class SoundFX:
    SOUNDS = {
        "wake":    "sounds/wake.wav",
        "done":    "sounds/done.wav",
        "error":   "sounds/error.wav",
    }

    def __init__(self, enabled=True):
        self.enabled = enabled
        base = PROJECT_ROOT
        self._paths = {k: os.path.join(base, v) for k, v in self.SOUNDS.items()}

    def play(self, name):
        if not self.enabled:
            return
        path = self._paths.get(name)
        if path and os.path.exists(path):
            try:
                subprocess.Popen(["aplay", "-q", path],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
            except Exception:
                pass

# STT commonly mishears certain names — normalize known cases so voice
# enrollment doesn't silently save under the wrong spelling.
_NAME_ALIASES = {"ahmed": "Ahmad"}


def _normalize_name(name):
    return _NAME_ALIASES.get(name.lower(), name)


# ─── States ───────────────────────────────────────────────────────────────────
class S:
    IDLE     = "idle"
    LISTEN   = "listen"
    THINK    = "think"
    SPEAK    = "speak"
    WARMUP   = "warmup"
    ERROR    = "error"

# ─── Actions that require a recognized owner voice ───────────────────────────
# Anything that touches another machine, posts publicly, or writes/runs new
# code gets gated here once voice ID is enabled and someone is enrolled.
PRIVILEGED_ACTIONS = {
    "generate_skill",                                    # self-coder: writes + installs new code
    "shutdown_system",                                    # powers off the Pi BMO runs on
    "pc_turn_on", "pc_lock", "pc_sleep", "pc_shutdown", "pc_restart",
    "pc_mute", "pc_youtube", "pc_spotify", "pc_launch_app", "pc_close_app",
    "pc_set_volume", "pc_top_processes", "pc_screenshot", "pc_read_clipboard",
    "pc_playtime", "pc_gpu_temp",                         # remote PC control
    "ig_post", "ig_story",                                # Instagram posting
}

# ─── ARIA Agent ───────────────────────────────────────────────────────────────
class ARIAAgent:
    def __init__(self, headless=False):
        self.headless   = headless
        self.state      = S.WARMUP
        self.stop_tts    = threading.Event()
        self.ptt_ev      = threading.Event()
        self.recording   = threading.Event()
        self.interrupted = threading.Event()
        self._exiting    = False
        self._tts_q      = []
        self._tts_lock   = threading.Lock()
        self._tts_busy   = threading.Event()
        self._tts_ready  = threading.Event()   # wakes worker instantly on enqueue
        self._name       = CFG.get("assistant_name", "BMO")
        self._root       = None


        # ── Hardware ──────────────────────────────────────────────────────
        self.led  = LEDController(CFG)
        self.sfx  = SoundFX(CFG.get("sound_effects", True))
        self.led.set(S.WARMUP)

        # ── AI stack (Groq ⚡ + Ollama 🔒 fallback) ───────────────────────
        print("[BMO] Initialising AI stack...", flush=True)
        self._language = CFG.get("language", "english").lower()
        self.stt = STT(
            model_name=CFG.get("whisper_model", "tiny.en"),
            groq_api_key=CFG.get("groq_api_key", ""),   # ⚡ Groq cloud STT
            language=("ar" if self._language == "arabic" else "en"),
        )
        self.ai    = BMOBrain(CFG)           # Groq-first, Ollama fallback

        self.skills = SkillsRouter(CFG, self.enqueue,
                                   ai_summarise=self.ai.summarise)
        self.skills.set_brain(self.ai)   # expose brain for "brain status" command
        self.alarms = AlarmManager(speak_cb=self.enqueue)

        # ── Speaker recognition ─────────────────────────────────────────────
        self.voiceid = VoiceIDManager(
            enabled=CFG.get("voice_id_enabled", True),
            threshold=CFG.get("voice_id_threshold", 0.75),
        )

        # ── Face recognition ────────────────────────────────────────────────
        self.faceid = FaceIDManager(
            enabled=CFG.get("face_id_enabled", True),
            threshold=CFG.get("face_id_threshold", 70.0),
        )

        # One-shot: after BMO asks something on its own, listen once without the wake word.
        self._listen_for_reply = False
        # From _record(): "strong" / "weak" / "none" per the VAD, None if it isn't available.
        self._last_rec_evidence = None

        # ── Nightly check-in / mood journal ────────────────────────────────
        self._checkin_pending  = False
        self._checkin_deadline = 0.0
        self.journal = JournalManager(
            on_fire=self._checkin_fire,
            checkin_time=CFG.get("checkin_time", "21:30"),
            enabled=CFG.get("checkin_enabled", True),
        )

        # ── Inner life (moods, acting on its own, diary) ───────────────────
        self.life = LifeEngine(
            CFG,
            say=self._life_say,
            can_speak=self._life_can_speak,
            look=self.faceid.look,
            set_face=self._life_face,
        )

        # ── Semantic memory (free-form conversational recall) ──────────────
        self.semantic_memory = SemanticMemory(
            embed_model=CFG.get("semantic_embed_model", "all-minilm"),
            enabled=CFG.get("semantic_memory_enabled", True),
            relevance_threshold=CFG.get("semantic_recall_threshold", 0.35),
        )

        # ── Instagram Scheduler ──────────────────────────────────────────────────
        self.instagram = None
        if HAS_INSTAGRAM:
            try:
                self.instagram = InstagramScheduler(CFG, speak_cb=self.enqueue)
                self.skills.set_instagram(self.instagram)
                print("[BMO] Instagram scheduler active.", flush=True)
            except Exception as e:
                print(f"[BMO] Instagram init error: {e}", flush=True)

        if self._language == "arabic":
            # Local Piper Arabic voice (low-quality, but works fully offline)
            # kept as the fallback if Groq's Arabic TTS is unreachable.
            piper_fallback = ARIAVoice(
                voice_model=CFG.get("arabic_fallback_voice_model", "ar_JO-kareem-low"),
                robotic_fx=False,           # Robotic FX garbles Arabic phonemes
                voices_dir=VOICES_DIR,
            )
            groq_key = CFG.get("groq_api_key", "")
            if groq_key:
                self.voice = GroqVoice(
                    groq_key,
                    model=CFG.get("arabic_tts_model", "canopylabs/orpheus-arabic-saudi"),
                    voice=CFG.get("arabic_tts_voice", "fahad"),
                    fallback=piper_fallback,
                    aplay_device=piper_fallback._aplay_dev,  # same real output device Piper found
                )
            else:
                print("[TTS] No Groq API key — using local Arabic Piper voice only.", flush=True)
                self.voice = piper_fallback
        else:
            self.voice = ARIAVoice(
                voice_model=CFG.get("voice_model", "en_GB-alan-medium"),
                robotic_fx=CFG.get("robotic_fx", True),
                voices_dir=VOICES_DIR,
            )
            self.skills.selfie.set_voice(self.voice)
        # ── BMO faces (code-drawn fallback, set in GUI) ───────────────────────
        self._bmo_faces = BMOFaces(
            canvas=None,
            sat_boost=CFG.get("face_saturation_boost", 1.0),
            val_boost=CFG.get("face_brightness_boost", 1.0),
        ) if HAS_BMO_FACES else None
        self._hud       = None  # initialised in _start_gui
        self._ambient   = None  # initialised in _start_gui
        self._spotify_playing = False
        self._spotify_last_poll = 0

        # ── Wake word ─────────────────────────────────────────────────────
        self.oww  = None
        ww_name   = CFG.get("wake_word_model", "alexa")

        if not HAS_OWW:
            print("[OWW] openwakeword not installed — PTT mode (press Enter).", flush=True)
        else:
            try:
                import openwakeword
                model_path = os.path.join(WAKEWORD_DIR, f"{ww_name}.onnx")
                if not os.path.exists(model_path):
                    try:
                        model_path = openwakeword.get_pretrained_model_paths([ww_name])[0]
                    except Exception:
                        model_path = None
                if model_path:
                    print(f"[OWW] Loading: {model_path}", flush=True)
                    self.oww = OWWModel(wakeword_model_paths=[model_path])
                    print(f"[OWW] Wake word '{ww_name}' active.", flush=True)
                else:
                    print(f"[OWW] Model not found for '{ww_name}' — PTT mode.", flush=True)
            except Exception as e:
                print(f"[OWW] Wake word unavailable: {e} — PTT mode.", flush=True)

        # ── Worker threads ────────────────────────────────────────────────
        threading.Thread(target=self._tts_worker, daemon=True).start()
        threading.Thread(target=self._main_loop,  daemon=True).start()

        # ── BMO Web App API ───────────────────────────────────────────────
        try:
            from bmo.app import start_bmo_app
            start_bmo_app(self)
        except Exception as e:
            print(f"[API] Failed to start BMO Web App: {e}")

        # ── Optional GUI ──────────────────────────────────────────────────
        if not headless:
            self._start_gui()

        if self.headless:
            print(f"[ARIA] Running headless. Say '{ww_name}' to activate.",
                  flush=True)
            try:
                while not self._exiting:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.quit()

    # ─── GUI (optional) ────────────────────────────────────────────────────
    def _start_gui(self):
        try:
            import tkinter as tk
            self._root = tk.Tk()
            self._root.title(f"{self._name} Assistant")

            # BMO Colors — match the brighter mint green face background.
            # Boosted via config for washed-out TFT panels (1.0 = unchanged).
            from bmo.faces import boost_color
            sat_boost = CFG.get("face_saturation_boost", 1.0)
            val_boost = CFG.get("face_brightness_boost", 1.0)
            self.BMO_BG = boost_color("#82D4A4", sat_boost, val_boost)
            self.BMO_FG = boost_color("#113333", sat_boost, val_boost)

            self._root.configure(bg=self.BMO_BG)
            self._root.attributes("-fullscreen", True)

            self._canvas = tk.Canvas(self._root, bg=self.BMO_BG, highlightthickness=0)
            self._canvas.pack(fill=tk.BOTH, expand=True)

            # ── Face System Setup ─────────────────────────────────────────────
            self._face_frames = {}
            self._face_idx    = {}
            
            # Code-drawn faces (BMOFaces) is now the primary system.
            # PNG loading is kept as a legacy fallback only.
            face_dir = FACES_DIR
            state_map = {
                S.IDLE:    "idle",
                S.LISTEN:  "listening",
                S.THINK:   "thinking",
                S.SPEAK:   "speaking",
                S.WARMUP:  "warmup",
                S.ERROR:   "error",
                "capturing": "capturing",
            }
            if os.path.exists(face_dir):
                for state, folder in state_map.items():
                    pattern = os.path.join(face_dir, folder, "*.png")
                    files   = sorted(glob.glob(pattern))
                    frames  = [tk.PhotoImage(file=f) for f in files]
                    self._face_frames[state] = frames
                    self._face_idx[state]    = 0
            
            # Initialize code-drawn face if not already done
            if not self._bmo_faces and HAS_BMO_FACES:
                from bmo.faces import BMOFaces
                self._bmo_faces = BMOFaces(
                    canvas=self._canvas,
                    sat_boost=CFG.get("face_saturation_boost", 1.0),
                    val_boost=CFG.get("face_brightness_boost", 1.0),
                )

            # ── HUD ────────────────────────────────────────────────────────────
            if HAS_BMO_HUD:
                from bmo.hud import BMOHud
                self._hud = BMOHud(
                    canvas=self._canvas,
                    spotify_skill=self.skills.spotify,
                    cfg=CFG,
                )

            # ── Media Display ─────────────────────────────────────────────────
            if HAS_MEDIA:
                try:
                    media = MediaDisplay(
                        canvas=self._canvas,
                        root=self._root,
                        base_dir=PROJECT_ROOT,
                    )
                    self.skills.set_media(media)
                    print("[BMO] Media display ready.", flush=True)
                except Exception as e:
                    print(f"[BMO] Media display error: {e}", flush=True)

            # ── Ambient Mode ──────────────────────────────────────────────────
            if HAS_AMBIENT:
                self._ambient = AmbientMode(
                    media_display=getattr(self.skills, "media", None),
                    face_system=self._bmo_faces
                )
                self.skills.set_ambient(self._ambient)
                print("[BMO] Ambient Mode ready.", flush=True)

            # ── Games Launcher ────────────────────────────────────────────────
            if HAS_GAMES:
                try:
                    self._root._bmo_bg = self.BMO_BG  # store so launcher can restore
                    games = GamesLauncher(
                        cfg=CFG,
                        root=self._root,
                        bmo_faces=self._bmo_faces,
                        canvas=self._canvas,
                    )
                    self.skills.set_games(games)
                    print("[GAMES] RetroArch launcher ready.", flush=True)
                except Exception as e:
                    print(f"[GAMES] Launcher init error: {e}", flush=True)

            self._status_var = tk.StringVar(value="Initialising...")
            tk.Label(self._root, textvariable=self._status_var,
                     bg=self.BMO_BG, fg=self.BMO_FG,
                     font=("monospace", 18, "bold"), wraplength=700).place(
                         relx=0.5, rely=0.88, anchor=tk.CENTER)

            self._pulse = 0
            # Defer first draw until window is fully rendered so
            # winfo_width() / winfo_height() return real pixel values.
            self._root.update_idletasks()
            self._root.after(100, self._draw_ui)
            self._root.bind("<Return>", self._ptt_toggle)
            self._root.bind("<Escape>", lambda e: self.quit())
            self._root.bind("<space>",  self._do_interrupt)
            self._root.protocol("WM_DELETE_WINDOW", self.quit)
            self._root.mainloop()
        except Exception as e:
            print(f"[GUI] Tkinter unavailable: {e}. Running headless.", flush=True)
            self.headless = True

    def _draw_ui(self):
        if not self._root:
            return
        try:
            media = getattr(self.skills, "media", None)
            if media and media.is_active():
                self._pulse += 1
                self._root.after(100, self._draw_ui)
                return

            c = self._canvas
            w = c.winfo_width()  or 800
            h = c.winfo_height() or 480
            c.delete("all")

            # ── Full Screen Center ────────────────────────────────────────
            cx, cy = w // 2, h // 2
            s = self.state

            # Poll Spotify state every 10 seconds in a background thread to avoid API rate limits
            now = time.time()
            if getattr(self, "_spotify_poll_active", False) is False and (now - getattr(self, "_spotify_last_poll", 0) > 10.0):
                self._spotify_last_poll = now
                self._spotify_poll_active = True
                def poll_sp():
                    try:
                        if hasattr(self.skills, "spotify") and getattr(self.skills, "spotify", None):
                            info = self.skills.spotify.current_track_info()
                            self._spotify_playing = bool(info and info.get("is_playing"))
                        else:
                            self._spotify_playing = False
                    except Exception:
                        self._spotify_playing = False
                    finally:
                        self._spotify_poll_active = False
                threading.Thread(target=poll_sp, daemon=True).start()

            # ── Face Display ──────────────────────────────────────────────
            face_cx, face_cy = cx, cy
            
            # Prioritize code-drawn face ("just coding no pics")
            if self._bmo_faces:
                cur_em = self._bmo_faces._emotion
                # 'rude' and other explicit emotions always win over state-based emotion
                if cur_em == "rude":
                    emotion = "rude"
                elif s == S.SPEAK and cur_em != "idle":
                    # Use the specific emotion set by enqueue()
                    emotion = cur_em
                elif s == S.IDLE and getattr(self, "_spotify_playing", False):
                    # BMO is playing Spotify music in IDLE state — go DJ Mode!
                    emotion = "music"
                elif s == S.IDLE and cur_em in ("sleep", "sad"):
                    # Mood face from BMO's inner life (sleepy at night, lonely when ignored)
                    emotion = cur_em
                else:
                    emotion = self._bmo_faces.emotion_for_state(s)

                # Make the face take up the full screen
                self._bmo_faces.draw(c, face_cx, face_cy, self._pulse, emotion)
                
            elif self._face_frames.get(s) or self._face_frames.get(S.IDLE, []):
                # Fallback to PNGs only if code-drawn system is unavailable
                frames = self._face_frames.get(s) or self._face_frames.get(S.IDLE, [])
                fps_div = 6 if s in (S.SPEAK, S.THINK) else 12
                idx = (self._pulse // fps_div) % len(frames)
                img = frames[idx]
                c.create_image(face_cx, face_cy, image=img, anchor="center")

            # ── HUD overlay (always on top) ───────────────────────────────
            if self._hud:
                self._hud.draw(c)

            self._pulse += 1
            if self._bmo_faces:
                delay = 33 # ~30 FPS for fluid animation
            else:
                delay = 100 if s in (S.SPEAK, S.THINK) else 150
            self._root.after(delay, self._draw_ui)
        except Exception:
            pass

    def _set_state(self, state, msg=""):
        self.state = state
        self.led.set(state)
        if msg:
            print(f"[{state.upper()}] {msg}", flush=True)
        if self._root and not self.headless:
            try:
                self._status_var.set(msg or state)
            except Exception:
                pass

    def _ptt_toggle(self, _=None):
        if self.recording.is_set():
            self.recording.clear()
        elif self.state == S.IDLE:
            self.recording.set()
            self.ptt_ev.set()

    def _stop_speaking(self):
        with self._tts_lock:
            self._tts_q.clear()
        self.stop_tts.set()
        self.voice.stop()

    def _tts_idle(self):
        # Queue first, then busy: the worker sets busy before it pops, so this
        # order can never see "empty queue, not busy" while a line is starting.
        return not self._tts_q and not self._tts_busy.is_set()

    def _do_interrupt(self, _=None):
        self.interrupted.set()
        self._stop_speaking()
        if HAS_MEDIA and getattr(self.skills, "media", None):
            self.skills.media.clear()
        self._set_state(S.IDLE, "Interrupted.")
        if self._bmo_faces:
            self._bmo_faces.set_emotion("confused")

    # ─── TTS queue ─────────────────────────────────────────────────────────
    def enqueue(self, text):
        with self._tts_lock:
            self._tts_q.append(text)
        self._tts_ready.set()   # wake TTS worker immediately — no polling delay

        # Detect emotion from the raw text (including [TAG]) for the face
        # Don't overwrite 'rude' — let it stay until speaking is done
        if self._bmo_faces and self._bmo_faces._emotion != "rude":
            from bmo.faces import emotion_from_reply
            emo = emotion_from_reply(text)
            if emo:
                self._bmo_faces.set_emotion(emo)
            else:
                self._bmo_faces.set_emotion("idle")

    # ─── Nightly check-in ────────────────────────────────────────────────────
    def _checkin_fire(self):
        """Called by JournalManager once/day. Only asks if BMO is idle —
        returns False (meaning: try again in 30s) otherwise."""
        if self.state != S.IDLE or not self._tts_idle() or self._listen_for_reply:
            return False
        import random
        self.enqueue(random.choice(CHECKIN_QUESTIONS))
        self._checkin_pending  = True
        self._checkin_deadline = time.time() + 240  # 4 min to reply
        self._listen_for_reply = True
        return True

    def _no_speech(self, src):
        """Nobody actually spoke: a false wake, or no answer to something BMO asked."""
        if src == "REPLY":
            if self._checkin_pending:
                self._checkin_pending = False
            else:
                self.life.on_no_reply()
        print("[REC] No speech heard — back to idle.", flush=True)
        self._set_state(S.IDLE, "No speech detected.")

    # ─── Inner life callbacks ────────────────────────────────────────────────
    def _life_can_speak(self):
        if self.state != S.IDLE or not self._tts_idle() or self.recording.is_set():
            return False
        if self._listen_for_reply or self._checkin_pending:
            return False
        if self._spotify_playing or (self._ambient and self._ambient.is_active()):
            return False
        media = getattr(self.skills, "media", None)
        if media and media.is_active():  # selfie preview, a photo or meme on screen
            return False
        games = getattr(self.skills, "games", None)
        return not (games and games.running)

    def _life_say(self, text, expect_reply=False):
        if not self._life_can_speak():
            return False
        self.ai.note_spoken(text)
        for s in [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]:
            self.enqueue(s)
        if expect_reply:
            self._listen_for_reply = True
        return True

    def _life_face(self, emotion):
        f = self._bmo_faces
        if f and f._emotion in ("idle", "sleep", "sad") and f._emotion != emotion and self._life_can_speak():
            f.set_emotion(emotion)

    def _is_privileged_action_allowed(self, action_name, speaker_name):
        """Gate PC control / self-coding / Instagram posting to the owner's
        voice — but only once voice ID is actually usable (resemblyzer
        installed AND an owner is configured), otherwise fail open so this
        doesn't silently break things for setups that never enrolled a voice."""
        if action_name not in PRIVILEGED_ACTIONS:
            return True
        if not self.voiceid.enabled:
            return True
        owner = CFG.get("voice_id_owner") or CFG.get("user_name", "")
        if not owner:
            return True
        return bool(speaker_name) and speaker_name.lower() == owner.lower()

    def _tts_worker(self):
        while True:
            try:
                self._tts_worker_iteration()
            except Exception as e:
                print(f"[TTS] Worker error (recovered): {e}", flush=True)
                self._tts_busy.clear()
                if self._bmo_faces:
                    self._bmo_faces.set_speaking(False)
                    self._bmo_faces.set_volume(0.0)

    def _tts_worker_iteration(self):
            txt = None
            with self._tts_lock:
                if self._tts_q:
                    self._tts_busy.set()
                    txt = self._tts_q.pop(0)
                    if not txt:
                        self._tts_busy.clear()
            if txt:
                self.stop_tts.clear()

                # Strip [TAG] tokens before speaking — they're for the face, not TTS
                from bmo.faces import strip_emotion_tags
                clean_txt = strip_emotion_tags(txt)

                # ── Syllable-paced lip sync ──────────────────────────────────
                # Pre-compute syllable timing from text so the mouth driver
                # can start immediately the moment audio begins (on_start).
                import re as _re

                def _count_syllables(word):
                    w = word.lower().strip(".,!?;:'\"()-")
                    vowel_groups = _re.findall(r'[aeiouy]+', w)
                    return max(1, len(vowel_groups))

                words      = [w for w in clean_txt.split() if w]
                syl_counts = [_count_syllables(w) for w in words]
                # BMO voice speed ≈ 3.8 syllables/sec at length_scale 1.0
                SPY_PER_SEC = 3.8

                _audio_started = threading.Event()
                _lip_stop      = threading.Event()

                def _lip_driver():
                    # Wait until audio actually starts playing
                    _audio_started.wait(timeout=4.0)
                    if _lip_stop.is_set():
                        return
                    if self._bmo_faces is None:
                        return
                    for nsyl in syl_counts:
                        if _lip_stop.is_set():
                            break
                        syl_dur = nsyl / SPY_PER_SEC
                        # Open mouth for ~60% of syllable duration
                        self._bmo_faces.set_volume(0.75 + (nsyl > 1) * 0.15)
                        _lip_stop.wait(syl_dur * 0.60)
                        if _lip_stop.is_set():
                            break
                        # Briefly close between syllables
                        self._bmo_faces.set_volume(0.05)
                        _lip_stop.wait(syl_dur * 0.40)
                    # Ensure mouth closes cleanly
                    if self._bmo_faces:
                        self._bmo_faces.set_volume(0.0)

                threading.Thread(target=_lip_driver, daemon=True).start()

                def on_start():
                    self._set_state(S.SPEAK, clean_txt)
                    if self._bmo_faces:
                        self._bmo_faces.set_speaking(True)
                    _audio_started.set()   # fire lip driver exactly when audio starts

                self.voice.say(clean_txt, self.stop_tts, on_start=on_start)
                self._tts_busy.clear()
                _lip_stop.set()  # stop lip driver

                # Stop mouth animation after each sentence
                if self._bmo_faces:
                    self._bmo_faces.set_speaking(False)
                    self._bmo_faces.set_volume(0.0)

                # When ALL sentences done, reset emotion and go idle
                if not self._tts_q:
                    if self._bmo_faces:
                        self._bmo_faces.set_emotion("idle")
                    self._set_state(S.IDLE,
                                    f"Say '{CFG.get('wake_word_model','alexa')}' to wake me.")

            else:
                # Block here until enqueue() fires _tts_ready — zero CPU, zero delay
                self._tts_ready.wait(timeout=1.0)
                self._tts_ready.clear()


    def _wait_tts(self) -> bool:
        """Returns True if interrupted by wake word."""
        if not self.oww:
            while self._tts_q or self._tts_busy.is_set():
                if self.interrupted.is_set():
                    break
                time.sleep(0.1)
            return False

        CHUNK = 1280
        SR    = 16000
        in_dev = get_in_dev()
        in_sr = best_sr(in_dev)
        in_chunk = int(CHUNK * (in_sr / SR))
        # Deliberately NOT the same as the normal wake_threshold: BMO's own
        # voice (it says its own name constantly) bleeds into the mic while
        # speaking, so a threshold tuned low enough for reliable real wake-ups
        # in a quiet room will also self-trigger on BMO's own TTS output and
        # cut its own sentence off. This listener only needs to catch a loud,
        # deliberate "hey bmo" over BMO's own speaker — so it gets its own,
        # much stricter threshold instead of inheriting the tuned-down one.
        thresh   = CFG.get("wake_threshold_during_tts", 0.6)

        try:
            with sd.InputStream(samplerate=in_sr, channels=1, dtype="int16",
                                 blocksize=in_chunk, device=in_dev) as stream:
                while self._tts_q or self._tts_busy.is_set():
                    if self.interrupted.is_set():
                        break

                    if stream.read_available < in_chunk:
                        sd.sleep(10)
                        continue

                    data, _ = stream.read(in_chunk)
                    audio   = np.frombuffer(data, dtype=np.int16)
                    if audio.ndim > 1:
                        audio = audio.flatten()
                    if in_sr != SR:
                        step  = len(audio) / CHUNK
                        idx   = np.arange(0, len(audio), step)[:CHUNK].astype(int)
                        audio = audio[idx]

                    if np.max(np.abs(audio)) > 20:
                        self.oww.predict(audio)
                        for m in self.oww.prediction_buffer:
                            score = list(self.oww.prediction_buffer[m])[-1]
                            if score > thresh:
                                print(f"\n[WAKE] '{m}' detected during TTS!", flush=True)
                                self.oww.reset()
                                self._do_interrupt()
                                return True
        except Exception as e:
            print(f"[WAKE] TTS listen error: {e}", flush=True)
            while self._tts_q or self._tts_busy.is_set():
                if self.interrupted.is_set():
                    break
                time.sleep(0.1)
                
        return False

    # ─── Wake word detection ────────────────────────────────────────────────
    def _wait_for_trigger(self):
        ww_name = CFG.get("wake_word_model", "alexa")
        self._set_state(S.IDLE, f"Listening for '{ww_name}'...")
        self.ptt_ev.clear()
        if self.oww:
            self.oww.reset()

        if not self.oww:
            while True:
                if self._listen_for_reply and self._tts_idle():
                    self._listen_for_reply = False
                    return "REPLY"
                if self.ptt_ev.wait(timeout=0.5):
                    self.ptt_ev.clear()
                    self._listen_for_reply = False
                    return "PTT"

        CHUNK = 1280
        SR    = 16000
        in_dev = get_in_dev()
        in_sr = best_sr(in_dev)
        in_chunk = int(CHUNK * (in_sr / SR))
        thresh     = CFG.get("wake_threshold", 0.5)
        thresh_tts = CFG.get("wake_threshold_during_tts", 0.6)
        last_tts   = 0.0  # BMO also talks while idle: alarms, check-ins, its inner life

        try:
            with sd.InputStream(samplerate=in_sr, channels=1, dtype="int16",
                                 blocksize=in_chunk, device=in_dev) as stream:
                while True:
                    if self._listen_for_reply and self._tts_idle():
                        # BMO just asked something on its own — listen once for
                        # the answer, no wake word needed.
                        self._listen_for_reply = False
                        return "REPLY"
                    if self.ptt_ev.is_set():
                        self.ptt_ev.clear()
                        self._listen_for_reply = False
                        return "PTT"
                    data, _ = stream.read(in_chunk)
                    audio   = np.frombuffer(data, dtype=np.int16)
                    if audio.ndim > 1:
                        audio = audio.flatten()
                    # Downsample to 16kHz if needed
                    if in_sr != SR:
                        step  = len(audio) / CHUNK
                        idx   = np.arange(0, len(audio), step)[:CHUNK].astype(int)
                        audio = audio[idx]

                    speaking = not self._tts_idle()
                    if speaking:
                        last_tts = time.time()
                    elif last_tts and time.time() - last_tts > 1.0:
                        # BMO's own voice lingers in the wake model's window right
                        # after it stops; flush it before going back to sensitive.
                        self.oww.reset()
                        last_tts = 0.0
                    cur_thresh = thresh_tts if last_tts else thresh

                    if np.max(np.abs(audio)) > 20:
                        self.oww.predict(audio)
                        for m in self.oww.prediction_buffer:
                            score = list(self.oww.prediction_buffer[m])[-1]
                            if score > cur_thresh:
                                print(f"\n[WAKE] '{m}' score={score:.2f}",
                                      flush=True)
                                self.oww.reset()
                                if speaking:
                                    self._stop_speaking()
                                self._listen_for_reply = False
                                return "WAKE"
        except Exception as e:
            print(f"[WAKE] Stream error: {e}", flush=True)
            self.ptt_ev.wait()
            return "PTT"

    # ─── Recording ──────────────────────────────────────────────────────────
    def _record(self, ptt=False):
        self._set_state(S.LISTEN, "Listening...")
        self.sfx.play("wake")
        # No sleep — start recording immediately for faster response
        in_dev = get_in_dev()
        sr  = best_sr(in_dev)
        buf = []

        sil_thresh = CFG.get("silence_threshold", 0.006)
        sil_dur    = CFG.get("silence_duration",   1.5)
        max_t      = CFG.get("max_record_seconds", 25)
        self._last_rec_evidence = None

        if ptt:
            def cb(d, f, t, s): buf.append(d.copy())
            try:
                sd.stop(); time.sleep(0.1)
                with sd.InputStream(samplerate=sr, channels=1,
                                    callback=cb, device=in_dev):
                    while self.recording.is_set():
                        sd.sleep(50)
            except Exception as e:
                print(f"[REC] PTT error: {e}", flush=True)
        else:
            chunk_d  = 0.03          # 30ms chunks — also a valid webrtcvad frame length
            chunk_sz = int(sr * chunk_d)
            n_sil    = int(sil_dur / chunk_d)
            n_max    = int(max_t / chunk_d)
            sil_cnt  = 0
            rec_cnt  = 0
            done     = False
            ep = Endpointer(sr, silence_s=sil_dur,
                            no_speech_s=CFG.get("no_speech_timeout", 3.5))

            def cb(d, f, t, s):
                nonlocal sil_cnt, rec_cnt, done
                buf.append(d.copy())
                rec_cnt += 1
                if ep.available:
                    if ep.push(d[:, 0]):
                        done = True
                    return
                # Loudness fallback, only when webrtcvad can't run.
                vol = np.linalg.norm(d) / max(np.sqrt(len(d)), 1)
                # Ignore silence for the first ~450ms to give user time to start
                if rec_cnt < 15:
                    return
                sil_cnt = sil_cnt + 1 if vol < sil_thresh else 0
                if sil_cnt >= n_sil:
                    done = True

            try:
                print(f"[REC] Starting recording (SR={sr}, Dev={in_dev})", flush=True)
                sd.stop(); time.sleep(0.1)
                vols = []
                with sd.InputStream(samplerate=sr, channels=1, callback=cb,
                                    device=in_dev, blocksize=chunk_sz):
                    while not done and rec_cnt < n_max:
                        # Calculate volume for logging (callback already does it but we want to see it)
                        if buf:
                            latest = buf[-1]
                            v = np.linalg.norm(latest) / max(np.sqrt(len(latest)), 1)
                            vols.append(v)
                        sd.sleep(int(chunk_d * 1000))
                
                duration = rec_cnt * chunk_d
                if ep.available:
                    self._last_rec_evidence = ep.evidence
                    print(f"[REC] Finished. Duration: {duration:.1f}s, speech: {ep.voiced_seconds:.1f}s "
                          f"({ep.evidence})", flush=True)
                else:
                    avg_vol = np.mean(vols) if vols else 0
                    print(f"[REC] Finished. Duration: {duration:.1f}s, Avg Vol: {avg_vol:.5f}", flush=True)
            except Exception as e:
                print(f"[REC] Adaptive error: {e}", flush=True)

        if not buf:
            return None
        audio = np.concatenate(buf, axis=0).flatten()
        audio = (np.nan_to_num(audio) * 32767).astype(np.int16)
        with wave.open(TMP_WAV, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio.tobytes())
        return TMP_WAV

    # JSON parser removed as part of intent routing update

    # ─── Main loop ──────────────────────────────────────────────────────────
    def _main_loop(self):
        # Warm up local Whisper only if Groq STT isn't active
        self._set_state(S.WARMUP, "Warming up systems...")
        if self.stt.model and not self.stt._groq_ok:
            try:
                import whisper as _w
                dummy = np.zeros(16000, dtype=np.float32)
                self.stt.model.transcribe(dummy, fp16=False, beam_size=1, best_of=1, temperature=0.0)
            except Exception:
                pass
        elif self.stt._groq_ok:
            print("[WARMUP] Groq STT active — skipping local Whisper warmup.", flush=True)

        # Startup greeting
        ww   = CFG.get("wake_word_model", "alexa")
        name = CFG.get("assistant_name", "BMO")
        if self._language == "arabic":
            self.enqueue(
                f"بيمو جاهز. جميع الأنظمة تعمل بشكل طبيعي. قل {ww} لتفعيلي."
            )
        else:
            self.enqueue(
                f"Hey hey, it's BMO! I'm alive and I'm awesome — say {ww} if you wanna talk to me!"
            )

        # Warm up Ollama in background only if Groq is not active to prevent low-voltage/RAM spikes
        def warm_brain():
            try:
                if self.ai.ollama and not self.ai.groq:
                    print("[WARMUP] Warming up Ollama locally...", flush=True)
                    self.ai.ollama.ask("System warmup.")
                    self.ai.ollama.reset()
            except Exception:
                pass
        threading.Thread(target=warm_brain, daemon=True).start()
        self._wait_tts()
        self.life.start()

        skip_trigger = False
        while True:
            try:
                if skip_trigger:
                    src = "WAKE"
                    skip_trigger = False
                    self.interrupted.clear()
                else:
                    src = self._wait_for_trigger()
                    if HAS_MEDIA and getattr(self.skills, "media", None):
                        self.skills.media.clear()
                    if self.interrupted.is_set():
                        self.interrupted.clear()
                        continue


                wav = self._record(ptt=(src == "PTT"))
                if not wav:
                    self._set_state(S.IDLE, "No audio detected.")
                    continue

                # Always transcribe: on this mic a voice across the room sits barely
                # above the fan noise, where the VAD can't see it but Whisper can.
                evidence = self._last_rec_evidence
                faint = evidence in ("weak", "none")

                self._set_state(S.THINK, "Thinking...")

                # Speaker ID (voice) and face ID (camera) both run in parallel
                # with STT — adds zero serial latency either way.
                _speaker_box = {}
                def _id_worker(_wav=wav):
                    _speaker_box["name"] = self.voiceid.identify(_wav)
                _id_thread = threading.Thread(target=_id_worker, daemon=True)
                _id_thread.start()

                _face_box = {}
                def _face_worker():
                    _face_box["name"] = self.faceid.identify()
                _face_thread = threading.Thread(target=_face_worker, daemon=True)
                _face_thread.start()

                t_stt0 = time.time()
                user_text = self.stt.run(wav)
                print(f"[TIMING] STT: {time.time()-t_stt0:.2f}s", flush=True)
                _id_thread.join(timeout=2.0)
                _face_thread.join(timeout=2.0)
                # Voice ID wins when both fire — it's cheaper and already
                # proven out; face ID just fills in when the voice is unknown.
                speaker_name = _speaker_box.get("name") or _face_box.get("name")
                if user_text and not re.search(r"[^\W_]", user_text):
                    user_text = ""  # punctuation only, e.g. "." from noise
                if user_text and faint and is_whisper_phantom(user_text):
                    print(f"[STT] Ignoring '{user_text}': what Whisper hears in silence.", flush=True)
                    user_text = ""
                if not user_text:
                    if faint:
                        self._no_speech(src)
                    else:
                        self.enqueue("I did not detect any speech. Please repeat.")
                        skip_trigger = self._wait_tts()
                    continue

                print(f"[USER] {user_text}" + (f" (speaker: {speaker_name})" if speaker_name else ""), flush=True)
                self.interrupted.clear()
                life_ctx, life_fu = self.life.context_for(speaker_name)
                self.life.on_user_interaction(speaker_name, user_text)

                low = user_text.lower()

                # ── Nightly check-in reply capture ─────────────────────────
                if self._checkin_pending:
                    self._checkin_pending = False
                    if (time.time() <= self._checkin_deadline
                            and not any(x in low for x in ["stop", "cancel", "be quiet", "shut up", "not now"])):
                        mood = self.journal.add_entry(user_text)
                        print(f"[JOURNAL] Logged check-in (mood: {mood}).", flush=True)
                        self.ai._refresh_system_prompt()  # so BMO can reference it this session

                # ── Rude gesture detection ────────────────────────────────────
                _RUDE_TRIGGERS = [
                    "fuck you", "fuck u", "screw you", "f you",
                    "go to hell", "kiss my ass", "suck my", "up yours",
                ]
                if any(t in low for t in _RUDE_TRIGGERS):
                    if self._bmo_faces:
                        self._bmo_faces.set_emotion("rude")

                is_interrupt = False
                if any(x in low for x in ["stop", "cancel", "be quiet", "shut up"]):
                    self._do_interrupt()
                    # Already acted on; left set, it would cut this command's reply
                    # short and swallow the next wake word.
                    self.interrupted.clear()
                    is_interrupt = True

                # Memory commands
                if any(x in low for x in ["what do you remember", "what do you know about me", "what's my name", "do you remember me"]):
                    self.enqueue(self.ai.memory.summary())
                    skip_trigger = self._wait_tts()
                    continue

                # Journal recall
                if any(x in low for x in ["read my journal", "check my journal", "what's in my journal",
                                           "how have i been", "journal recap", "how have i been feeling"]):
                    self.enqueue(self.journal.summary())
                    skip_trigger = self._wait_tts()
                    continue

                # ── Inner life: quiet mode, BMO's own day and diary ─────────
                # ("chill" is taken — it starts lo-fi ambient mode.)
                if re.search(r"\b(?:you can talk again|quiet mode off|talk to me again)\b", low):
                    self.life.end_quiet()
                    self.enqueue("Yay! BMO is back!")
                    skip_trigger = self._wait_tts()
                    continue
                if re.search(r"\b(?:quiet mode|stop talking to yourself|leave me alone|"
                             r"give me some space|be quiet for a while)\b", low):
                    self.life.set_quiet(hours=3)
                    self.enqueue("Okay. BMO will be quiet for a while. Say you can talk again when you miss me.")
                    skip_trigger = self._wait_tts()
                    continue
                if re.search(r"\bhow (?:was|is|'s) your day\b|\bhow'?s your day\b|\bwhat did you do today\b", low):
                    self._set_state(S.THINK, "Remembering my day...")
                    self.enqueue(self.life.todays_story())
                    skip_trigger = self._wait_tts()
                    continue
                if re.search(r"\b(?:read|tell) me your diary\b|\bread your diary\b|\bwhat did you do yesterday\b", low):
                    self.enqueue(self.life.diary(days_ago=1))
                    skip_trigger = self._wait_tts()
                    continue

                # ── Speaker recognition (voice ID) ─────────────────────────
                _enroll_m = re.search(r"remember my voice as ([a-zA-Z]+)", low)
                if _enroll_m:
                    enroll_name = _normalize_name(_enroll_m.group(1).capitalize())
                    self.enqueue(self.voiceid.enroll(enroll_name, wav))
                    skip_trigger = self._wait_tts()
                    continue

                _forget_voice_m = re.search(r"forget ([a-zA-Z]+)'?s voice", low)
                if _forget_voice_m:
                    forget_name = _normalize_name(_forget_voice_m.group(1).capitalize())
                    self.enqueue(self.voiceid.forget(forget_name))
                    skip_trigger = self._wait_tts()
                    continue

                if any(x in low for x in ["whose voices do you know", "who do you recognize", "what voices do you know"]):
                    self.enqueue(self.voiceid.list_known())
                    skip_trigger = self._wait_tts()
                    continue

                if (re.search(r"recognize (me|my voice)", low)
                        or re.search(r"know (who i am|it'?s me|my voice)", low)
                        or any(x in low for x in ["who's talking", "who is talking",
                                                   "who's speaking", "who is speaking"])):
                    if speaker_name:
                        self.enqueue(f"You're {speaker_name} — I'd know that voice anywhere!")
                    else:
                        self.enqueue("I don't recognize your voice yet. Say 'remember my voice as' and your name!")
                    skip_trigger = self._wait_tts()
                    continue

                # ── Face recognition (face ID) ──────────────────────────────
                _enroll_face_m = re.search(r"remember (?:my face|what i look like) as ([a-zA-Z]+)", low)
                if _enroll_face_m:
                    enroll_face_name = _normalize_name(_enroll_face_m.group(1).capitalize())
                    self._set_state(S.THINK, "Learning your face...")
                    self.enqueue(self.faceid.enroll(enroll_face_name))
                    skip_trigger = self._wait_tts()
                    continue

                _forget_face_m = re.search(r"forget ([a-zA-Z]+)'?s face", low)
                if _forget_face_m:
                    forget_face_name = _normalize_name(_forget_face_m.group(1).capitalize())
                    self.enqueue(self.faceid.forget(forget_face_name))
                    skip_trigger = self._wait_tts()
                    continue

                if any(x in low for x in ["whose faces do you know", "who do you recognize by face",
                                           "what faces do you know"]):
                    self.enqueue(self.faceid.list_known())
                    skip_trigger = self._wait_tts()
                    continue

                # Full memory wipe (facts + session + semantic recall)
                if any(x in low for x in ["forget everything about me", "delete my memory", "wipe my memory"]):
                    self.ai.reset(forget_facts=True)
                    self.semantic_memory.forget_all()
                    self.enqueue("Done. I've forgotten everything about you. Nice to meet you!")
                    skip_trigger = self._wait_tts()
                    continue

                # ── Semantic recall ("what did I say about X") ─────────────
                _recall_m = (re.search(r"what did i (?:say|tell you|mention) about (.+)", low)
                             or re.search(r"do you remember (?:anything |me talking )?about (.+)", low)
                             or re.search(r"what do you know about (?!me\b)(.+)", low))
                if _recall_m:
                    topic = _recall_m.group(1).strip().rstrip("?.!")
                    memories = self.semantic_memory.recall(topic)
                    if memories:
                        context = "\n".join(f"- {m}" for m in memories)
                        self.enqueue(self.ai.summarise(context, f"What do you remember about {topic}?"))
                    else:
                        self.enqueue(f"I don't remember you mentioning anything about {topic}.")
                    skip_trigger = self._wait_tts()
                    continue

                # Session-only reset (keeps long-term facts)
                if any(x in low for x in ["forget everything", "reset memory", "clear memory"]):
                    self.ai.reset(forget_facts=False)
                    self.enqueue("Conversation cleared. But I still remember who you are!")
                    skip_trigger = self._wait_tts()
                    continue

                # ── Alarm/Reminder via skills (intercept before LLM) ──
                alarm_action = self._check_alarm_shortcut(low)
                if alarm_action:
                    self.enqueue(alarm_action)
                    skip_trigger = self._wait_tts()
                    continue

                # ── Fast Intent Matching ─────────────────────────────────
                fast_action = self.skills.match_intent(user_text)
                if fast_action:
                    action_name = fast_action.get("action")
                    if not self._is_privileged_action_allowed(action_name, speaker_name):
                        owner = CFG.get("voice_id_owner") or CFG.get("user_name", "")
                        print(f"[VOICEID] Blocked privileged action '{action_name}' — "
                              f"speaker={speaker_name!r}, owner={owner!r}", flush=True)
                        self.enqueue(f"That's a {owner}-only command and I don't recognize this voice, sorry.")
                        skip_trigger = self._wait_tts()
                        continue
                    self._set_state(S.THINK, "Executing action...")
                    result = self.skills.route(fast_action, original_query=user_text)
                    self.life.on_action(action_name)
                    if result:
                        self.enqueue(result)
                    else:
                        self.enqueue("Action processed but returned no response.")
                    skip_trigger = self._wait_tts()
                    self.sfx.play("done")

                    if fast_action.get("action") == "shutdown_system":
                        self.quit(poweroff=True)
                        continue

                    continue

                if is_interrupt:
                    continue

                # ── LLM (Conversational Fallback) ─────────────────────────
                t_llm0 = time.time()
                ooc_instruction = (
                    "(OOC: CRITICAL INSTRUCTION: Adjust your response length based on the user's input! "
                    "For simple greetings or short commands, give a VERY SHORT 1-2 sentence answer. "
                    "For complex questions, provide detail. Do not ramble. "
                    "Optionally end your response with an emotion tag like [HAPPY], [SAD], [ANGRY], "
                    "[EXCITED], [CONFUSED], [LAUGH], [IN_LOVE]. Do not say the tag aloud.)"
                )
                # ── Arabic mode: force Arabic replies ─────────────────────
                if self._language == "arabic":
                    arabic_instruction = (
                        "\n[LANGUAGE DIRECTIVE - MANDATORY]: You MUST respond ONLY in Arabic (العربية). "
                        "Do NOT use English at all. Write your entire response in Arabic script. "
                        "Keep it natural and conversational."
                    )
                    prompt_with_emotion = user_text + arabic_instruction + "\n" + ooc_instruction
                else:
                    prompt_with_emotion = user_text + "\n" + ooc_instruction
                if speaker_name:
                    prompt_with_emotion = f"(OOC: The person currently speaking is {speaker_name} — greet or address them by name if it feels natural, don't force it.)\n" + prompt_with_emotion
                if life_ctx:
                    prompt_with_emotion = life_ctx + prompt_with_emotion
                    self.life.followup_asked(life_fu)
                reply = self.ai.ask(prompt_with_emotion)
                print(f"[TIMING] LLM: {time.time()-t_llm0:.2f}s | Reply: {reply}", flush=True)
                self.semantic_memory.remember_async(user_text)  # background — never blocks the reply
                # Clean the reply so Piper TTS can speak the whole thought without breaking 
                safe_reply = reply.replace("'", "").replace("<think>", "").replace("</think>", "")
                if self._language == "arabic":
                    # Defensive net: if the model still slips a Latin-script name into
                    # an Arabic sentence despite the persona instruction, fix it up so
                    # it doesn't sound (or synthesize) wrong.
                    for latin, arabic in (("Ahmed", "أحمد"), ("Ahmad", "أحمد")):
                        safe_reply = safe_reply.replace(latin, arabic)
                else:
                    safe_reply = safe_reply.replace("Ahmed", "Ahmad")
                
                # Extract emotion tag if present — but never overwrite 'rude'
                extracted_emotion = None
                for tag in ["[HAPPY]", "[SAD]", "[ANGRY]", "[EXCITED]", "[CONFUSED]", "[LAUGH]", "[IN_LOVE]"]:
                    if tag in safe_reply:
                        extracted_emotion = tag.strip("[]").lower()
                        safe_reply = safe_reply.replace(tag, "")

                cur_em = self._bmo_faces._emotion if self._bmo_faces else None
                if extracted_emotion and self._bmo_faces and cur_em != "rude":
                    self._bmo_faces.set_emotion(extracted_emotion)

                
                # Split long responses into sentences so TTS doesn't drop anything after newlines
                # Also filter out bare emotion words (LLM sometimes outputs "LAUGH\n" with no brackets)
                _BARE_EMOTION_WORDS = {
                    "laugh", "lol", "haha", "happy", "sad", "angry", "excited",
                    "confused", "in_love", "love", "meme", "sleep", "music",
                    "calm", "sarcasm", "sarcastic", "shocked", "surprise",
                }
                sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', safe_reply) if s.strip()]
                sentences = [s for s in sentences
                             if s.lower().strip(".,!?; ") not in _BARE_EMOTION_WORDS]
                for s in sentences:
                    self.enqueue(s)


                skip_trigger = self._wait_tts()
                self.sfx.play("done")

            except Exception as e:
                traceback.print_exc()
                self._set_state(S.ERROR, f"Error: {str(e)[:40]}")
                self.sfx.play("error")
                time.sleep(2)

    def _check_alarm_shortcut(self, text):
        """Intercept simple alarm/reminder patterns before the LLM."""
        from bmo.alarms import AlarmManager as _AM
        # list alarms
        if "list alarm" in text or "my alarms" in text:
            return self.alarms.list_alarms()
        # cancel alarm
        m = re.search(r"cancel (?:the )?(.+?) alarm", text)
        if m:
            return self.alarms.cancel_alarm(m.group(1).strip())
        # list reminders
        if "list reminder" in text or "my reminders" in text:
            return self.alarms.list_reminders()
        return None

    def quit(self, poweroff=False):
        if self._exiting:
            return
        self._exiting = True
        self.alarms.stop()
        self.led.off()
        # Stop piper + any active audio BEFORE exit to prevent ALSA crash
        try:
            self.voice.shutdown()
        except Exception:
            pass
        import sounddevice as _sd
        try:
            _sd.stop()
        except Exception:
            pass
        print("[ARIA] Shutting down.", flush=True)
        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass
        
        if poweroff:
            import os
            os.system("sudo shutdown -h now")
            
        sys.exit(0)

# ─── Self-test ────────────────────────────────────────────────────────────────
def run_self_test():
    print("=== ARIA Self-Test ===", flush=True)
    import shutil

    checks = {
        "piper":     shutil.which("piper"),
        "sox":       shutil.which("sox"),
        "aplay":     shutil.which("aplay"),
        "espeak":    shutil.which("espeak"),
        "ffmpeg":    shutil.which("ffmpeg"),
        "ollama":    shutil.which("ollama"),
    }
    for name, path in checks.items():
        status = f"OK  ({path})" if path else "MISSING"
        print(f"  {name:12} {status}", flush=True)

    # Python deps
    for mod in ["whisper", "ollama", "sounddevice", "openwakeword",
                "spotipy", "requests", "duckduckgo_search"]:
        try:
            __import__(mod)
            print(f"  {mod:20} OK", flush=True)
        except ImportError:
            print(f"  {mod:20} MISSING — run: pip install {mod}", flush=True)

    # Ollama model
    try:
        import ollama as _ol
        models = [m.model for m in _ol.list().models]
        target = CFG.get("ollama_model", "llama3.2:3b")
        ok = any(target in m for m in models)
        print(f"  ollama model {target}: {'OK' if ok else 'NOT PULLED — run: ollama pull ' + target}",
              flush=True)
    except Exception as e:
        print(f"  ollama check failed: {e}", flush=True)

    # Voice model
    voices_dir = VOICES_DIR
    model_name = CFG.get("voice_model", "en_GB-alan-medium")
    voice_path = os.path.join(voices_dir, f"{model_name}.onnx")
    print(f"  voice model:         {'OK' if os.path.exists(voice_path) else 'MISSING — run setup.sh'}",
          flush=True)

    print("=== Test complete ===", flush=True)
