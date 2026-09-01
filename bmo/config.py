"""
Single source of truth for config defaults, merged with config.json.

Before this module existed, default values for the same keys were defined
in multiple places with different values (found during the restructure:
voice_id_threshold 0.65 vs 0.75, ollama_model "llama3.2:1b" vs "llama3.2:3b",
chat_memory_turns 15 vs 12). None of that ever caused a live bug only
because config.json happens to set all three explicitly today — but it was
one deleted key away from silently changing behavior. Canonical values below
were chosen to match what's already live in config.json.

Kept as a plain dict, not a dataclass: every consumer already does
cfg.get(key, default), and a typed object would mean touching every one of
those call sites for no functional gain.
"""
import json
import os

from bmo.paths import CONFIG_PATH

_DEFAULTS = {
    "assistant_name":     "ARIA",
    "wake_word_model":    "alexa",
    "voice_model":        "en_GB-alan-medium",
    "ollama_model":       "llama3.2:3b",
    "whisper_model":      "tiny.en",
    "input_device":       None,
    "instagram_username":    "",
    "instagram_password":    "",
    "instagram_post_enabled":  True,
    "instagram_story_enabled": True,
    "instagram_replies_enabled": True,
    "instagram_reply_interval_minutes": 30,
    "instagram_post_time":   "10:00",
    "instagram_story_time":  "18:00",
    "instagram_theme":       "BMO adventures, cute robot moments, Adventure Time vibes",
    "output_device":      None,
    "input_sample_rate":  None,
    "robotic_fx":         True,
    "led_enabled":        False,
    "led_idle_pin":       17,
    "led_listen_pin":     27,
    "led_think_pin":      22,
    "led_speak_pin":      23,
    "sound_effects":      True,
    "spotify_client_id":  "",
    "spotify_client_secret": "",
    "spotify_redirect_uri": "http://localhost:8888/callback",
    "home_assistant_url": "",
    "home_assistant_token": "",
    "news_count":         5,
    "chat_memory_turns":  12,
    "wake_threshold":     0.5,
    "silence_threshold":  0.006,
    "silence_duration":   1.5,
    "max_record_seconds": 25,
    "checkin_enabled":    True,
    "checkin_time":       "21:30",
    "voice_id_enabled":   True,
    "voice_id_threshold": 0.65,
    "voice_id_owner":     "",
    "face_saturation_boost": 1.0,
    "face_brightness_boost": 1.0,
    "semantic_memory_enabled":   True,
    "semantic_embed_model":      "all-minilm",
    "semantic_recall_threshold": 0.35,
}


def load_config() -> dict:
    cfg = dict(_DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"[CFG] Warning: {e}", flush=True)
    return cfg
