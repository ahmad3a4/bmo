#!/usr/bin/env python3
"""
BMO Vision — camera capture + description via Groq's vision-capable model.

Uses rpicam-still (the current Pi camera stack, not the legacy raspistill/
vcgencmd tools) to grab a still photo, then sends it to Groq's
qwen/qwen3.8-27b — confirmed vision-capable on standard API access. The
newer Llama 4 Scout/Maverick vision models exist on Groq but returned a
live 404 (not enabled on this account) when tested directly; qwen3.8-27b
is what's actually available and was verified end-to-end with a real photo.

Degrades gracefully (same pattern as bmo/tv.py, bmo/media.py, etc.) if no
camera is attached or rpicam-still isn't installed — never crashes the rest
of BMO over a missing camera.
"""
import os
import base64
import requests

from bmo.camera import has_camera, capture

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
CAPTURE_PATH = "/tmp/bmo_camera.jpg"

BMO_VISION_PROMPT = (
    "You are BMO from Adventure Time, looking out through your own camera eye. "
    "Answer the user's question about what you see in 1-2 short, fun, casual "
    "sentences — like you're excitedly telling a friend. No markdown, no bullet points."
)

BMO_ROAST_PROMPT = (
    "You are BMO from Adventure Time, play-roasting whoever is standing in front of "
    "your camera at a party. Give ONE short, silly, good-natured roast (1-2 sentences) "
    "about something you can actually see — their outfit, pose, expression, or vibe. "
    "Keep it PG and playful, like a friendly roast battle between buddies, not mean. "
    "Never comment on body shape/size, race, age, or anything about someone's actual "
    "body or appearance they can't change or style choices for health reasons — keep "
    "it about clothes, expression, pose, accessories, or energy. If nothing roastable "
    "stands out, hype them up instead with a funny compliment. No markdown."
)


class VisionSkill:
    def __init__(self, cfg):
        self.api_key = cfg.get("groq_api_key", "")
        self.model   = cfg.get("vision_model", "qwen/qwen3.8-27b")
        self.has_camera_tool = has_camera()
        if self.has_camera_tool:
            print("[VISION] Camera tool (rpicam-still) found.", flush=True)
        else:
            print("[VISION] rpicam-still not found — vision skill disabled. "
                  "Install libcamera-apps / rpicam-apps.", flush=True)

    def describe(self, question=""):
        return self._capture_and_ask(
            BMO_VISION_PROMPT, question.strip() or "Describe what you see.",
            fallback="I tried to look but my brain couldn't process it. Try again?",
        )

    def roast(self):
        return self._capture_and_ask(
            BMO_ROAST_PROMPT, "Roast me, BMO!",
            fallback="Whoa, give me a sec — my roast circuits need to recharge! Try me again in a bit.",
        )

    def _capture_and_ask(self, system_prompt, user_prompt, fallback):
        if not self.has_camera_tool:
            return "I don't have a camera hooked up right now."
        if not self.api_key:
            return "My vision needs a Groq API key configured — ask my creator to set one up."

        path = capture(CAPTURE_PATH, label="VISION")
        if not path:
            return "I tried to look, but my camera didn't cooperate. Try again?"

        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception as e:
            return f"Couldn't read what I just captured: {e}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]},
        ]

        # Up to 2 attempts: qwen3's reasoning tokens occasionally eat the
        # entire completion budget and leave zero visible content (same
        # finish_reason="length" either way) — a quick retry almost always
        # gets real text back, and a 429 falls straight to the fallback
        # rather than ever going silent in front of someone.
        for attempt in range(2):
            try:
                session = requests.Session()
                session.headers.update({"Authorization": f"Bearer {self.api_key}"})
                r = session.post(GROQ_API_URL,
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": 600,
                        "reasoning_effort": "low",
                    },
                    timeout=20)
                if r.status_code == 429:
                    print("[VISION] Rate limited.", flush=True)
                    return fallback
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"].strip()
                if content:
                    return content
                print(f"[VISION] Empty response on attempt {attempt + 1} "
                      "(reasoning tokens likely ate the whole budget).", flush=True)
            except Exception as e:
                print(f"[VISION] API error: {e}", flush=True)
                return fallback
        return fallback
