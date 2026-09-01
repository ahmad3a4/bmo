"""
The ordered intent-matching table, extracted verbatim from the original
SkillsRouter.match_intent() (one giant sequential method). Each entry here
corresponds 1:1 to one of that method's original commented sections, in the
EXACT SAME ORDER — order is load-bearing (e.g. "set volume to 40 on my pc"
must be checked before the general Spotify volume regex, or the wrong skill
wins; "game time" must be checked before "what time is it").

Each builder is `(router, low, text) -> dict | None`. `router` gives access
to router.self_coder for the one entry that needs it (dynamic skill lookup).
Do not reorder this list without re-running the golden-file corpus diff.
"""
import re


def _b_self_coding_command(router, low, text):
    # ── Self Coding Command ───────────────────────────────────────────────
    m = re.search(r"\b(?:write|create|learn)(?: a)?(?: new)? skill (?:to|that) (.+)\b", low)
    if m:
        return {"action": "generate_skill", "prompt": m.group(1)}
    return None


def _b_dynamic_skills(router, low, text):
    # ── Check Dynamic Skills ─────────────────────────────────────────────
    if router.self_coder:
        mod = router.self_coder.match_dynamic_intent(low)
        if mod:
            return {"action": "execute_dynamic", "module": mod, "text": text}
    return None


def _b_games_first(router, low, text):
    # ── Games (checked FIRST — 'game time' must not match get_time) ──────────
    if re.search(r"\b(game time|gaming time|game mode|gaming mode)\b", low):
        return {"action": "launch_games"}
    if re.search(r"(?:let.?s|wanna|want to|open|start|launch)\b.{0,15}\b(game|games|retroarch|arcade)", low):
        return {"action": "launch_games"}
    if re.search(r"\b(play games|let.?s play|open games)\b", low):
        return {"action": "launch_games"}
    if re.search(r"\b(stop|exit|close|quit|turn off|end) (playing|games?)\b", low):
        return {"action": "stop_games"}
    return None


def _b_ambient(router, low, text):
    # ── Ambient / Relax Mode ─────────────────────────────────────────────
    if re.search(r"\b(stop|exit|close|quit|turn off|end) (relax|ambient|lo-fi|study|chill)", low):
        return {"action": "stop_ambient"}
    if re.search(r"\b(relax|ambient|lo-fi|study|chill)", low):
        return {"action": "start_ambient"}
    return None


def _b_pc_control(router, low, text):
    # ── PC Control ───────────────────────────────────────────────────────
    if re.search(r"\b(turn on|wake up|start|boot)\b.*?(pc|computer|laptop|windows)", low):
        return {"action": "pc_turn_on"}
    if re.search(r"\b(lock|put to sleep|sleep|turn off|shut down|shutdown)\b.*?(pc|computer|laptop|windows)", low):
        if "lock" in low: return {"action": "pc_lock"}
        if "sleep" in low: return {"action": "pc_sleep"}
        if "turn off" in low or "shut down" in low or "shutdown" in low: return {"action": "pc_shutdown"}
    if re.search(r"\bmute\b.*?(pc|computer|laptop|windows)", low): return {"action": "pc_mute"}
    if re.search(r"\bopen (youtube|spotify)\b.*?(pc|computer|laptop|windows)", low):
        return {"action": f"pc_{re.search(r'open (youtube|spotify)', low).group(1)}"}
    _launch_m = re.search(
        r"\b(?:open|launch|start|run|fire up|pull up)\s+(.+?)\s+(?:on|from)\s+(?:my |the )?(?:pc|computer|laptop|windows)\b", low)
    if _launch_m:
        return {"action": "pc_launch_app", "app": _launch_m.group(1).strip()}

    if re.search(r"\brestart\b.*?(pc|computer|laptop|windows)", low):
        return {"action": "pc_restart"}

    _close_m = re.search(
        r"\b(?:close|kill|quit|exit)\s+(.+?)\s+(?:on|from)\s+(?:my |the )?(?:pc|computer|laptop|windows)\b", low)
    if _close_m:
        return {"action": "pc_close_app", "app": _close_m.group(1).strip()}

    _vol_m = re.search(r"\b(?:set )?volume\s+(?:to\s+)?(\d{1,3})\b.*?(pc|computer|laptop|windows)", low)
    if _vol_m:
        return {"action": "pc_set_volume", "level": int(_vol_m.group(1))}

    if re.search(r"\bwhat'?s running\b.*?(pc|computer|laptop|windows)", low) or "top processes" in low:
        return {"action": "pc_top_processes"}

    if re.search(r"\btake a screenshot\b", low) or re.search(r"\bscreenshot\b.*?(pc|computer|screen)", low):
        return {"action": "pc_screenshot"}

    if re.search(r"\bwhat'?s in my clipboard\b|\bread my clipboard\b|\bcheck my clipboard\b", low):
        return {"action": "pc_read_clipboard"}

    _playtime_m = re.search(r"how long (?:have i been|was i) playing (.+?)(?:\?|$)", low)
    if _playtime_m:
        return {"action": "pc_playtime", "app": _playtime_m.group(1).strip()}

    if re.search(r"\bam i throttl(?:e|ing)\b|\bgpu temp(?:erature)?\b", low):
        return {"action": "pc_gpu_temp"}
    return None


def _b_system_shutdown(router, low, text):
    # ── System Shutdown ──────────────────────────────────────────────────
    if re.search(r"\b(shut down|turn off|power off)( the system| bmo| yourself)?\b", low) and "light" not in low and "tv" not in low:
        return {"action": "shutdown_system"}
    return None


def _b_time_date(router, low, text):
    # Time / Date (requires question context to avoid matching 'game time' etc.)
    if re.search(r"\bwhat time\b|\bwhat'?s the time\b|\btime is it\b", low): return {"action": "get_time"}
    if re.search(r"\b(date|what is today|what day is it)\b", low): return {"action": "get_date"}
    return None


def _b_weather(router, low, text):
    # Weather
    m = re.search(r"weather in ([\w\s]+)", low)
    if m: return {"action": "get_weather", "location": m.group(1).strip()}
    if re.search(r"\bweather\b", low): return {"action": "get_weather", "location": "your city"}
    return None


def _b_spotify(router, low, text):
    # Spotify
    m = re.search(r"(?:play|put on) (.+) on spotify", low)
    if m: return {"action": "play_spotify", "query": m.group(1).strip()}
    if re.search(r"\bpause\b.*?(music|spotify)?", low) or re.search(r"\bstop\b.*?(music|spotify)", low): return {"action": "pause_spotify"}
    # Only resume Spotify if explicitly asking for music or resume
    if re.search(r"\b(resume|continue|unpause)( music| spotify)?\b", low) and "tv" not in low:
        return {"action": "resume_spotify"}
    if re.search(r"\b(play|start) (music|spotify)\b", low) and "tv" not in low:
        return {"action": "resume_spotify"}
    if "next" in low or "skip" in low: return {"action": "next_track"}
    if "previous" in low or "go back" in low: return {"action": "previous_track"}
    if "what is playing" in low or "current track" in low: return {"action": "current_track"}
    return None


def _b_volume_generic(router, low, text):
    # Volume (Highly tolerant for STT errors)
    m = re.search(r"(?:volume|sound|loud|turn it up|turn up|turn it down|turn down|speed|falling).{0,15}\b(\d{1,3})\b", low)
    if m: return {"action": "set_volume", "level": int(m.group(1))}
    return None


def _b_home_assistant_lights(router, low, text):
    # Home Assistant lights
    m = re.search(r"(?:turn|switch) on (?:the )?(.+) light", low)
    if m: return {"action": "home_light_on", "entity": f"light.{m.group(1).replace(' ', '_')}"}
    m = re.search(r"(?:turn|switch) off (?:the )?(.+) light", low)
    if m: return {"action": "home_light_off", "entity": f"light.{m.group(1).replace(' ', '_')}"}
    return None


def _b_tv_control(router, low, text):
    # ── TV Control ───────────────────────────────────────────────────────
    if re.search(r"turn (on|off) (?:the )?tv", low):
        state = "on" if "on" in re.search(r"turn (on|off)", low).group(1) else "off"
        return {"action": f"tv_{state}"}
    if re.search(r"(?:tv|television) on", low):   return {"action": "tv_on"}
    if re.search(r"(?:tv|television) off", low):  return {"action": "tv_off"}
    if re.search(r"wake (?:up )?(?:the )?tv", low): return {"action": "tv_on"}
    if re.search(r"(?:connect|reconnect|link|pair).{0,15}tv", low): return {"action": "tv_connect"}
    if re.search(r"tv.{0,10}(?:connect|reconnect)", low): return {"action": "tv_connect"}
    if "mute" in low and ("tv" in low or "television" in low): return {"action": "tv_mute"}
    if "unmute" in low and ("tv" in low or "television" in low): return {"action": "tv_unmute"}
    if re.search(r"tv volume up", low):   return {"action": "tv_volume_up"}
    if re.search(r"tv volume down", low): return {"action": "tv_volume_down"}
    m = re.search(r"(?:set )?tv volume (?:to )?(\d+)", low)
    if m: return {"action": "tv_set_volume", "level": int(m.group(1))}
    m = re.search(r"(?:switch|change|set) (?:to )?channel (\d+)", low)
    if m: return {"action": "tv_channel", "channel": int(m.group(1))}
    m = re.search(r"(?:switch|change|set) (?:tv )?input (?:to )?(.+)", low)
    if m: return {"action": "tv_input", "source": m.group(1).strip()}
    m = re.search(r"(?:open|launch|start) (?:the )?(?:application |app )?(.+) on (?:the )?(?:tv|roku)", low)
    if m: return {"action": "tv_launch_app", "app": m.group(1).strip()}
    m = re.search(r"(?:search|find|look up) (.+) on (?:the )?(?:tv|television|youtube)", low)
    if m: return {"action": "tv_search", "query": m.group(1).strip()}
    m = re.search(r"(?:press|hit|type) (.+) on (?:the )?(?:tv|television)", low)
    if m: return {"action": "tv_press", "key": m.group(1).strip()}
    if re.search(r"tv status", low): return {"action": "tv_status"}
    return None


def _b_instagram_qr(router, low, text):
    # ── Instagram QR Code ────────────────────────────────────────────────
    if re.search(r"\b(?:show|display|open|view|qr)\b.{0,15}\b(?:qr|instagram|insta|social|code)\b", low) or low == "qr":
        return {"action": "show_instagram_qr"}
    return None


def _b_memes_media(router, low, text):
    # ── Memes & Media ────────────────────────────────────────────────────
    # Topical meme: "show me a meme about cats" / "cat meme"
    m = re.search(r"(?:show (?:me )?(?:a )?)?(?:meme|memes?) (?:about|on|of) ([\w\s]+)", low)
    if m: return {"action": "show_meme", "topic": m.group(1).strip()}
    m = re.search(r"([\w\s]+?) memes?", low)
    if m and m.group(1).strip() not in ("a", "random", "funny", "show", "show me"):
        return {"action": "show_meme", "topic": m.group(1).strip()}
    if re.search(r"show (?:me )?(?:a )?meme", low): return {"action": "show_meme"}
    if re.search(r"(?:random |funny )?meme", low):   return {"action": "show_meme"}
    if re.search(r"show (?:me )?(?:a )?picture", low): return {"action": "show_picture"}
    if re.search(r"show (?:me )?(?:a )?(?:random )?(?:image|photo|pic)", low): return {"action": "show_picture"}
    if re.search(r"close (?:the )?(?:image|picture|meme|display)", low): return {"action": "clear_display"}
    if re.search(r"clear (?:the )?(?:screen|display)", low): return {"action": "clear_display"}
    m = re.search(r"show (?:image|picture|photo) (?:from )?(?:url )?(.+)", low)
    if m: return {"action": "show_image_url", "url": m.group(1).strip()}
    return None


def _b_timers(router, low, text):
    # Timers
    m = re.search(r"set a timer for (\d+) seconds?", low)
    if m: return {"action": "set_timer", "seconds": int(m.group(1)), "label": "timer"}
    m = re.search(r"set a (\d+) minute timer", low)
    if m: return {"action": "set_timer", "seconds": int(m.group(1))*60, "label": "timer"}
    return None


def _b_instagram(router, low, text):
    # ── Instagram ────────────────────────────────────────────────────────
    if re.search(r"\b(?:post|publish|share|add|create|make|do|generate)\b.{0,20}\b(?:story|stories)\b", low):
        m = re.search(r"(?:about|on|of) ([\w\s]+?)(?:\.|$)", low)
        theme = m.group(1).strip() if m else ""
        return {"action": "ig_story", "theme": theme}
    if re.search(r"\b(?:post|publish|share|add|create|make|do|generate)\b.{0,20}\b(?:instagram|insta|post)\b", low):
        m = re.search(r"(?:about|on|of) ([\w\s]+?)(?:\.|$)", low)
        theme = m.group(1).strip() if m else ""
        return {"action": "ig_post", "theme": theme}
    if re.search(r"(?:check|reply|respond).{0,20}(?:comment|comments|instagram)", low):
        return {"action": "ig_reply_check"}
    if re.search(r"(?:how many|how much).{0,15}follower", low):
        return {"action": "ig_followers"}
    if re.search(r"instagram.{0,15}(?:follower|stat|status)", low):
        return {"action": "ig_followers"}
    return None


def _b_notes(router, low, text):
    # ── Notes / Reminders ────────────────────────────────────────────────
    # Delete note by number: "delete note 2" / "remove note 3"
    m = re.search(r"\b(?:delete|remove|erase|forget) note (\d+)", low)
    if m: return {"action": "note_delete", "index": int(m.group(1))}
    # Clear all notes
    if re.search(r"\b(?:clear|delete|remove|erase) all notes?\b", low):
        return {"action": "note_clear"}
    # Read notes: "what are my notes" / "show notes" / "list notes"
    if re.search(r"\b(?:show|list|read|what are)(?: my)? notes?\b", low):
        return {"action": "note_list"}
    if re.search(r"\bmy notes?\b", low):
        return {"action": "note_list"}
    # Search notes: "find note about meeting"
    m = re.search(r"\b(?:find|search)(?: a)? note (?:about|with|containing) ([\w\s]+)", low)
    if m: return {"action": "note_find", "keyword": m.group(1).strip()}
    # Add note: "remember that..." / "note that..." / "add a note..."
    m = re.search(r"\b(?:remember|note|add a note|write down|save)(?: a note)?(?: that| to)? (.+)", low)
    if m: return {"action": "note_add", "text": m.group(1).strip()}
    return None


def _b_bored(router, low, text):
    # ── Bored Activity ───────────────────────────────────────────────────
    if re.search(r"\b(?:i.?m bored|what (?:should|can) i do|give me (?:something|an activity)|suggest (?:something|an activity)|bored)", low):
        return {"action": "bored_activity"}
    return None


def _b_fun_web(router, low, text):
    # Fun / Web
    if "tell me a joke" in low: return {"action": "get_joke"}
    if "tell me a fact" in low: return {"action": "get_fact"}
    if "news" in low: return {"action": "get_news"}
    if "system status" in low: return {"action": "system_status"}
    if re.search(r"(?:brain|ai|groq|ollama) status", low): return {"action": "brain_status"}
    if re.search(r"(?:which|what) (?:ai|model|brain)", low): return {"action": "brain_status"}

    m = re.search(r"calculate (.+)", low)
    if m: return {"action": "calculate", "expression": m.group(1)}

    m = re.search(r"(?:search the web for|search for|look up) (.+)", low)
    if m: return {"action": "search_web", "query": m.group(1).strip()}
    return None


def _b_games_second(router, low, text):
    # ── Games ────────────────────────────────────────────────────────────
    if re.search(r"(?:let.?s|wanna|want to|open|start|launch|play)\b.{0,15}\b(game|games|play|retroarch|arcade)", low):
        return {"action": "launch_games"}
    if re.search(r"\b(game mode|gaming mode|game time)\b", low):
        return {"action": "launch_games"}
    return None


# Order is load-bearing — do not reorder without re-running the golden-file diff.
INTENT_REGISTRY = [
    ("self_coding_command",   _b_self_coding_command),
    ("dynamic_skills",        _b_dynamic_skills),
    ("games_first",           _b_games_first),
    ("ambient",               _b_ambient),
    ("pc_control",            _b_pc_control),
    ("system_shutdown",       _b_system_shutdown),
    ("time_date",             _b_time_date),
    ("weather",               _b_weather),
    ("spotify",               _b_spotify),
    ("volume_generic",        _b_volume_generic),
    ("home_assistant_lights", _b_home_assistant_lights),
    ("tv_control",            _b_tv_control),
    ("instagram_qr",          _b_instagram_qr),
    ("memes_media",           _b_memes_media),
    ("timers",                _b_timers),
    ("instagram",             _b_instagram),
    ("notes",                 _b_notes),
    ("bored",                 _b_bored),
    ("fun_web",               _b_fun_web),
    ("games_second",          _b_games_second),
]
