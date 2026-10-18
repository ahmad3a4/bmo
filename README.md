# BMO — a living voice companion for the Raspberry Pi 5

BMO is a voice assistant modelled on BMO from *Adventure Time*. It runs on a Raspberry Pi 5 with a screen, a microphone, a speaker and a camera. You talk to it with "hey bmo", it answers in BMO's robot voice, and its face reacts on screen.

Unlike a normal assistant it doesn't only wait for commands. BMO has moods that change through the day, greets people it recognises, follows up on things you told it, entertains itself when it's alone, and writes its own diary every night.

---

## What BMO can do

**Conversation**
- Hands-free wake word ("hey bmo"), then just talk
- Answers with BMO's personality, using Groq's `gpt-oss` models, with a local Ollama model as an offline fallback
- Remembers facts about you, recalls past conversations ("what did I say about my trip?"), and keeps a nightly mood journal

**It's alive**
- **Moods:** gets lonely when nobody talks to it, bored when nothing fun happens, sleepy at night, happy with company. The mood shows on its face and colours its replies.
- **Greets people by name** when the camera sees them come back after a while
- **Follows up** on things you mention: say you have an exam tomorrow, and the next day it asks how it went
- **Gets your attention** when it's bored and someone is nearby, and backs off if ignored
- **Talks to itself** when alone: plays detective, sings, chats with Football (its reflection)
- **Writes a diary** every night from what happened that day

**Sight (Pi camera)**
- Describes what it sees, reads text out loud, and play-roasts your outfit
- Recognises faces after you teach it ("remember my face as Ahmad")
- **Selfies:** live preview on screen, a spoken 5-second countdown, then the photo is saved

**Who's talking**
- Recognises voices after enrolment, and only obeys its owner for risky commands (PC control, self-coding, Instagram posting, powering off)

**Control things**
- **Windows PC:** wake, lock, sleep, shut down, open/close apps, volume, screenshots, clipboard, GPU temperature, game playtime (through a small agent on the PC)
- **Android TV** over ADB, **Spotify**, **Home Assistant** lights
- **Instagram:** scheduled posts and stories, comment replies, follower stats
- **RetroArch** games, lo-fi ambient mode, memes and images on screen

**Everyday helpers**
- Weather, news, web search, timers, notes, jokes, facts, maths, system status

**Teaches itself**
- "Learn a new skill that ..." makes BMO write and install a new Python skill for itself (owner's voice only)

---

## Voice commands

Start every command with **"hey bmo"**. These are examples; most have several phrasings.

| Area | Say |
|---|---|
| Chat | anything: "how are you?", "tell me a story" |
| BMO's day | "how was your day?", "read me your diary" |
| Quiet | "quiet mode" / "leave me alone" (3 hours), "you can talk again" |
| Camera | "what do you see?", "read this", "roast me", "rate my outfit", "selfie" |
| Faces | "remember my face as Ahmad", "forget Ahmad's face", "whose faces do you know?" |
| Voices | "remember my voice as Ahmad", "forget Ahmad's voice", "who's talking?" |
| Memory | "what do you remember about me?", "what did I say about ...", "forget everything" |
| Journal | "read my journal", "how have I been feeling?" |
| PC | "turn on my pc", "open Valorant on my pc", "close Chrome on my pc", "lock my computer", "take a screenshot", "read my clipboard", "gpu temp" |
| TV | "turn on the tv", "tv volume up", "open Netflix on the tv", "search cat videos on youtube" |
| Spotify | "play Daft Punk on spotify", "pause", "next song", "what is playing" |
| Home | "turn on the living room light", "turn off the bedroom light" |
| Instagram | "post on instagram", "post a story", "check instagram comments", "instagram followers" |
| Fun | "let's play games", "chill" (lo-fi mode), "show me a meme", "tell me a joke", "I'm bored" |
| Helpers | "weather in Riyadh", "latest news", "search for ...", "set a 10 minute timer", "note that ...", "list my alarms" |
| Self-coding | "learn a new skill that tells the time in Tokyo" |
| System | "system status", "brain status" |

Saying "stop", "cancel" or "be quiet" interrupts BMO. Saying "hey bmo" while it's talking also cuts in.

---

## How it works

```
 "hey bmo"  ─▶  wake word (OpenWakeWord, custom "hey bmo" model)
                    │
                    ▼
 record until you stop talking  (webrtcvad on a 200 Hz high-passed signal)
                    │
                    ├─▶ speech-to-text   (Groq whisper-large-v3-turbo; local Whisper fallback)
                    ├─▶ voice ID         (Resemblyzer)           } in parallel with STT,
                    └─▶ face ID          (OpenCV Haar + LBPH)    } no added latency
                    │
                    ▼
 built-in commands (memory, journal, voice/face ID, quiet mode, diary)
                    │
                    ▼
 intent registry (ordered regex fast path) ──▶ skill  (PC, TV, Spotify, camera, ...)
                    │ no match
                    ▼
 LLM: Groq gpt-oss-120b / 20b  ──fallback──▶  Ollama llama3.2:3b
                    │
                    ▼
 speech: Piper (in-process, custom "bmo" voice) ─▶ sox robot FX ─▶ aplay
         + lip-synced, code-drawn face on screen
```

Running alongside, the **inner life** loop (`bmo/life.py`) ticks every 20 seconds. It updates BMO's needs, glances through the camera (locally, nothing is sent anywhere), and decides whether to greet someone, follow something up, try to get attention or talk to itself. Everything it does is rate-limited and silent during quiet hours.

**Measured on the Pi 5:**
- Speech-to-text and LLM replies take about 0.3–0.6 s each.
- Short replies start playing about 0.5 s after the text is ready.
- Recording ends about 0.75 s after you stop talking when BMO can clearly hear you. If it can't tell, it listens for a fixed 3.5 s.

---

## Project layout

```
aria.py                  Entry point (run this from the project root)
bmo/
  agent.py               Main loop: wake word, recording, state machine, GUI
  brain.py               Speech-to-text, LLM (Groq / Ollama), text-to-speech, memory
  life.py                Inner life: moods, acting on its own, diary
  vad.py                 Speech endpointing (has the person started / stopped talking?)
  camera.py              Shared Pi camera access (one user at a time)
  face_id.py             Face recognition
  voiceprint.py          Voice recognition
  journal.py             Nightly check-in and mood journal
  semantic_memory.py     "What did I say about ..." recall (Ollama embeddings)
  faces.py               Code-drawn animated face, emotions, lip sync
  media.py               Images, memes and the live camera preview on screen
  alarms.py  ambient.py  games.py  tv.py  hud.py  self_coder.py
  app.py                 Local web API (port 8080)
  config.py  paths.py    Config defaults and every file path
  skills/
    registry.py          Ordered intent patterns (voice phrase -> action)
    router.py            Action dispatch
    vision.py  selfie.py  pc_control.py  spotify.py  home_assistant.py  notes.py  misc.py
  instagram/             Scheduler and web automation
  tools/                 One-off setup scripts (Spotify auth, Instagram session import)
bmo_pc_agent.py          Runs on your Windows PC so BMO can control it
install_pc_agent_task.ps1  Installs the PC agent to start at Windows login
dynamic_skills/          Skills BMO wrote for itself
wakeword/  sounds/  assets/  web/
voices/                  Piper voice models (not in git, see setup)
data/                    Everything personal (not in git, see privacy)
```

---

## Setup

### Hardware
- Raspberry Pi 5 (8 GB recommended)
- USB microphone and USB speaker
- Raspberry Pi camera (tested with the OV5647)
- A screen for the face (optional; `--headless` works without one)

### Install

```bash
git clone https://github.com/ahmad3a4/bmo.git ~/aria
cd ~/aria
bash setup.sh                      # system packages, venv, Piper, Ollama, default voice
source venv/bin/activate
pip install -r requirements.txt
pip install openwakeword --no-deps # see the note in requirements.txt
```

Then copy in the files that aren't in git:
- **Voice:** put `bmo.onnx` and `bmo.onnx.json` in `voices/`. `setup.sh` only downloads the stock `en_GB-alan-medium` voice.
- **Config:** `cp config.example.json config.json` and fill in your keys. At minimum you need `groq_api_key` (free at console.groq.com).

### Run

```bash
python aria.py              # with the face on screen
python aria.py --headless   # no screen
python aria.py --test       # self-test the components
```

Run `aria.py` from the project root, not as `python -m bmo`, so BMO's self-written skills in `dynamic_skills/` can be imported.

### Optional pieces
- **Spotify:** fill in the Spotify keys, then run `python bmo/tools/spotify_setup.py` once.
- **Windows PC control:** copy `bmo_pc_agent.py` and `install_pc_agent_task.ps1` to the PC, then run `.\install_pc_agent_task.ps1 -Token "<pc_agent_token from config.json>"`. Set `pc_ip` and `pc_mac` in `config.json`.
- **TV:** enable ADB debugging on the TV and set `adb_tv_ip`.
- **Face and voice ID:** after starting BMO, say "remember my face as <name>" and "remember my voice as <name>". Set `voice_id_owner` to your name to lock risky commands to your voice.

---

## Configuration

`config.json` only needs the values you want to change. Everything else falls back to the defaults in `bmo/config.py`.

| Key | Default | What it does |
|---|---|---|
| `groq_api_key` | — | Needed for speech-to-text, the LLM and vision |
| `groq_model` | `turbo` | `turbo`/`fast` = gpt-oss-20b, `smart` = gpt-oss-120b |
| `ollama_model` | `llama3.2:3b` | Offline fallback brain |
| `wake_word_model` | `alexa` | Use `hey bmo` for the custom model in `wakeword/` |
| `wake_threshold` | `0.5` | Lower = wakes more easily (and on more noise) |
| `wake_threshold_during_tts` | `0.6` | Stricter threshold while BMO is talking, so its own voice can't wake it |
| `silence_duration` | `1.5` | Seconds of quiet before BMO decides you've finished |
| `no_speech_timeout` | `3.5` | How long BMO listens when it can't clearly hear you |
| `voice_model` / `robotic_fx` | `en_GB-alan-medium` / `true` | Piper voice and the robot effect |
| `vision_model` | `qwen/qwen3.8-27b` | Groq vision model for the camera |
| `face_id_enabled` / `face_id_threshold` | `true` / `70` | Face recognition (lower threshold = stricter) |
| `voice_id_enabled` / `voice_id_threshold` / `voice_id_owner` | `true` / `0.65` / — | Voice recognition and owner lock |
| `life_enabled` | `true` | Turns the whole inner life on or off |
| `life_quiet_start` / `life_quiet_end` | `23:00` / `08:00` | BMO never talks on its own in this window |
| `life_away_minutes` | `60` | How long someone must be gone before BMO greets them |
| `life_idle_minutes` | `45` | How long without attention before BMO gets bored |
| `life_min_gap_minutes` | `20` | Minimum time between things BMO says on its own |
| `life_glance_seconds` | `90` | How often BMO glances through the camera while awake |
| `life_talk_to_self` | `true` | Allow BMO to play pretend when alone |
| `checkin_enabled` / `checkin_time` | `true` / `21:30` | Nightly "how was your day?" check-in |
| `language` | `english` | `arabic` is experimental |

---

## Privacy

Everything personal stays in `data/`, which is excluded from git:

| File / folder | What it holds |
|---|---|
| `memory.json`, `semantic_memory.json` | Facts and past conversation snippets |
| `journal.json` | Nightly check-in answers |
| `voiceprints.json`, `known_faces/` | Voice and face enrolments |
| `selfies/` | Selfies |
| `life_state.json`, `bmo_diary.json` | BMO's mood, the day's events, and its diary |

What leaves the Pi: recorded speech (Groq speech-to-text), conversation text (Groq LLM), and camera photos only when you ask BMO to look ("what do you see", "roast me"). Camera glances for greeting people and face recognition run locally, and each glance overwrites the previous one in `/tmp`.

---

## Troubleshooting

**BMO doesn't hear me, or only sometimes.** BMO's own logs show how loud your voice reaches the mic. A fan or other rumble near the mic makes the USB mic's auto-gain turn itself down, and then your voice ends up barely above the noise. Move the mic closer to where you talk and away from fans. A better USB mic helps more than any setting.

**BMO wakes up on its own.** `wake_threshold` is too low. False wakes are harmless, because BMO quietly gives up if nobody speaks. But a very low threshold also lets a TV or video wake it.

**BMO doesn't greet me.** Face greetings need a face enrolment ("remember my face as <name>"). BMO also stays quiet during quiet hours, in quiet mode, and while music, games or anything on screen is active.

**Web API.** `bmo/app.py` serves a small control page and API on port 8080. `/api/command` and `/api/speak` need the `X-BMO-Token` header (the `api_token` in `config.json`, generated on first start).
