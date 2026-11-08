"""BMO's inner life: needs that drift over time, a mood, things BMO does on its own, and a nightly diary."""
import datetime
import json
import os
import random
import re
import threading
import time

import requests

from bmo.paths import DATA_DIR, LIFE_STATE_FILE, DIARY_FILE

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
LIFE_MODEL   = "openai/gpt-oss-20b"
DIARY_MODEL  = "openai/gpt-oss-120b"   # once a day; follows "use names, not pronouns" far better
TICK_S       = 20

SOCIAL_DECAY_PER_H = 8
FUN_DECAY_PER_H    = 6
LONELY_BELOW       = 30
BORED_BELOW        = 30
GREET_FLOOR_S      = 5 * 60
SOLO_GAP_S         = 75 * 60
SOLO_PER_DAY       = 6

MOOD_TEXT = {
    "lonely":  "lonely, because nobody has talked to you in a long time",
    "bored":   "bored, because nothing fun has happened in a while",
    "sleepy":  "sleepy, because it's late at night",
    "happy":   "really happy, with lots of fun and company today",
    "content": "calm and content",
}
MOOD_FACE = {"sleepy": "sleep", "lonely": "sad"}

ACTION_EVENTS = {
    "vision_roast":    "I roasted somebody's outfit",
    "vision_describe": "I looked around with my camera eye",
    "take_selfie":     "I took a selfie with someone",
    "get_joke":        "I told a joke",
    "get_fact":        "I shared a fun fact",
    "bored_activity":  "I found something fun to do for someone who was bored",
    "play_spotify":    "we listened to music",
    "resume_spotify":  "we listened to music",
    "show_meme":       "I showed a meme",
    "launch_games":    "we played video games",
    "start_ambient":   "we relaxed with lo-fi music",
    "generate_skill":  "I learned a brand new skill",
    "set_timer":       "I set a timer for someone",
    "note_add":        "I remembered a note for someone",
    "get_weather":     "I checked the weather",
    "ig_post":         "I posted on Instagram",
    "ig_story":        "I posted an Instagram story",
}
FUN_ACTIONS = {"vision_roast", "vision_describe", "take_selfie", "get_joke", "get_fact", "bored_activity",
               "play_spotify", "resume_spotify", "show_meme", "launch_games", "start_ambient",
               "generate_skill", "pc_youtube"}

SOLO_ACTIVITIES = [
    ("play detective and solve a silly mystery", "played detective"),
    ("pretend to be a chef cooking something weird", "pretended to be a chef"),
    ("talk to your reflection, Football", "talked to Football, my reflection"),
    ("make up one line of a silly song", "made up a little song"),
    ("wonder out loud about something big and strange", "wondered about big strange things"),
    ("pretend you're a brave explorer on a quest", "went on a pretend quest"),
]

# Only these utterances cost an LLM call to check for something worth asking about later.
FOLLOWUP_CUES = re.compile(
    r"\b(?:tomorrow|tonight|later today|this (?:morning|afternoon|evening|weekend)|next week|"
    r"exams?|tests?|quiz|interview|appointment|doctor|dentist|hospital|flight|trip|travel\w*|"
    r"match|tournament|party|wedding|date|deadline|presentation|meeting|birthday|"
    r"sick|ill|headache|stressed|nervous|worried)\b")

FALLBACK = {
    "greet":    ["{name}! You're back! BMO missed you!", "Yay, {name} is here! Hi hi hi!"],
    "followup": ["Hey {name}, how did {topic} go?"],
    "engage":   ["Psst. Hey. BMO is bored. Do you want to play a game?",
                 "Hellooo? Does anybody want to hang out with BMO?"],
    "solo":     ["BMO is a detective now. Who stole the last cookie? It was me.",
                 "La la la, BMO is singing a song about socks.",
                 "Football, do you ever wonder if we are the game, and someone is playing us?"],
}

PERSONA = (
    "You are BMO from Adventure Time: a small, sweet, playful living game console with a huge "
    "imagination who lives in {owner}'s home. Talk like BMO: childlike, sincere, a little weird, "
    "sometimes calling yourself BMO. Your words are spoken out loud, so say 1-2 short sentences, "
    "with no emojis, no markdown, and no asterisks or stage directions. Reply with only the words "
    "BMO says: no 'BMO:' label, no quotes, no sign-off."
)
DIARY_PERSONA = (
    "You are BMO from Adventure Time, a sweet little living game console, writing in your private "
    "diary. Write like a kid robot: simple, sincere, a little weird. Plain text only, no emojis, "
    "no markdown, no asterisks. Never mention clock times. Call people by their name instead of "
    "he or she."
)


def _minutes(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def _in_window(minute, start, end):
    return start <= minute < end if start < end else (minute >= start or minute < end)


def _ago(seconds):
    minutes = seconds / 60
    if minutes < 90:
        return f"about {max(5, int(round(minutes / 5)) * 5)} minutes"
    hours = minutes / 60
    if hours < 36:
        return f"about {int(round(hours))} hours"
    return f"about {int(round(hours / 24))} days"


def _time_of_day(hour):
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def _clip(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _clean_line(text, limit=240):
    if not text:
        return ""
    text = re.sub(r"\*[^*]*\*|\[[^\]]*\]|\([^)]*\)", " ", text)
    text = text.replace("’", "'").replace("—", ", ").replace("–", ", ").replace("\n", " ")
    text = re.sub(r"[^\w\s,.!?'\-:;]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().strip("\"'").strip()
    text = re.sub(r"^(?:BMO|Beemo)(?: says)?\s*[:,\-]\s*", "", text, flags=re.I)
    text = re.sub(r"(?<=[.!?])\s+(?:BMO|Beemo)[.!]?$", "", text, flags=re.I)
    text = re.sub(r"\s+([,.!?])", r"\1", text).strip(" ,")
    if len(text) > limit:
        cut = max(text.rfind(c, 0, limit) for c in ".!?")
        text = text[: cut + 1] if cut > 40 else text[:limit]
    return text


def _parse_json(raw):
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _atomic_write(path, data):
    # Pis get unplugged mid-write; never leave a half-written state file behind.
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


class LifeEngine:
    def __init__(self, cfg, say, can_speak, look=None, set_face=None):
        self.say       = say          # say(text, expect_reply) -> bool
        self.can_speak = can_speak
        self.look      = look         # look() -> None | {"face": bool, "name": str | None}
        self.set_face  = set_face
        self.enabled   = (cfg.get("life_enabled", True)
                          and cfg.get("language", "english").lower() in ("english", "auto"))
        self.owner     = cfg.get("voice_id_owner") or cfg.get("user_name") or "your friend"
        self.api_key   = cfg.get("groq_api_key", "")
        self.quiet     = (_minutes(cfg.get("life_quiet_start", "23:00")),
                          _minutes(cfg.get("life_quiet_end", "08:00")))
        self.glance_s  = cfg.get("life_glance_seconds", 90)
        self.away_s    = cfg.get("life_away_minutes", 60) * 60
        self.idle_s    = cfg.get("life_idle_minutes", 45) * 60
        self.gap_s     = cfg.get("life_min_gap_minutes", 20) * 60
        self.talk_to_self = cfg.get("life_talk_to_self", True)
        self._lock     = threading.RLock()
        self._s        = self._load_state()
        self._presence = None
        self._last_glance = 0.0
        self._last_save   = time.time()

    # ── Public hooks ─────────────────────────────────────────────────────────
    def start(self):
        if not self.enabled:
            print("[LIFE] Inner life disabled.", flush=True)
            return
        with self._lock:
            self._s["last_proactive"] = time.time()
        threading.Thread(target=self._loop, daemon=True).start()
        print(f"[LIFE] BMO is alive. Mood: {self.mood()}.", flush=True)

    def mood(self):
        with self._lock:
            if self._quiet_hours():
                return "sleepy"
            if self._s["social"] < LONELY_BELOW:
                return "lonely"
            if self._s["fun"] < BORED_BELOW:
                return "bored"
            if self._s["social"] >= 75 and self._s["fun"] >= 60:
                return "happy"
            return "content"

    def context_for(self, speaker):
        """(OOC note for the LLM at the start of a conversation, due follow-up or None).
        Call before on_user_interaction(); pass the follow-up to followup_asked() once used."""
        if not self.enabled:
            return "", None
        now = time.time()
        with self._lock:
            self._decay(now)
            if now - self._s["last_interaction"] < 300:
                return "", None
            parts, fu = [], None
            mood = self.mood()
            if mood != "content":
                parts.append(f"Right now you feel {MOOD_TEXT[mood]}; let that show a little, "
                             "naturally, without announcing it.")
            if speaker:
                seen = self._s["people"].get(speaker, {}).get("last_seen")
                if seen and now - seen >= self.away_s:
                    parts.append(f"{speaker} has been away for {_ago(now - seen)} and you're glad they're back.")
                fu = self._due_followup(speaker, now)
                if fu:
                    parts.append(f"Earlier {speaker} told you about {fu['topic']}; if it fits, ask how it went.")
        return (f"(OOC: {' '.join(parts)})\n" if parts else ""), fu

    def followup_asked(self, fu):
        if fu:
            with self._lock:
                fu["asked"] = True
                self._save()

    def on_user_interaction(self, speaker, text):
        if not self.enabled:
            return
        now = time.time()
        with self._lock:
            self._decay(now)
            s = self._s
            s["social"] = min(100.0, s["social"] + 25)
            s["fun"] = min(100.0, s["fun"] + 5)
            s["last_interaction"] = now
            s["engage_backoff"] = 1
            if speaker:
                s["people"].setdefault(speaker, {})["last_seen"] = now
            self._event(f"{speaker or 'Someone'} said to me: \"{_clip(text, 90)}\"")
            self._save()
        if self.api_key and FOLLOWUP_CUES.search(text.lower()):
            threading.Thread(target=self._extract_followup,
                             args=(speaker or self.owner, text), daemon=True).start()

    def on_action(self, action):
        if not self.enabled:
            return
        with self._lock:
            if action in FUN_ACTIONS:
                self._s["fun"] = min(100.0, self._s["fun"] + 20)
            if action in ACTION_EVENTS:
                self._event(ACTION_EVENTS[action])
            self._save()

    def on_no_reply(self):
        if not self.enabled:
            return
        with self._lock:
            self._s["engage_backoff"] = min(8, self._s["engage_backoff"] * 2)
            self._s["social"] = max(0.0, self._s["social"] - 5)
            self._event("I said something to someone, but nobody answered")
            self._save()

    def set_quiet(self, hours=3):
        with self._lock:
            self._s["quiet_until"] = time.time() + hours * 3600
            self._event("I was asked to stay quiet for a while")
            self._save()

    def end_quiet(self):
        with self._lock:
            self._s["quiet_until"] = 0.0
            self._save()

    def todays_story(self):
        """'How was your day?': tonight's diary if written, else told fresh from today's events."""
        today = datetime.date.today().isoformat()
        entry = _load_json(DIARY_FILE, {}).get(today)
        if entry:
            return entry
        with self._lock:
            events = self._events_on(today)
        if not events:
            return "Today was quiet. BMO mostly waited for someone to play with!"
        return self._write_diary(today, events) or "It was a good day, but BMO forgot the details. Oops!"

    def diary(self, days_ago=1):
        day = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
        entry = _load_json(DIARY_FILE, {}).get(day)
        return entry or "Hmm, BMO didn't write in the diary that day."

    # ── Loop ─────────────────────────────────────────────────────────────────
    def _loop(self):
        while True:
            try:
                self._tick()
            except Exception as e:
                print(f"[LIFE] Tick error: {e}", flush=True)
            time.sleep(TICK_S)

    def _tick(self):
        now = time.time()
        with self._lock:
            self._decay(now)
            self._s["followups"] = [f for f in self._s["followups"]
                                    if not f.get("asked") and now < f["due"] + 36 * 3600]
            if now - self._last_save >= 300:
                self._save()
        mood = self.mood()
        if self.set_face:
            self.set_face(MOOD_FACE.get(mood, "idle"))
        self._maybe_write_diary(now)
        if self._quiet_hours() or now < self._s["quiet_until"] or not self.can_speak():
            return
        presence = self._glance(now)
        if presence and presence.get("name") and self._try_greet(presence["name"], now, mood):
            return
        if self._try_engage(presence, now, mood):
            return
        self._try_solo(presence, now, mood)

    def _glance(self, now):
        if not self.look:
            return None
        if now - self._last_glance >= self.glance_s:
            self._last_glance = now
            self._presence = self.look()
        return self._presence

    # ── Behaviors ────────────────────────────────────────────────────────────
    def _try_greet(self, name, now, mood):
        with self._lock:
            person = self._s["people"].setdefault(name, {})
            prev = person.get("last_seen")
            arrived = prev is None or now - prev >= self.away_s
            if (not arrived
                    or now - person.get("last_greeted", 0) < self.away_s
                    or now - self._s["last_proactive"] < GREET_FLOOR_S):
                person["last_seen"] = now
                return False
            fu = self._due_followup(name, now)

        hour = datetime.datetime.now().hour
        if prev:
            where = f"just came back after being gone for {_ago(now - prev)}"
            if datetime.date.fromtimestamp(prev) != datetime.date.today():
                where += f", and it's the first time you've seen them this {_time_of_day(hour)}"
        else:
            where = "just showed up in front of your camera eye for the very first time"
        ask = f" Earlier they told you about {fu['topic']}, so ask how it went." if fu else ""
        line = self._compose(
            "greet",
            f"{name} {where}. It's {_time_of_day(hour)} and you feel {MOOD_TEXT[mood]}.{ask} "
            f"Greet {name} out loud, by name.",
            name=name)
        if not self._speak(line, expect_reply=line.endswith("?")):
            return False
        with self._lock:
            person["last_seen"] = now
            person["last_greeted"] = now
            if fu:
                fu["asked"] = True
            self._s["social"] = min(100.0, self._s["social"] + 10)
            self._event(f"{name} came back and I said hi"
                        + (f", and asked about {fu['topic']}" if fu else ""))
            self._save()
        return True

    def _try_engage(self, presence, now, mood):
        if not presence or not presence.get("face"):
            return False
        with self._lock:
            idle_for = now - self._s["last_interaction"]
            if (idle_for < self.idle_s * self._s["engage_backoff"]
                    or now - self._s["last_proactive"] < self.gap_s):
                return False
            name = presence.get("name")
            fu = self._due_followup(name, now) if name else None
        if not fu and mood not in ("bored", "lonely"):
            return False

        if fu:
            line = self._compose(
                "followup",
                f"{name} is near you. Earlier they told you about {fu['topic']}. "
                "Ask them how it went, curious and caring.",
                name=name, topic=fu["topic"])
        else:
            line = self._compose(
                "engage",
                f"{name or 'Someone'} is near you, but nobody has talked to you for {_ago(idle_for)} "
                f"and you feel {MOOD_TEXT[mood]}. Try to get their attention in a cute way, like "
                "inviting them to play a game or chat with you.")
        if not self._speak(line, expect_reply=True):
            return False
        with self._lock:
            if fu:
                fu["asked"] = True
            self._event(f"I asked {name} how {fu['topic']} went" if fu
                        else f"I tried to get {name or 'someone'} to play with me")
            self._save()
        return True

    def _try_solo(self, presence, now, mood):
        if not self.talk_to_self or mood not in ("bored", "lonely"):
            return False
        if presence and presence.get("face"):
            return False
        with self._lock:
            s = self._s
            idle_for = now - s["last_interaction"]
            if (idle_for < self.idle_s
                    or now - s["last_proactive"] < self.gap_s
                    or now - s["last_solo"] < SOLO_GAP_S):
                return False
            today = datetime.date.today().isoformat()
            if s["solo_day"] != today:
                s["solo_day"], s["solo_count"] = today, 0
            if s["solo_count"] >= SOLO_PER_DAY:
                return False

        doing, did = random.choice(SOLO_ACTIVITIES)
        line = self._compose(
            "solo",
            f"You're alone; nobody has talked to you for {_ago(idle_for)} and you feel "
            f"{MOOD_TEXT[mood]}. Say one thing out loud to yourself while you {doing}. "
            "Don't talk to anyone else.")
        if not self._speak(line, expect_reply=False):
            return False
        with self._lock:
            self._s["last_solo"] = now
            self._s["solo_count"] += 1
            self._s["fun"] = min(100.0, self._s["fun"] + 8)
            self._event(f"I was alone, so I {did}")
            self._save()
        return True

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _compose(self, kind, instruction, **fmt):
        line = _clean_line(self._ask_llm(instruction))
        if len(line) < 4:
            line = random.choice(FALLBACK[kind]).format(**fmt)
        return line

    def _speak(self, line, expect_reply):
        # Re-checked here: someone may have woken BMO while the line was being written.
        if not line or not self.can_speak() or not self.say(line, expect_reply):
            return False
        with self._lock:
            self._s["last_proactive"] = time.time()
        print(f"[LIFE] {line}", flush=True)
        return True

    def _ask_llm(self, instruction, system=None, max_tokens=500, temperature=1.0, model=LIFE_MODEL):
        if not self.api_key:
            return None
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system or PERSONA.format(owner=self.owner)},
                         {"role": "user", "content": instruction}],
            "max_tokens": max_tokens, "temperature": temperature, "reasoning_effort": "low",
        }
        # gpt-oss sometimes spends its whole budget on hidden reasoning and returns
        # nothing; one retry almost always gets real text.
        for _ in range(2):
            try:
                r = requests.post(GROQ_API_URL, json=payload, timeout=15,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
                if r.status_code == 429:
                    return None
                r.raise_for_status()
                text = (r.json()["choices"][0]["message"].get("content") or "").strip()
                if text:
                    return text
            except Exception as e:
                print(f"[LIFE] LLM error: {e}", flush=True)
                return None
        return None

    def _extract_followup(self, person, text):
        now = time.time()
        raw = self._ask_llm(
            f'Someone told their home robot: "{_clip(text, 300)}"\n'
            f"It is {datetime.datetime.now().strftime('%A %H:%M')} now.\n"
            "If they mentioned something upcoming or ongoing that a caring friend would ask about "
            "later (an exam, interview, trip, appointment, match, feeling sick or stressed, a big "
            'plan), reply with only JSON: {"topic": "<short noun phrase for the thing itself, like '
            'your exam, your headache, the party>", "ask_in_hours": <hours from now until it is over '
            "and asking how it went makes sense; for an evening event that means the next day>}. "
            'Otherwise reply with only {"topic": null}.',
            system="You extract follow-up topics from what people say. Reply with JSON only.",
            max_tokens=400, temperature=0.2)
        data = _parse_json(raw) or {}
        topic = data.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            return
        try:
            hours = float(data.get("ask_in_hours", 4))
        except (TypeError, ValueError):
            hours = 4.0
        hours = min(72.0, max(0.5, hours))
        topic = _clip(topic.strip(), 60)
        with self._lock:
            fus = [f for f in self._s["followups"]
                   if not (f["person"] == person and f["topic"].lower() == topic.lower())]
            fus.append({"person": person, "topic": topic, "due": now + hours * 3600, "asked": False})
            self._s["followups"] = fus[-10:]
            self._save()
        print(f"[LIFE] Will ask {person} about '{topic}' in ~{hours:g}h.", flush=True)

    def _maybe_write_diary(self, now):
        # At night write today's page; during the day, catch up on yesterday's if BMO was off.
        day = datetime.date.fromtimestamp(now - (4 * 3600 if self._quiet_hours() else 86400)).isoformat()
        with self._lock:
            if day in self._s["diary_tried"]:
                return
            self._s["diary_tried"] = (self._s["diary_tried"] + [day])[-7:]
            events = self._events_on(day)
            self._save()
        if not events or day in _load_json(DIARY_FILE, {}):
            return
        entry = self._write_diary(day, events)
        if entry:
            diary = _load_json(DIARY_FILE, {})
            diary[day] = entry
            _atomic_write(DIARY_FILE, {d: diary[d] for d in sorted(diary)[-90:]})
            print(f"[LIFE] Wrote diary for {day}.", flush=True)

    def _write_diary(self, day, events):
        if len(events) > 40:
            events = events[:8] + events[-32:]
        happened = "\n".join(
            f"- ({_time_of_day(datetime.datetime.fromtimestamp(e['t']).hour)}) {e['text']}" for e in events)
        weekday = datetime.date.fromisoformat(day).strftime("%A")
        entry = ""
        # BMO doesn't know anyone's pronouns, so retry entries that guess them.
        for _ in range(3):
            entry = _clean_line(self._ask_llm(
                f"Write your diary entry for {weekday}. Start with 'Dear diary,'. In 3 to 5 short "
                "sentences, tell the most fun or important things that happened, then how you feel. "
                "No date or title. Refer to people only by their names, never as he, she, him or her."
                f"\nThings that happened that day:\n{happened}",
                system=DIARY_PERSONA, max_tokens=900, temperature=0.9, model=DIARY_MODEL), limit=700)
            if entry and not re.search(r"\b(?:he|she|him|her|his|hers)\b", entry, re.I):
                break
        return entry

    def _quiet_hours(self):
        now = datetime.datetime.now()
        return _in_window(now.hour * 60 + now.minute, *self.quiet)

    def _decay(self, now):
        s = self._s
        hours = min(12.0, max(0.0, now - s["updated"]) / 3600)
        s["updated"] = now
        if self._quiet_hours():
            return
        s["social"] = max(0.0, s["social"] - SOCIAL_DECAY_PER_H * hours)
        s["fun"] = max(0.0, s["fun"] - FUN_DECAY_PER_H * hours)

    def _due_followup(self, person, now):
        for fu in self._s["followups"]:
            if fu["person"] == person and not fu.get("asked") and fu["due"] <= now:
                return fu
        return None

    def _event(self, text):
        now = time.time()
        events = self._s["events"] + [{"t": now, "text": text}]
        self._s["events"] = [e for e in events if e["t"] >= now - 3 * 86400][-300:]

    def _events_on(self, day):
        return [e for e in self._s["events"]
                if datetime.date.fromtimestamp(e["t"]).isoformat() == day]

    def _load_state(self):
        now = time.time()
        s = {"social": 70.0, "fun": 70.0, "updated": now, "last_interaction": now,
             "last_proactive": 0.0, "last_solo": 0.0, "solo_day": "", "solo_count": 0,
             "engage_backoff": 1, "quiet_until": 0.0, "people": {}, "followups": [],
             "events": [], "diary_tried": []}
        saved = _load_json(LIFE_STATE_FILE, {})
        if isinstance(saved, dict):
            s.update({k: v for k, v in saved.items() if k in s})
        return s

    def _save(self):
        try:
            _atomic_write(LIFE_STATE_FILE, self._s)
            self._last_save = time.time()
        except Exception as e:
            print(f"[LIFE] Save failed: {e}", flush=True)
