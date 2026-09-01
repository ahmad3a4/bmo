#!/usr/bin/env python3
"""
ARIA Alarms — Persistent alarms and reminders stored to JSON.
A background thread fires callbacks when alarms/reminders are due.
"""
import os, json, threading, time, datetime

from bmo.paths import DATA_DIR, ALARMS_FILE as ALARM_FILE, REMINDERS_FILE as REMIND_FILE


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load(path):
    _ensure_dir()
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


def _save(path, data):
    _ensure_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class AlarmManager:
    """
    Alarms  — fire daily at a fixed HH:MM time.
    Reminders — fire once after N minutes.
    """

    def __init__(self, speak_cb):
        """speak_cb(text) is called when an alarm/reminder fires."""
        self.speak_cb = speak_cb
        self._running  = True
        self._thread   = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._announce_pending_reminders()

    # ─── Alarms ──────────────────────────────────────────────────────────

    def set_alarm(self, time_str, label="alarm"):
        """time_str: 'HH:MM' in 24-hour format."""
        try:
            datetime.datetime.strptime(time_str, "%H:%M")
        except ValueError:
            return f"Invalid time format '{time_str}'. Use HH:MM."
        alarms = _load(ALARM_FILE)
        # Overwrite if same label exists
        alarms = [a for a in alarms if a.get("label") != label]
        alarms.append({"time": time_str, "label": label, "fired_today": False})
        _save(ALARM_FILE, alarms)
        return f"Alarm set for {time_str} labelled {label}."

    def list_alarms(self):
        alarms = _load(ALARM_FILE)
        if not alarms:
            return "No alarms set."
        return "Alarms: " + ", ".join(
            f"{a['label']} at {a['time']}" for a in alarms
        ) + "."

    def cancel_alarm(self, label):
        alarms = _load(ALARM_FILE)
        new    = [a for a in alarms if a.get("label") != label]
        if len(new) == len(alarms):
            return f"No alarm labelled {label} found."
        _save(ALARM_FILE, new)
        return f"Alarm {label} cancelled."

    # ─── Reminders ───────────────────────────────────────────────────────

    def add_reminder(self, text, minutes):
        reminders = _load(REMIND_FILE)
        fire_at   = (
            datetime.datetime.now() + datetime.timedelta(minutes=int(minutes))
        ).isoformat()
        reminders.append({"text": text, "fire_at": fire_at, "done": False})
        _save(REMIND_FILE, reminders)
        return f"Reminder set: '{text}' in {minutes} minutes."

    def list_reminders(self):
        reminders = [r for r in _load(REMIND_FILE) if not r.get("done")]
        if not reminders:
            return "No pending reminders."
        items = []
        for r in reminders:
            try:
                dt  = datetime.datetime.fromisoformat(r["fire_at"])
                now = datetime.datetime.now()
                mins = max(0, int((dt - now).total_seconds() / 60))
                items.append(f"{r['text']} in {mins} minutes")
            except Exception:
                items.append(r["text"])
        return "Reminders: " + ", ".join(items) + "."

    # ─── Background loop ─────────────────────────────────────────────────

    def _loop(self):
        last_date = None
        while self._running:
            now  = datetime.datetime.now()
            date = now.date()

            # Reset "fired_today" at midnight
            if last_date != date:
                alarms = _load(ALARM_FILE)
                for a in alarms:
                    a["fired_today"] = False
                _save(ALARM_FILE, alarms)
                last_date = date

            # Check alarms
            alarms = _load(ALARM_FILE)
            changed = False
            for a in alarms:
                if a.get("fired_today"):
                    continue
                try:
                    alarm_time = datetime.datetime.strptime(
                        a["time"], "%H:%M"
                    ).replace(year=now.year, month=now.month, day=now.day)
                except Exception:
                    continue
                if now >= alarm_time:
                    a["fired_today"] = True
                    changed = True
                    self.speak_cb(f"Alarm. {a['label']}. Wake up or take action.")
            if changed:
                _save(ALARM_FILE, alarms)

            # Check reminders
            reminders = _load(REMIND_FILE)
            changed   = False
            for r in reminders:
                if r.get("done"):
                    continue
                try:
                    fire_at = datetime.datetime.fromisoformat(r["fire_at"])
                except Exception:
                    continue
                if now >= fire_at:
                    r["done"] = True
                    changed   = True
                    self.speak_cb(f"Reminder. {r['text']}.")
            if changed:
                _save(REMIND_FILE, reminders)

            time.sleep(10)  # Check every 10 seconds

    def _announce_pending_reminders(self):
        """On startup, announce any overdue reminders."""
        reminders = _load(REMIND_FILE)
        now = datetime.datetime.now()
        changed = False
        for r in reminders:
            if r.get("done"):
                continue
            try:
                fire_at = datetime.datetime.fromisoformat(r["fire_at"])
                if now >= fire_at:
                    r["done"] = True
                    changed   = True
                    self.speak_cb(f"Overdue reminder from before. {r['text']}.")
            except Exception:
                pass
        if changed:
            _save(REMIND_FILE, reminders)

    def stop(self):
        self._running = False
