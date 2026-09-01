#!/usr/bin/env python3
"""
BMO Voice ID — lightweight speaker recognition using voice embeddings.

Enrolls short voice samples per person ("remember my voice as Ahmad") and
identifies who's speaking on each turn, purely from the wav file already
captured by the normal recording pipeline. No extra mic time needed.

Requires `resemblyzer` (pip install resemblyzer). If it's not installed,
this module degrades to a no-op — identify() always returns None — instead
of crashing the rest of BMO.
"""
import os
import json
import numpy as np

from bmo.paths import DATA_DIR, VOICEPRINTS_FILE as VOICEPRINT_FILE

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    HAS_RESEMBLYZER = True
except ImportError:
    HAS_RESEMBLYZER = False


def _load():
    try:
        with open(VOICEPRINT_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(VOICEPRINT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _cosine(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class VoiceIDManager:
    def __init__(self, enabled=True, threshold=0.75):
        self.enabled   = enabled and HAS_RESEMBLYZER
        self.threshold = threshold
        self._encoder  = None
        self._profiles = _load()  # {name: {"embedding": [...], "samples": n}}

        if enabled and not HAS_RESEMBLYZER:
            print("[VOICEID] resemblyzer not installed — speaker recognition disabled. "
                  "Install with: pip install resemblyzer", flush=True)
        elif self.enabled:
            try:
                self._encoder = VoiceEncoder()
                print(f"[VOICEID] Ready. {len(self._profiles)} enrolled voice(s): "
                      f"{', '.join(self._profiles) or '(none)'}", flush=True)
            except Exception as e:
                print(f"[VOICEID] Failed to load encoder: {e}", flush=True)
                self.enabled = False

    def _embed(self, wav_path):
        wav = preprocess_wav(wav_path)
        if wav is None or len(wav) == 0:
            return None
        return self._encoder.embed_utterance(wav)

    def enroll(self, name, wav_path):
        """Add (or refine, via running average) a voice sample for `name`."""
        if not self.enabled:
            return "Voice recognition isn't set up on this BMO — resemblyzer isn't installed."
        try:
            emb = self._embed(wav_path)
        except Exception as e:
            print(f"[VOICEID] Enroll error: {e}", flush=True)
            return "Couldn't process that recording, sorry."
        if emb is None:
            return "That was too short or quiet for me to learn your voice — try again with a full sentence."

        existing = self._profiles.get(name)
        if existing:
            n   = existing.get("samples", 1)
            old = np.array(existing["embedding"])
            avg = (old * n + emb) / (n + 1)
            self._profiles[name] = {"embedding": avg.tolist(), "samples": n + 1}
            _save(self._profiles)
            return f"Got it, refined your voice profile, {name}!"

        self._profiles[name] = {"embedding": emb.tolist(), "samples": 1}
        _save(self._profiles)
        return f"Nice to meet you, {name}! I'll remember your voice."

    def identify(self, wav_path):
        """Returns the best-matching enrolled name, or None if unknown/disabled."""
        if not self.enabled or not self._profiles:
            return None
        try:
            emb = self._embed(wav_path)
        except Exception:
            return None
        if emb is None:
            return None

        best_name, best_score = None, 0.0
        for name, profile in self._profiles.items():
            score = _cosine(emb, profile["embedding"])
            if score > best_score:
                best_name, best_score = name, score

        matched = best_name if (best_name and best_score >= self.threshold) else None
        print(f"[VOICEID] Best match: {best_name} score={best_score:.2f} "
              f"(threshold {self.threshold}) → {'MATCH' if matched else 'no match'}", flush=True)
        return matched

    def forget(self, name):
        key = next((k for k in self._profiles if k.lower() == name.lower()), None)
        if key:
            del self._profiles[key]
            _save(self._profiles)
            return f"I've forgotten {key}'s voice."
        return f"I don't have a voice profile for {name}."

    def list_known(self):
        if not self._profiles:
            return "I don't recognize anyone's voice yet. Say 'remember my voice as' and your name!"
        return "I know these voices: " + ", ".join(self._profiles.keys()) + "."
