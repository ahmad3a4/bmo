#!/usr/bin/env python3
"""
BMO Journal — nightly check-in scheduler + persistent day/mood journal.

A background thread fires `on_fire()` once a day at `checkin_time`. The
caller (aria.py) is responsible for actually speaking the question and
routing the next spoken reply into add_entry() — this module only owns
scheduling and storage, since mic/TTS access is the agent's job.
"""
import os
import json
import threading
import time
import datetime

from bmo.paths import DATA_DIR, JOURNAL_FILE

_MOOD_WORDS = {
    "happy":    ["great", "good", "awesome", "amazing", "happy", "fun", "excited",
                 "productive", "relaxing", "nice", "wonderful"],
    "stressed": ["stressed", "tired", "exhausted", "busy", "overwhelmed", "hard",
                 "rough", "hectic", "annoying", "frustrating"],
    "sad":      ["sad", "bad", "terrible", "awful", "down", "depressed", "lonely",
                 "upset", "horrible"],
}

CHECKIN_QUESTIONS = [
    "Hey, before you go — how was your day?",
    "Quick check-in — how are you feeling tonight?",
    "How'd today treat you?",
]


def _detect_mood(text):
    low = text.lower()
    best_mood, best_score = "neutral", 0
    for mood, words in _MOOD_WORDS.items():
        score = sum(1 for w in words if w in low)
        if score > best_score:
            best_mood, best_score = mood, score
    return best_mood


def _load():
    try:
        with open(JOURNAL_FILE) as f:
            return json.load(f)
    except Exception:
        return {"last_checkin_date": None, "entries": []}


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(JOURNAL_FILE, "w") as f:
        json.dump(data, f, indent=2)


class JournalManager:
    def __init__(self, on_fire, checkin_time="21:30", enabled=True):
        self.on_fire      = on_fire
        self.checkin_time = checkin_time
        self.enabled      = enabled
        self._data        = _load()
        self._running     = True
        self._thread      = None
        if self.enabled:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            print(f"[JOURNAL] Nightly check-in scheduled for {checkin_time}.", flush=True)

    def add_entry(self, text):
        mood  = _detect_mood(text)
        today = datetime.date.today().isoformat()
        entry = {
            "date": today,
            "time": datetime.datetime.now().strftime("%H:%M"),
            "text": text,
            "mood": mood,
        }
        self._data.setdefault("entries", []).append(entry)
        self._data["entries"] = self._data["entries"][-60:]  # cap history
        self._data["last_checkin_date"] = today
        _save(self._data)
        return mood

    def recent(self, n=5):
        return self._data.get("entries", [])[-n:]

    def summary(self):
        entries = self.recent(3)
        if not entries:
            return "You haven't checked in with me yet — ask me how I'm doing sometime and I'll ask you back!"
        parts = [f"on {e['date']} you felt {e['mood']}" for e in entries]
        return "Here's your recent check-ins: " + ", and ".join(parts) + "."

    def build_prompt_snippet(self):
        entries = self.recent(3)
        if not entries:
            return ""
        lines = [f"- {e['date']}: felt {e['mood']} — \"{e['text'][:120]}\"" for e in entries]
        return "Recent journal check-ins with your creator:\n" + "\n".join(lines)

    def _loop(self):
        while self._running:
            try:
                now   = datetime.datetime.now()
                today = now.date().isoformat()
                if (self._data.get("last_checkin_date") != today
                        and now.strftime("%H:%M") >= self.checkin_time):
                    fired = False
                    try:
                        fired = bool(self.on_fire())
                    except Exception as e:
                        print(f"[JOURNAL] on_fire error: {e}", flush=True)
                    if fired:
                        self._data["last_checkin_date"] = today
                        _save(self._data)
                    # If not fired (e.g. agent busy), retry on the next tick
                    # instead of waiting until tomorrow.
            except Exception as e:
                print(f"[JOURNAL] Loop error: {e}", flush=True)
            time.sleep(30)

    def stop(self):
        self._running = False
