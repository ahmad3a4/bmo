"""
SkillsRouter — orchestrates intent matching (via registry.py's ordered table)
and action dispatch (a name->handler dict, safe to be unordered since a grep
audit confirmed zero duplicate action names across the original if-chain).
"""
import os
import time
import datetime
import threading

from bmo.paths import MEMORY_FILE
from bmo.self_coder import SelfCoder
from bmo.skills.spotify import SpotifySkill
from bmo.skills.pc_control import PCControlSkill
from bmo.skills.home_assistant import HomeAssistantSkill
from bmo.skills.notes import NotesSkill
from bmo.skills.misc import (
    get_weather, web_search, get_news, set_system_volume,
    get_joke, get_fact, get_bored_activity, calculate, get_system_status,
)
from bmo.skills.registry import INTENT_REGISTRY

try:
    from bmo.tv import TVSkill
    HAS_TV = True
except ImportError:
    HAS_TV = False
    print("[SKILLS] bmo_tv not found.", flush=True)

try:
    from bmo.media import MediaDisplay
    HAS_MEDIA = True
except ImportError:
    HAS_MEDIA = False
    print("[SKILLS] bmo_media not found.", flush=True)

try:
    from bmo.games import GamesLauncher
    HAS_GAMES = True
except ImportError:
    HAS_GAMES = False


class SkillsRouter:
    def __init__(self, cfg, timer_cb, ai_summarise=None, media_display=None):
        self.spotify  = SpotifySkill(cfg)
        self.ha       = HomeAssistantSkill(cfg)
        self.pc       = PCControlSkill(cfg)
        self.timer_cb = timer_cb
        self.ai_sum   = ai_summarise  # callable(context, question) → str
        self.news_n   = cfg.get("news_count", 5)
        self._last_query = ""
        self.instagram = None  # set via set_instagram()

        # ── TV Control ───────────────────────────────────────────────────
        self.tv = TVSkill(cfg) if HAS_TV else None

        # ── Self Coder ───────────────────────────────────────────────────
        groq_key = cfg.get("groq_api_key", "")
        self.self_coder = SelfCoder(groq_key) if groq_key else None

        # ── Media Display ────────────────────────────────────────────────
        self.media = media_display  # MediaDisplay instance (set from GUI)

        # ── Games Launcher ───────────────────────────────────────────────
        self.games = None  # set later via set_games()

        # ── Notes / Reminders ────────────────────────────────────────────
        self.notes = NotesSkill(MEMORY_FILE)

        self._routes = self._build_routes()

    def set_media(self, media_display):
        """Attach the MediaDisplay instance after GUI is ready."""
        self.media = media_display

    def set_games(self, launcher):
        """Attach the GamesLauncher instance after GUI is ready."""
        self.games = launcher

    def set_ambient(self, ambient_mode):
        """Attach the AmbientMode instance after GUI is ready."""
        self.ambient = ambient_mode

    def set_brain(self, brain):
        """Attach the BMOBrain so brain_status command can report AI backend."""
        self._brain = brain

    def set_instagram(self, scheduler):
        """Attach the InstagramScheduler instance."""
        self.instagram = scheduler

    def match_intent(self, text):
        """Fast regex-based intent matching to bypass LLM for core commands."""
        low = text.lower()
        for _name, builder in INTENT_REGISTRY:
            result = builder(self, low, text)
            if result is not None:
                return result
        return None

    # ─── route() handlers ──────────────────────────────────────────────────
    # Handlers needing more than one expression are small methods; simple
    # ones are inline lambdas in _build_routes(). Every handler takes just
    # `action_data` — original_query is available via self._last_query,
    # which route() sets before dispatch (identical timing to the original).

    def _route_generate_skill(self, action_data):
        if self.self_coder:
            return self.self_coder.generate_skill(action_data.get("prompt", ""))
        return "My self-coding module is disabled. Check API keys."

    def _route_execute_dynamic(self, action_data):
        mod = action_data.get("module")
        try:
            return mod.execute(action_data, action_data.get("text", ""))
        except Exception as e:
            return f"My dynamic skill crashed. Error: {e}"

    def _route_search_web(self, action_data):
        query = action_data.get("query", self._last_query)
        raw   = web_search(query)
        if self.ai_sum and raw and raw != "No results found.":
            return self.ai_sum(raw, query)
        return raw[:400]

    def _route_set_timer(self, action_data):
        secs  = int(action_data.get("seconds", 60))
        label = action_data.get("label", "timer")
        threading.Timer(secs, lambda: self.timer_cb(
            f"Timer alert. Your {label} timer has finished."
        )).start()
        m, s  = divmod(secs, 60)
        h, m  = divmod(m, 60)
        parts = []
        if h: parts.append(f"{h} hour{'s' if h != 1 else ''}")
        if m: parts.append(f"{m} minute{'s' if m != 1 else ''}")
        if s: parts.append(f"{s} second{'s' if s != 1 else ''}")
        return f"Timer set for {' '.join(parts)}. I will notify you."

    def _route_brain_status(self, action_data):
        if hasattr(self, "_brain") and self._brain:
            return self._brain.status()
        return "Brain status: AI backend not directly accessible from skills."

    def _route_tv(self, action_data, act):
        # Preserves the original structure exactly, including the fact that
        # "tv_unmute" was never added to the "module not available" fallback
        # tuple — a pre-existing quirk, not something introduced here.
        if self.tv:
            if act == "tv_on":          return self.tv.turn_on()
            if act == "tv_off":         return self.tv.turn_off()
            if act == "tv_mute":        return self.tv.mute()
            if act == "tv_unmute":      return self.tv.mute()  # toggle
            if act == "tv_volume_up":   return self.tv.volume_up()
            if act == "tv_volume_down": return self.tv.volume_down()
            if act == "tv_set_volume":  return self.tv.set_volume(int(action_data.get("level", 50)))
            if act == "tv_channel":     return self.tv.set_channel(int(action_data.get("channel", 1)))
            if act == "tv_input":       return self.tv.set_input(action_data.get("source", "hdmi1"))
            if act == "tv_launch_app":  return self.tv.launch_app(action_data.get("app", ""))
            if act == "tv_search":      return self.tv.search(action_data.get("query", ""))
            if act == "tv_press":       return self.tv.press_key(action_data.get("key", "home"))
            if act == "tv_status":      return self.tv.get_status()
            if act == "tv_connect":
                if hasattr(self.tv, "adb") and self.tv.adb.available:
                    return self.tv.adb.reconnect()
                return self.tv.get_status()
        elif act in ("tv_on", "tv_off", "tv_mute", "tv_volume_up", "tv_volume_down",
                     "tv_set_volume", "tv_channel", "tv_input", "tv_launch_app",
                     "tv_status", "tv_connect"):
            return "TV control module is not available. Check bmo_tv.py installation."
        return None

    def _route_show_instagram_qr(self, action_data):
        if self.media:
            qr_path = os.path.join(self.media._base_dir, "instagram_qr.png")
            if not os.path.exists(qr_path):
                try:
                    import urllib.request
                    url = "https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=https://instagram.com/hey.bmo.ai&format=png"
                    urllib.request.urlretrieve(url, qr_path)
                except Exception as e:
                    print(f"[MEDIA] QR download failed: {e}", flush=True)
            if os.path.exists(qr_path):
                self.media.show_image(qr_path)
                return "Here is the QR code for my Instagram account! Scan it with your phone to follow me."
            return "I could not load the QR code image right now."
        return "Media display is not available."

    def _route_show_meme(self, action_data):
        if self.media:
            topic = action_data.get("topic", "")
            result_holder = ["Fetching a meme for you!"]
            def _meme_done(text):
                result_holder[0] = text
            self.media.show_meme(callback=_meme_done, topic=topic)
            time.sleep(3)
            return result_holder[0]
        return "Media display is not available in headless mode."

    def _route_launch_games(self, action_data):
        if self.games and self.games.available:
            # Run in a background thread so BMO voice loop stays alive
            threading.Thread(target=self.games.launch, daemon=True).start()
            return "Game time! Launching RetroArch. Say hey bmo when you're done."
        if not self.games:
            return "Games module not available. Check bmo_games.py."
        return "RetroArch is not installed. Run: sudo apt install retroarch"

    def _build_routes(self):
        return {
            # ── Dynamic Self Coding ──────────────────────────────────────
            "generate_skill":  self._route_generate_skill,
            "execute_dynamic": self._route_execute_dynamic,

            # ── Spotify ──────────────────────────────────────────────────
            "play_spotify":     lambda ad: self.spotify.play(ad.get("query", "")),
            "pause_spotify":    lambda ad: self.spotify.pause(),
            "resume_spotify":   lambda ad: self.spotify.resume(),
            "next_track":       lambda ad: self.spotify.next_track(),
            "previous_track":   lambda ad: self.spotify.prev_track(),
            "spotify_volume":   lambda ad: self.spotify.set_volume(ad.get("level", 50)),
            "current_track":    lambda ad: self.spotify.current_track(),

            # ── Time / Date ──────────────────────────────────────────────
            "get_time": lambda ad: f"The current time is {datetime.datetime.now().strftime('%I:%M %p')}.",
            "get_date": lambda ad: f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}.",

            # ── Weather ──────────────────────────────────────────────────
            "get_weather": lambda ad: get_weather(ad.get("location", "your city")),

            # ── Web Search (with optional AI summary) ────────────────────
            "search_web": self._route_search_web,

            # ── News ─────────────────────────────────────────────────────
            "get_news": lambda ad: get_news(self.news_n),

            # ── Timers ───────────────────────────────────────────────────
            "set_timer": self._route_set_timer,

            # ── Volume ───────────────────────────────────────────────────
            "set_volume": lambda ad: set_system_volume(ad.get("level", 75)),

            # ── Home Assistant ────────────────────────────────────────────
            "home_light_on":      lambda ad: self.ha.light_on(ad.get("entity", "light.main")),
            "home_light_off":     lambda ad: self.ha.light_off(ad.get("entity", "light.main")),
            "home_toggle":        lambda ad: self.ha.toggle(ad.get("entity", "switch.main")),
            "home_status":        lambda ad: self.ha.status(ad.get("entity", "")),
            "home_list_entities": lambda ad: self.ha.list_entities(),

            # ── Bored Activity ────────────────────────────────────────────
            "bored_activity": lambda ad: get_bored_activity(),

            # ── Notes / Reminders ─────────────────────────────────────────
            "note_add":    lambda ad: self.notes.add(ad.get("text", "")),
            "note_list":   lambda ad: self.notes.list_notes(),
            "note_delete": lambda ad: self.notes.delete(int(ad.get("index", 1))),
            "note_clear":  lambda ad: self.notes.clear_all(),
            "note_find":   lambda ad: self.notes.find(ad.get("keyword", "")),

            # ── Fun ──────────────────────────────────────────────────────
            "get_joke": lambda ad: get_joke(),
            "get_fact": lambda ad: get_fact(),

            # ── Calculator ────────────────────────────────────────────────
            "calculate": lambda ad: calculate(ad.get("expression", "0")),

            # ── System ───────────────────────────────────────────────────
            "shutdown_system": lambda ad: "Shutting down the system. Goodbye!",
            "system_status":   lambda ad: get_system_status(),
            "brain_status":    self._route_brain_status,

            # ── PC Control ───────────────────────────────────────────────
            "pc_turn_on":        lambda ad: self.pc.turn_on(),
            "pc_lock":           lambda ad: self.pc.lock(),
            "pc_sleep":          lambda ad: self.pc.sleep(),
            "pc_shutdown":       lambda ad: self.pc.shutdown(),
            "pc_mute":           lambda ad: self.pc.mute(),
            "pc_youtube":        lambda ad: self.pc.youtube(),
            "pc_spotify":        lambda ad: self.pc.spotify(),
            "pc_launch_app":     lambda ad: self.pc.launch_app(ad.get("app", "")),
            "pc_close_app":      lambda ad: self.pc.close_app(ad.get("app", "")),
            "pc_restart":        lambda ad: self.pc.restart(),
            "pc_set_volume":     lambda ad: self.pc.set_volume(ad.get("level", "")),
            "pc_top_processes":  lambda ad: self.pc.top_processes(),
            "pc_screenshot":     lambda ad: self.pc.screenshot(),
            "pc_read_clipboard": lambda ad: self.pc.read_clipboard(),
            "pc_playtime":       lambda ad: self.pc.playtime(ad.get("app", "")),
            "pc_gpu_temp":       lambda ad: self.pc.gpu_temp(),

            # ── TV Control ───────────────────────────────────────────────
            "tv_on":          lambda ad: self._route_tv(ad, "tv_on"),
            "tv_off":         lambda ad: self._route_tv(ad, "tv_off"),
            "tv_mute":        lambda ad: self._route_tv(ad, "tv_mute"),
            "tv_unmute":      lambda ad: self._route_tv(ad, "tv_unmute"),
            "tv_volume_up":   lambda ad: self._route_tv(ad, "tv_volume_up"),
            "tv_volume_down": lambda ad: self._route_tv(ad, "tv_volume_down"),
            "tv_set_volume":  lambda ad: self._route_tv(ad, "tv_set_volume"),
            "tv_channel":     lambda ad: self._route_tv(ad, "tv_channel"),
            "tv_input":       lambda ad: self._route_tv(ad, "tv_input"),
            "tv_launch_app":  lambda ad: self._route_tv(ad, "tv_launch_app"),
            "tv_search":      lambda ad: self._route_tv(ad, "tv_search"),
            "tv_press":       lambda ad: self._route_tv(ad, "tv_press"),
            "tv_status":      lambda ad: self._route_tv(ad, "tv_status"),
            "tv_connect":     lambda ad: self._route_tv(ad, "tv_connect"),

            # ── Instagram QR Code ─────────────────────────────────────────
            "show_instagram_qr": self._route_show_instagram_qr,

            # ── Memes & Media ─────────────────────────────────────────────
            "show_meme":    self._route_show_meme,
            "show_picture": lambda ad: (self.media.show_random_local() if self.media
                                         else "Media display is not available in headless mode."),
            "show_image_url": lambda ad: (self.media.show_image_url(ad.get("url", ""))
                                           if (self.media and ad.get("url", ""))
                                           else "Media display is not available."),
            "clear_display": lambda ad: (self.media.clear() if self.media else "Nothing to clear."),

            # ── Games ─────────────────────────────────────────────────────
            "launch_games": self._route_launch_games,
            "stop_games":   lambda ad: (self.games.stop() if self.games else "Games module not available."),

            # ── Ambient Mode ──────────────────────────────────────────────
            "start_ambient": lambda ad: (self.ambient.start() if self.ambient else "Ambient mode module not available."),
            "stop_ambient":  lambda ad: (self.ambient.stop() if self.ambient else "Ambient mode is not active."),

            # ── Instagram ─────────────────────────────────────────────────
            "ig_post":        lambda ad: (self.instagram.manual_post(ad.get("theme", "")) if self.instagram
                                           else "Instagram scheduler is not running."),
            "ig_story":       lambda ad: (self.instagram.manual_story(ad.get("theme", "")) if self.instagram
                                           else "Instagram scheduler is not running."),
            "ig_reply_check": lambda ad: (self.instagram.manual_reply_check() if self.instagram
                                           else "Instagram scheduler is not running."),
            "ig_followers":   lambda ad: (f"The Instagram account has {self.instagram.get_followers()} followers."
                                           if self.instagram else "Instagram scheduler is not running."),
        }

    def route(self, action_data, original_query=""):
        act = action_data.get("action", "").lower()
        self._last_query = original_query
        handler = self._routes.get(act)
        if handler:
            return handler(action_data)
        return None
