import os
import json
import datetime


# ─── Notes & Reminders ────────────────────────────────────────────────────────
class NotesSkill:
    """Lightweight notes stored in the same memory.json used by BMOMemory."""

    KEY = "notes"

    def __init__(self, memory_file):
        self._path = memory_file

    def _load(self):
        try:
            with open(self._path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, data):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[NOTES] Save error: {e}", flush=True)

    def add(self, text):
        text = text.strip()
        if not text:
            return "I didn't catch what to remember. Try again."
        data = self._load()
        notes = data.get(self.KEY, [])
        notes.append({"text": text, "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
        data[self.KEY] = notes
        self._save(data)
        return f"Got it! I've noted: {text}"

    def list_notes(self):
        notes = self._load().get(self.KEY, [])
        if not notes:
            return "You have no notes saved yet."
        items = [f"{i+1}. {n['text']}" for i, n in enumerate(notes)]
        return "Here are your notes: " + ". ".join(items) + "."

    def delete(self, index):
        """Delete by 1-based index."""
        data = self._load()
        notes = data.get(self.KEY, [])
        if not notes:
            return "You have no notes to delete."
        if index < 1 or index > len(notes):
            return f"I only have {len(notes)} note{'s' if len(notes) != 1 else ''}. Which one?"
        removed = notes.pop(index - 1)["text"]
        data[self.KEY] = notes
        self._save(data)
        return f"Deleted note {index}: {removed}"

    def clear_all(self):
        data = self._load()
        count = len(data.get(self.KEY, []))
        data[self.KEY] = []
        self._save(data)
        return f"Cleared all {count} note{'s' if count != 1 else ''}."

    def find(self, keyword):
        notes = self._load().get(self.KEY, [])
        matches = [n for n in notes if keyword.lower() in n["text"].lower()]
        if not matches:
            return f"No notes found containing '{keyword}'."
        items = [f"{i+1}. {n['text']}" for i, n in enumerate(matches)]
        return "Found: " + ". ".join(items) + "."
