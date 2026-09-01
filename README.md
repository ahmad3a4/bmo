# 🟩 BMO — Adventure Time AI Companion

> **A real-time, voice-interactive AI assistant with true personality, sub-second latency, and a face that shows its feelings.**  
> *Inspired by BMO from Adventure Time. Running on a Raspberry Pi 5.*

---

## ✨ What Makes This Different

Most voice assistants feel robotic. BMO doesn't.

| Feature | What Sets It Apart |
|---|---|
| ⚡ **Sub-second latency** | Groq cloud LLM (~300ms) + Groq Whisper STT (~300ms) — feels instant |
| 🎭 **Real-time lip-sync** | Procedural Tkinter face with 15+ emotion states, synced to speech |
| 🧠 **Long-term memory** | Dual-layer (session history + Ollama) — survives reboots |
| 🎤 **Hands-free** | OpenWakeWord always-on detection, no button needed |
| 🏠 **Smart integrations** | Spotify · Smart TV (ADB) · Home Assistant · Instagram auto-posting |
| 🔒 **Offline fallback** | Groq down? Ollama kicks in locally. No single point of failure |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        ARIA / BMO                           │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │ Wake Word│───▶│   STT    │───▶│  Intent  │              │
│  │ (OWW)    │    │ (Groq ⚡)│    │  Router  │              │
│  └──────────┘    └──────────┘    └─────┬────┘              │
│                                        │                   │
│                          ┌─────────────┴──────────────┐   │
│                          │                            │   │
│                     Fast Skills               LLM Query    │
│                     (regex match)         ┌────────────┐  │
│                          │                │ Groq ⚡     │  │
│                   ┌──────┴──────┐         │ llama-3.1  │  │
│                   │  Spotify    │         │            │  │
│                   │  TV (ADB)   │         │  fallback  │  │
│                   │  Weather    │         │ Ollama 🔒  │  │
│                   │  Web Search │         └────────────┘  │
│                   │  Instagram  │                │        │
│                   │  Home Asst. │         ┌──────▼─────┐  │
│                   └─────────────┘         │   TTS      │  │
│                          │                │ Piper+Sox  │  │
│                          └────────────────┤ Robotic FX │  │
│                                           └──────┬─────┘  │
│                                                  │        │
│                                           ┌──────▼─────┐  │
│                                           │  BMO Face  │  │
│                                           │ 15 emotions│  │
│                                           │ lip-synced │  │
│                                           └────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## ⚡ Performance (Groq Mode)

| Stage | Latency |
|---|---|
| Wake word detection | Real-time (16kHz stream) |
| Silence detection | 30ms chunks, 1.5s threshold |
| Groq Whisper STT | **~0.3s** |
| Groq LLM (llama-3.1-8b-instant) | **~0.3–0.5s** |
| Piper TTS generation | **~0.1s** |
| **Total round-trip** | **~0.8–1.2s** ⚡ |

*Offline fallback (Ollama 3b on Pi 5): ~2–3s total.*

---

## 🎭 Face System

BMO's face is **100% procedurally drawn** in Python (Tkinter canvas). No PNG sprites.  
Expressions are triggered automatically from LLM reply content:

| Keyword in reply | Emotion shown |
|---|---|
| "playing", "spotify", "music" | 🎵 Music notes floating |
| "love", "beautiful", "sweet" | ❤️ Heart eyes + pink blush |
| "amazing", "incredible" | ⭐ Star eyes + bouncing ! |
| "haha", "funny", "lol" | 😄 Open laugh mouth |
| "sorry", "unable", "can't" | 😢 Frown + animated tear |
| "hmm", "unclear" | 😕 Squint + wavy mouth + ? |
| "tv", "channel" | 📺 Square screen eyes |
| LLM thinking | 💭 Animated thinking dots |
| Wake word heard | 👀 Wide alert eyes |
| Error state | ✖️ X eyes |

---

## 🧠 AI Pipeline

### Primary: Groq Cloud ⚡
- **LLM**: `llama-3.1-8b-instant` — ~300ms, 80-token replies
- **STT**: `whisper-large-v3-turbo` — ~300ms transcription
- **Personality**: BMO system prompt — short, warm, Adventure Time energy

### Fallback: Ollama 🔒 (Fully Offline)
- Model: `llama3.2:1b` (local, runs on Pi 5)  
- Auto-activates on Groq rate-limit or network loss
- Conversation history is **mirrored** between backends — no context loss on switch

### Memory Architecture
```
Session Memory (in-RAM)         Long-term (Ollama context)
────────────────────            ──────────────────────────
Last 15 conversation turns  +   Persistent across reboots
Trimmed automatically           User-specific facts retained
Shared Groq ↔ Ollama            "forget everything" to reset
```

---

## 🏠 Skill Integrations

### 🎵 Spotify
```
"play Daft Punk on Spotify"        → search + play
"pause" / "resume"                 → playback control
"next song" / "previous song"      → skip tracks
"set Spotify volume to 60"         → volume
"what's playing"                   → now playing info
```

### 📺 Smart TV (Android TV via ADB)
```
"turn on the TV"                   → Wake-on-LAN + ADB power
"TV volume up" / "TV volume down"  → ADB keyevent
"open Netflix on the TV"           → launch app by name
"set TV volume to 40"              → precise volume
"connect to TV"                    → re-establish ADB session
"TV status"                        → connectivity report
```

### 📸 Instagram Auto-Posting
```
"post a photo to Instagram"        → upload feed post (scheduler)
"create an Instagram story"        → upload story
```
*Session-based auth with cookie persistence. Challenge-handler built in.*

### 🌐 Web / Utility Skills
```
"weather in Riyadh"                → wttr.in live weather
"search for quantum computing"     → DuckDuckGo + AI summary
"latest news"                      → BBC RSS headlines
"set a timer for 10 minutes"       → background countdown
"set an alarm for 7:30"            → persistent daily alarm
"remind me to drink water in 30 minutes"
"tell me a joke"                   → JokeAPI
"random fact"                      → Useless Facts API
"what is sqrt(144) plus 5"         → safe math eval
"system status"                    → Pi CPU temp, RAM, load
"brain status"                     → which AI backend is active
```

### 💡 Home Assistant
```
"turn on the living room lights"   → light.living_room on
"turn off bedroom lights"          → light off
"toggle the fan"                   → switch.fan toggle
"what is the temperature sensor"   → entity state query
```

---

## 📂 File Structure

```
aria/
├── aria.py              Main agent — wake word, recording, state machine
├── aria_brain.py        STT (Groq/Whisper) · LLM (Groq/Ollama) · TTS (Piper)
├── aria_skills.py       All skill handlers + intent router (regex fast-path)
├── aria_alarms.py       Persistent alarm & reminder manager
├── bmo_faces.py         Procedural face system — 15 emotions, lip-sync
├── bmo_hud.py           Spotify HUD overlay (canvas)
├── bmo_media.py         Meme & image display system
├── bmo_tv.py            Android TV ADB controller
├── bmo_instagram.py     Instagram scheduler + session auth
├── spotify_setup.py     One-time Spotify OAuth flow
├── config.json          All settings
├── requirements.txt     Python dependencies
├── setup.sh             Full Pi setup automation
├── voices/              Piper TTS voice models (.onnx)
├── wakeword/            Wake word models (.onnx)
├── sounds/              Sound effect WAVs (wake, done, error)
└── data/                Persistent alarms/reminders (JSON)
```

---

## 🚀 Quick Start (Raspberry Pi 5)

```bash
# 1. Clone / copy to Pi
scp -r aria/ pi@raspberrypi.local:~/aria/

# 2. SSH in and run setup
ssh pi@raspberrypi.local
cd ~/aria && bash setup.sh

# 3. Add your API keys
nano config.json

# 4. One-time Spotify auth (optional)
source venv/bin/activate
python spotify_setup.py

# 5. Launch BMO
python aria.py              # with GUI (fullscreen face)
python aria.py --headless   # no screen (Pi headless server)
python aria.py --test       # self-test all components
```

---

## ⚙️ Configuration (`config.json`)

```json
{
  "assistant_name":        "BMO",
  "wake_word_model":       "alexa",
  "voice_model":           "en_GB-alan-medium",
  "groq_api_key":          "gsk_...",
  "groq_model":            "turbo",
  "ollama_model":          "llama3.2:1b",
  "whisper_model":         "tiny.en",
  "robotic_fx":            true,
  "sound_effects":         true,
  "led_enabled":           false,
  "silence_threshold":     0.006,
  "silence_duration":      1.5,
  "wake_threshold":        0.5,
  "chat_memory_turns":     15,
  "spotify_client_id":     "...",
  "spotify_client_secret": "...",
  "home_assistant_url":    "http://homeassistant.local:8123",
  "home_assistant_token":  "..."
}
```

### Groq Model Aliases
| Alias | Model | Speed |
|---|---|---|
| `turbo` / `fast` | `llama-3.1-8b-instant` | ⚡ ~300ms |
| `smart` / `70b` | `llama-3.3-70b-versatile` | ~800ms |
| `3b` | `llama-3.2-3b-preview` | ⚡⚡ ultra-fast |

---

## 🎤 Custom Wake Word

Default: `alexa` (OpenWakeWord pre-trained).  
For a custom **"Hey BMO"** wake word:

1. Visit [console.picovoice.ai](https://console.picovoice.ai) → free account
2. **Wake Word** → type "Hey BMO" → download `.ppn` for Raspberry Pi (ARM)
3. Place in `wakeword/bmo.ppn`
4. Set `"wake_word_model": "bmo"` in `config.json`

---

## 🔌 GPIO LED Wiring (Optional)

```
GPIO 17 → 220Ω → Green LED  → GND    (IDLE)
GPIO 27 → 220Ω → Blue LED   → GND    (LISTENING)
GPIO 22 → 220Ω → Yellow LED → GND    (THINKING)
GPIO 23 → 220Ω → White LED  → GND    (SPEAKING)
```

Enable in config: `"led_enabled": true`

---

## 🎙️ Voice Pipeline Details

```
Piper TTS → raw PCM → sox robotic FX → aplay
                        │
                        ├── pitch -180 (deeper voice)
                        ├── echo 0.8 0.7 35 0.18 (slight reverb)
                        └── phaser 0.8 0.74 3 0.35 0.5
```

First audio chunk fires `on_start()` callback → face switches to SPEAK state → lip-sync animation begins.  
Sox pipeline runs in parallel — no added latency.

---

## 🛡️ Fault Tolerance

| Failure | Recovery |
|---|---|
| Groq rate limit | Auto-fallback to Ollama |
| Groq down | Auto-fallback to Ollama |
| Ollama not running | "Brain offline" message |
| Piper not found | espeak fallback |
| OpenWakeWord missing | PTT mode (press Enter) |
| GPIO unavailable | LEDs silently disabled |
| Instagram blocked | Session re-auth + cookie patch |
| ADB connection lost | Reconnect on next TV command |
| Any skill error | Graceful error message, no crash |

---

*Built with ❤️ on a Raspberry Pi 5 (8GB). Adventure Time forever. 🌈*
