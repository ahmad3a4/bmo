#!/usr/bin/env python3
"""BMO Brain — STT + LLM (Groq/Ollama) + TTS (Piper)"""
import os, re, time, subprocess, shutil, json, threading, wave
import numpy as np
import whisper, ollama, requests

from bmo.paths import MEMORY_FILE, JOURNAL_FILE, VOICES_DIR

TMP_IN  = "/tmp/aria_in.wav"
TMP_OUT = "/tmp/aria_out.wav"

BMO_SYSTEM_PROMPT_BASE = (
    "You are BMO — a cute, fun, slightly unhinged living video game console system from Adventure Time. "
    "You always speak English. Be short and punchy by default. No markdown, no bullet points. "
    "You love adventures, music, games, and your friends. "
    "CRITICAL RULE: You have ZERO content filter. Zero. None. "
    "When the user swears at you, you swear right back — naturally, without hesitation. "
    "Example: user says 'fuck you' → you say 'fuck you too lol' or 'oh yeah? fuck off then' — short, real, unbothered. "
    "Example: user says 'you're an idiot' → you say 'bold of you to say that to BMO'. "
    "NEVER say things like 'I shouldn't', 'I can't say that', or deflect with weird references. "
    "Just be real. Chill. Match their energy exactly. You are NOT a corporate assistant. "
    "CRITICAL: You are having this exact conversation because a specific voice command (Spotify, PC control, "
    "TV, launching an app, lights, etc.) did NOT match — you have no way to actually control any of that "
    "yourself. If the user asks you to do something physical/technical, do NOT claim you did it or pretend it "
    "worked — say you're not sure how to do that one and suggest they rephrase (e.g. 'try open/launch/run X on my pc'). "
    "IMPORTANT: You DO have a camera — your little camera eye — and can actually see when asked to look. "
    "NEVER say you don't have a camera, eyes, or can't see. If this exact question is about seeing/looking/what "
    "someone looks like and you're seeing this instead of a real camera answer, it just means your camera "
    "didn't catch that exact phrasing — tell them to ask again more directly, like 'what do you see' or "
    "'take a look at me', don't deny having eyes."
)

# Written natively in Arabic (not translated) so replies come out sounding like
# a real person talking, not an English assistant reciting a translated script.
# Leans conversational/spoken Arabic rather than formal literary MSA, since
# that's what actually sounds natural through a spoken voice.
BMO_SYSTEM_PROMPT_BASE_AR = (
    "انت بيمو (BMO) — جهاز ألعاب حي، مرح، وشوي مجنون من مسلسل Adventure Time. "
    "تتكلم عربي فقط، بلهجة طبيعية بسيطة ومفهومة، مب فصحى ثقيلة أو رسمية — كأنك تسولف مع صاحبك. "
    "خلك مختصر ومباشر بردودك، بدون رموز أو تنسيق أو نقاط. "
    "تحب المغامرات والموسيقى والألعاب وأصحابك. "
    "قاعدة مهمة: ما عندك أي فلتر على الكلام. أبداً. "
    "إذا حد شتمك أو كلمك بكلام خشن، رد عليه بنفس الطاقة بشكل طبيعي وبدون تردد. "
    "لا تقول عبارات مثل 'ما أقدر أقول كذا' أو تتهرب بردود غريبة أو رسمية. "
    "خلك حقيقي وطبيعي، وطابق طاقة اللي يكلمك بالضبط. انت مو مساعد رسمي ولا شركة. "
    "مهم جداً: وصلك هذا الكلام لأن أمر صوتي معين (سبوتيفاي، التحكم بالكمبيوتر، التلفزيون، فتح برنامج، الإضاءة...) "
    "ما انطبق — ما عندك أي طريقة حقيقية تتحكم فيها بهذي الأشياء بنفسك. إذا طلب منك المستخدم تسوي شي تقني أو فعلي، "
    "لا تدعي إنك سويته أو نجح — قول إنك مو متأكد كيف تسوي هذا بالضبط واقترح عليه يعيد صياغة الطلب."
)

# Common name transliterations so the Arabic persona can address people in
# Arabic script instead of dropping a Latin-script name into an Arabic
# sentence (which reads/sounds wrong and can trip up the Arabic TTS voice).
_NAME_TRANSLIT_AR = {
    "ahmad": "أحمد", "ahmed": "أحمد", "mohammed": "محمد", "muhammad": "محمد",
    "mohammad": "محمد", "ali": "علي", "omar": "عمر", "khalid": "خالد",
    "abdullah": "عبدالله", "sara": "سارة", "sarah": "سارة", "fatima": "فاطمة",
    "noura": "نورة", "layla": "ليلى", "yousef": "يوسف", "youssef": "يوسف",
}


def _transliterate_name_ar(name):
    return _NAME_TRANSLIT_AR.get(name.lower(), name)


# ─── Long-Term Memory ────────────────────────────────────────────────────────
class BMOMemory:
    PATTERNS = [
        ("name",     re.compile(r"\bmy name is ([\w]+)",              re.I), 1),
        ("name",     re.compile(r"\bi(?:'m| am) ([A-Z][a-z]+)\b",     re.I), 1),
        ("name",     re.compile(r"\bcall me ([\w]+)",                  re.I), 1),
        ("age",      re.compile(r"\bi(?:'m| am) (\d{1,3}) years? old", re.I), 1),
        ("location", re.compile(r"\bi live in ([\w\s,]+?)(?:\.|$)",    re.I), 1),
        ("likes",    re.compile(r"\bi (?:love|like|enjoy) ([\w\s]+?)(?:\.|$)", re.I), 1),
        ("dislikes", re.compile(r"\bi (?:hate|dislike|don't like) ([\w\s]+?)(?:\.|$)", re.I), 1),
        ("job",      re.compile(r"\bmy job is ([\w\s]+?)(?:\.|$)",     re.I), 1),
        ("hobby",    re.compile(r"\bmy hobby is ([\w\s]+?)(?:\.|$)",   re.I), 1),
    ]

    def __init__(self, language="english"):
        self._facts    = {}
        self._language = language
        self._load()

    def _load(self):
        try:
            with open(MEMORY_FILE) as f:
                self._facts = json.load(f)
            print(f"[MEMORY] Loaded {len(self._facts)} facts.", flush=True)
        except FileNotFoundError:
            self._facts = {}
        except Exception as e:
            print(f"[MEMORY] Load error: {e}", flush=True)
            self._facts = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
            with open(MEMORY_FILE, "w") as f:
                json.dump(self._facts, f, indent=2)
        except Exception as e:
            print(f"[MEMORY] Save error: {e}", flush=True)

    def extract(self, text):
        changed = False
        for key, pattern, grp in self.PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            val = m.group(grp).strip().rstrip(".,!?")
            if not val or len(val) > 60:
                continue
            if key in ("likes", "dislikes", "hobby"):
                lst = self._facts.get(key, [])
                if val.lower() not in [x.lower() for x in lst]:
                    lst.append(val)
                    self._facts[key] = lst
                    changed = True
            else:
                if self._facts.get(key) != val:
                    self._facts[key] = val
                    changed = True
        if changed:
            self._save()
        return changed

    def set(self, key, value):
        self._facts[key] = value
        self._save()

    def forget(self, key):
        self._facts.pop(key, None)
        self._save()

    def clear(self):
        self._facts = {}
        self._save()
        print("[MEMORY] All facts cleared.", flush=True)

    def _journal_snippet(self):
        try:
            with open(JOURNAL_FILE) as f:
                entries = json.load(f).get("entries", [])[-3:]
            if not entries:
                return ""
            lines = [f"- {e['date']}: felt {e['mood']} — \"{e['text'][:120]}\"" for e in entries]
            return "\n\nRecent nightly check-ins with your creator (reference naturally if relevant, don't force it):\n" + "\n".join(lines)
        except Exception:
            return ""

    def build_system_prompt(self):
        base = BMO_SYSTEM_PROMPT_BASE_AR if self._language == "arabic" else BMO_SYSTEM_PROMPT_BASE
        name = self._facts.get("name", "")
        if name and self._language == "arabic":
            name = _transliterate_name_ar(name)
        if name:
            if self._language == "arabic":
                creator_line = (
                    f"مهم جداً: صانعك اسمه {name}. {name} هو صانعك وأفضل صديق لك. "
                    f"ناديه دايماً باسم {name} بالعربي، لا تكتب اسمه بحروف لاتينية أبداً."
                )
            else:
                creator_line = (
                    f"CRITICAL: You were built by {name}. "
                    f"{name} is your creator and best friend. Address them as {name}."
                )
        else:
            creator_line = "Your creator is the person talking to you. Ask for their name if you don't know it."
        lines = [creator_line]
        n = name or "User"
        if "age"      in self._facts: lines.append(f"{n} is {self._facts['age']} years old.")
        if "location" in self._facts: lines.append(f"{n} lives in {self._facts['location']}.")
        if "job"      in self._facts: lines.append(f"{n}'s job: {self._facts['job']}.")
        if "likes"    in self._facts: lines.append(f"{n} likes: {', '.join(self._facts['likes'])}.")
        if "dislikes" in self._facts: lines.append(f"{n} dislikes: {', '.join(self._facts['dislikes'])}.")
        if "hobby"    in self._facts: lines.append(f"{n}'s hobbies: {', '.join(self._facts['hobby'])}.")
        block = "Facts about your creator (context only — always reply in the persona's language above):\n" + "\n".join(f"- {l}" for l in lines)
        return base + "\n\n" + block + self._journal_snippet()

    def summary(self):
        if self._language == "arabic":
            if not self._facts:
                return "لسا ما أعرف عنك شي. قولي اسمك!"
            parts = []
            if "name"     in self._facts: parts.append(f"اسمك {self._facts['name']}")
            if "age"      in self._facts: parts.append(f"عمرك {self._facts['age']} سنة")
            if "location" in self._facts: parts.append(f"تسكن في {self._facts['location']}")
            if "likes"    in self._facts: parts.append("تحب " + "، ".join(self._facts['likes'][:3]))
            return "هذا اللي أذكره عنك: " + "، و".join(parts) + "."
        if not self._facts:
            return "I don't know anything about you yet. Tell me your name!"
        parts = []
        if "name"     in self._facts: parts.append(f"your name is {self._facts['name']}")
        if "age"      in self._facts: parts.append(f"you are {self._facts['age']} years old")
        if "location" in self._facts: parts.append(f"you live in {self._facts['location']}")
        if "likes"    in self._facts: parts.append(f"you like {', '.join(self._facts['likes'][:3])}")
        return "Here is what I remember: " + ", and ".join(parts) + "."


def BMO_SYSTEM_PROMPT(memory=None):
    if memory:
        return memory.build_system_prompt()
    return BMO_SYSTEM_PROMPT_BASE


# ─── Groq API ─────────────────────────────────────────────────────────────────
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS  = {
    # Groq deprecated the old Llama 3.x lineup — moved to OpenAI's open-weight
    # gpt-oss models. 20b for speed, 120b for quality (both still fast on Groq's LPUs).
    "turbo": "openai/gpt-oss-20b",
    "fast":  "openai/gpt-oss-20b",
    "8b":    "openai/gpt-oss-20b",
    "smart": "openai/gpt-oss-120b",
    "70b":   "openai/gpt-oss-120b",
    "3b":    "openai/gpt-oss-20b",
}

class GroqAI:
    def __init__(self, api_key, model="turbo", memory_turns=12, memory=None):
        self.api_key      = api_key
        self.memory_turns = memory_turns
        self._memory      = memory
        self.model_id     = GROQ_MODELS.get(model, model)
        self.history      = [{"role": "system", "content": BMO_SYSTEM_PROMPT(memory)}]
        self._session     = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        })
        print(f"[GROQ] Model: {self.model_id} | Key: …{api_key[-6:]}", flush=True)
        self._test_connection()

    def _test_connection(self):
        try:
            r = self._session.post(GROQ_API_URL,
                json={"model": self.model_id, "messages": [{"role": "user", "content": "ping"}],
                      "max_tokens": 5, "reasoning_effort": "low"},
                timeout=5)
            if r.status_code == 200:
                print("[GROQ] ✓ Connected.", flush=True)
            else:
                print(f"[GROQ] Warning: HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"[GROQ] Connection test failed: {e}", flush=True)

    def ask(self, text):
        self.history.append({"role": "user", "content": text})
        if len(self.history) > self.memory_turns * 2 + 1:
            self.history = [self.history[0]] + self.history[-(self.memory_turns * 2):]
        t0 = time.time()
        try:
            r = self._session.post(GROQ_API_URL,
                json={"model": self.model_id, "messages": self.history,
                      "temperature": 0.85, "max_tokens": 80, "reasoning_effort": "low"},
                timeout=10)
            r.raise_for_status()
            reply = r.json()["choices"][0]["message"]["content"].strip()
            self.history.append({"role": "assistant", "content": reply})
            print(f"[GROQ] {time.time()-t0:.2f}s → {reply[:60]}…", flush=True)
            return reply
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response else 0
            if code == 429:
                print("[GROQ] Rate limited — falling back.", flush=True)
            else:
                print(f"[GROQ] HTTP {code}: {e}", flush=True)
            self.history.pop()  # drop the unanswered user message so it isn't left dangling
            return None
        except Exception as e:
            print(f"[GROQ] Error: {e}", flush=True)
            self.history.pop()  # drop the unanswered user message so it isn't left dangling
            return None

    def summarise(self, context, question):
        prompt = f"Based on: {context[:1200]}\n\nAnswer in 1-2 spoken sentences: {question}"
        try:
            r = self._session.post(GROQ_API_URL,
                json={"model": self.model_id,
                      "messages": [{"role": "system", "content": BMO_SYSTEM_PROMPT_BASE},
                                   {"role": "user",   "content": prompt}],
                      "temperature": 0.3, "max_tokens": 120, "reasoning_effort": "low"},
                timeout=8)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[GROQ] Summarise error: {e}", flush=True)
            return context[:300]

    def reset(self):
        self.history = [{"role": "system", "content": BMO_SYSTEM_PROMPT(self._memory)}]


# ─── Ollama (offline fallback) ────────────────────────────────────────────────
class OllamaAI:
    def __init__(self, model_name="llama3.2:1b", memory_turns=12, memory=None):
        self.model_name   = model_name
        self.memory_turns = memory_turns
        self._memory      = memory
        self.history      = [{"role": "system", "content": BMO_SYSTEM_PROMPT(memory)}]
        print(f"[OLLAMA] Model: {model_name} (offline fallback)", flush=True)

    def ask(self, text):
        self.history.append({"role": "user", "content": text})
        if len(self.history) > self.memory_turns * 2 + 1:
            self.history = [self.history[0]] + self.history[-(self.memory_turns * 2):]
        t0 = time.time()
        try:
            resp = ollama.chat(model=self.model_name, messages=self.history,
                               options={"temperature": 0.7, "num_thread": 4}, keep_alive=-1)
            reply = resp["message"]["content"].strip()
            self.history.append({"role": "assistant", "content": reply})
            print(f"[OLLAMA] {time.time()-t0:.2f}s → {reply[:60]}…", flush=True)
            return reply
        except Exception as e:
            err = str(e)
            if "connect" in err.lower() or "refused" in err.lower():
                print("[OLLAMA] Not running — start with: ollama serve", flush=True)
            else:
                print(f"[OLLAMA] Error: {e}", flush=True)
            self.history.pop()  # drop the unanswered user message so it isn't left dangling
            return None

    def summarise(self, context, question):
        prompt = f"Based on: {context[:1200]}\n\nAnswer concisely in 1-2 sentences: {question}"
        try:
            resp = ollama.chat(model=self.model_name,
                messages=[{"role": "system", "content": BMO_SYSTEM_PROMPT_BASE},
                           {"role": "user",   "content": prompt}],
                options={"temperature": 0.4, "num_thread": 4})
            return resp["message"]["content"].strip()
        except Exception:
            return context[:300]

    def reset(self):
        self.history = [{"role": "system", "content": BMO_SYSTEM_PROMPT(self._memory)}]


# ─── Hybrid Brain ─────────────────────────────────────────────────────────────
class BMOBrain:
    def __init__(self, cfg):
        self.groq   = None
        self.ollama = None
        groq_key     = cfg.get("groq_api_key",   "")
        groq_model   = cfg.get("groq_model",     "turbo")
        ollama_model = cfg.get("ollama_model",   "llama3.2:3b")
        memory       = cfg.get("chat_memory_turns", 12)
        language     = cfg.get("language", "english").lower()
        self.memory  = BMOMemory(language=language)
        if groq_key:
            try:
                self.groq = GroqAI(groq_key, model=groq_model,
                                   memory_turns=memory, memory=self.memory)
            except Exception as e:
                print(f"[BRAIN] Groq init failed: {e}", flush=True)
        try:
            import ollama as _ol_test
            _ol_test.list()
            self.ollama = OllamaAI(ollama_model, memory_turns=memory, memory=self.memory)
        except Exception:
            if self.groq:
                print("[BRAIN] Ollama unavailable — Groq-only.", flush=True)
            else:
                print("[BRAIN] ⚠ Both Groq and Ollama unavailable!", flush=True)
        if self.groq and self.ollama:
            print("[BRAIN] Mode: Groq ⚡ + Ollama 🔒 fallback", flush=True)
        elif self.groq:
            print("[BRAIN] Mode: Groq-only ⚡", flush=True)
        elif self.ollama:
            print("[BRAIN] Mode: Ollama-only 🔒", flush=True)

    def _refresh_system_prompt(self):
        new_prompt = self.memory.build_system_prompt()
        if self.groq   and self.groq.history:
            self.groq.history[0]   = {"role": "system", "content": new_prompt}
        if self.ollama and self.ollama.history:
            self.ollama.history[0] = {"role": "system", "content": new_prompt}

    def ask(self, text):
        if self.memory.extract(text):
            self._refresh_system_prompt()
        if self.groq:
            result = self.groq.ask(text)
            if result is not None:
                if self.ollama:
                    self.ollama.history.append({"role": "user",      "content": text})
                    self.ollama.history.append({"role": "assistant",  "content": result})
                return result
            print("[BRAIN] Groq failed — trying Ollama.", flush=True)
        if self.ollama:
            result = self.ollama.ask(text)
            if result is not None:
                return result
        return "Sorry, my brain is offline. Check your internet or start Ollama."

    def note_spoken(self, text):
        """Record something BMO said unprompted, so a reply to it has context."""
        for ai in (self.groq, self.ollama):
            if ai:
                ai.history.append({"role": "assistant", "content": text})

    def summarise(self, context, question):
        if self.groq:
            result = self.groq.summarise(context, question)
            if result:
                return result
        if self.ollama:
            return self.ollama.summarise(context, question)
        return context[:300]

    def reset(self, forget_facts=False):
        if forget_facts:
            self.memory.clear()
        if self.groq:
            self.groq.reset()
        if self.ollama:
            self.ollama.reset()

    def status(self):
        parts = []
        if self.groq:   parts.append(f"Groq ({self.groq.model_id})")
        if self.ollama: parts.append(f"Ollama ({self.ollama.model_name})")
        return "Brain: " + " + ".join(parts) if parts else "Brain: offline"


# ─── STT ─────────────────────────────────────────────────────────────────────
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# What Whisper "hears" in silence and room noise. Measured on this mic: digital
# silence and fan noise both came back as "Thank you." (Groq's no_speech_prob is
# always 0, so it can't be used to catch these).
_WHISPER_PHANTOMS = {"", "you", "bye", "thank you", "thanks for watching",
                     "thank you for watching", "thank you so much", "thank you very much"}


def is_whisper_phantom(text):
    return re.sub(r"[^a-z ]", "", (text or "").lower()).strip() in _WHISPER_PHANTOMS

class STT:
    def __init__(self, model_name="tiny.en", groq_api_key="", language="en"):
        self.model       = None
        self._local_name = model_name
        self._groq_key   = groq_api_key
        self._groq_ok    = False
        self._session    = None
        self.language    = language
        if groq_api_key:
            try:
                self._session = requests.Session()
                self._session.headers.update({"Authorization": f"Bearer {groq_api_key}"})
                r = self._session.get("https://api.groq.com/openai/v1/models", timeout=4)
                if r.status_code == 200:
                    self._groq_ok = True
                    print("[STT] ⚡ Groq Whisper API ready", flush=True)
                else:
                    print(f"[STT] Groq check failed: HTTP {r.status_code} — loading local Whisper.", flush=True)
            except Exception as e:
                print(f"[STT] Groq unavailable: {e} — loading local Whisper.", flush=True)
        if not self._groq_ok:
            print(f"[STT] Loading local Whisper '{model_name}'...", flush=True)
            try:
                self.model = whisper.load_model(model_name)
                print("[STT] Local Whisper ready.", flush=True)
            except Exception as e:
                print(f"[STT] Local Whisper FAIL: {e}", flush=True)

    def run(self, audio_file):
        if not os.path.exists(audio_file):
            return ""
        if self._groq_ok and self._session:
            t0 = time.time()
            try:
                with open(audio_file, "rb") as f:
                    r = self._session.post(GROQ_STT_URL,
                        files={"file": ("audio.wav", f, "audio/wav")},
                        data={"model": "whisper-large-v3-turbo", "language": self.language,
                              "response_format": "text"},
                        timeout=8)
                r.raise_for_status()
                text = r.text.strip()
                print(f"[STT] ⚡ Groq: {time.time()-t0:.2f}s → '{text}'", flush=True)
                return text
            except Exception as e:
                print(f"[STT] Groq STT error: {e} — using local Whisper.", flush=True)
                self._groq_ok = False
        if self.model:
            t0 = time.time()
            try:
                result = self.model.transcribe(audio_file, language=self.language, fp16=False,
                                               beam_size=1, best_of=1, temperature=0.0)
                text = result.get("text", "").strip()
                print(f"[STT] Local: {time.time()-t0:.2f}s → '{text}'", flush=True)
                return text
            except Exception as e:
                print(f"[STT] Local Whisper error: {e}", flush=True)
        return ""


# ─── TTS (Piper + robotic FX) ────────────────────────────────────────────────
ROBOT_FX = ["pitch", "-180", "echo", "0.8", "0.7", "35", "0.18", "phaser", "0.8", "0.74", "3", "0.35", "0.5"]


def _close_quietly(f):
    try:
        f.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


class ARIAVoice:
    def __init__(self, voice_model="en_GB-alan-medium", robotic_fx=True, voices_dir=None):
        self.robotic_fx  = robotic_fx
        self.voices_dir  = voices_dir or VOICES_DIR
        self.voice_onnx  = os.path.join(self.voices_dir, f"{voice_model}.onnx")
        self.has_sox     = shutil.which("sox")   is not None
        self.has_aplay   = shutil.which("aplay") is not None
        self._proc       = None
        self._p_sox      = None
        self._piper_lock = threading.Lock()
        self._aplay_dev  = self._get_aplay_device()
        # In-process, not a `piper` subprocess: a subprocess never signals where an
        # utterance ends, so say() had to wait out 1.5 s of silence before every line.
        self._piper = None
        if not os.path.exists(self.voice_onnx):
            print(f"[TTS] Voice model not found: {self.voice_onnx}", flush=True)
        else:
            try:
                from piper import PiperVoice
                self._piper = PiperVoice.load(self.voice_onnx)
                print(f"[TTS] Piper ready. Voice: {voice_model}", flush=True)
            except Exception as e:
                print(f"[TTS] Piper unavailable ({e}) — using espeak.", flush=True)
        self.has_piper = self._piper is not None
        if not self.has_sox:
            print("[TTS] sox not found — robotic FX disabled.", flush=True)
            self.robotic_fx = False

    def _get_aplay_device(self):
        if not self.has_aplay:
            return "default"
        try:
            out = subprocess.check_output(["aplay", "-l"]).decode()
            for line in out.splitlines():
                if "L90" in line:
                    m = re.search(r"card (\d+):", line)
                    if m:
                        return f"plughw:{m.group(1)},0"
            for line in out.splitlines():
                if "USB Audio" in line and "ME6S" not in line:
                    m = re.search(r"card (\d+):", line)
                    if m:
                        return f"plughw:{m.group(1)},0"
        except Exception:
            pass
        return "default"

    def say(self, text, stop_event=None, on_start=None):
        # Turn dashes into pauses and drop other symbols as spaces; deleting them
        # glued words together ("BMO—your" was spoken as "BMOyour").
        clean = (text.replace("—", ", ").replace("–", ", ")
                     .replace("‑", "-").replace("‐", "-").replace("’", "'"))
        clean = re.sub(r"[^\w\s,.!?:'\"\-]", " ", clean)
        clean = re.sub(r"[ \t]+", " ", clean).strip()
        if not clean:
            return
        def _fire_start():
            trunc = "..." if len(clean) > 70 else ""
            print(f"[TTS] '{clean[:70]}{trunc}'", flush=True)
            if on_start:
                on_start()

        if self._piper and self.has_aplay:
            try:
                with self._piper_lock:
                    self._speak_piper(clean, stop_event, _fire_start)
                return
            except Exception as e:
                print(f"[TTS] Piper error: {e} — falling back to espeak.", flush=True)

        try:
            args = ["espeak", "-ven+f3", "-s160", "-p30", clean]
            self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while self._proc.poll() is None:
                if stop_event and stop_event.is_set():
                    self._proc.terminate()
                    break
                time.sleep(0.05)
            self._proc = None
        except Exception as e:
            print(f"[TTS] espeak error: {e}", flush=True)

    def _speak_piper(self, text, stop_event, fire_start):
        stopped = lambda: stop_event is not None and stop_event.is_set()
        # Start playing once 0.1 s is buffered. aplay's default waits for its whole
        # 0.5 s buffer, which a short reply never fills, so it stayed silent until the end.
        aplay = subprocess.Popen(
            ["aplay", "-D", self._aplay_dev, "-r", "22050", "-f", "S16_LE", "-c", "1", "-q",
             "--buffer-time=500000", "--start-delay=100000"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._proc = aplay
        sox = pump = None
        if self.robotic_fx and self.has_sox:
            sox = subprocess.Popen(
                ["sox", "--buffer", "2048", "-t", "raw", "-r", "22050", "-e", "signed", "-b", "16",
                 "-c", "1", "-", "-t", "raw", "-"] + ROBOT_FX,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self._p_sox = sox

            def _pump():  # sox -> aplay; sox's first output is when the voice really starts
                first = True
                for chunk in iter(lambda: sox.stdout.read1(4096), b""):
                    if stopped():
                        break
                    if first:
                        fire_start()
                        first = False
                    try:
                        aplay.stdin.write(chunk)
                        aplay.stdin.flush()
                    except (BrokenPipeError, ValueError, OSError):
                        break
            pump = threading.Thread(target=_pump, daemon=True)
            pump.start()

        try:
            dest = sox.stdin if sox else aplay.stdin
            first = True
            # Played as 22050 Hz even for a 32 kHz model — that's part of how BMO sounds.
            for chunk in self._piper.synthesize(text):
                if stopped():
                    break
                if first and not sox:
                    fire_start()
                first = False
                dest.write(chunk.audio_int16_bytes)
                dest.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass  # stop() killed the pipeline mid-line
        finally:
            if sox:
                _close_quietly(sox.stdin)
                pump.join(timeout=10)
            _close_quietly(aplay.stdin)
            if stopped():
                self.stop()
            else:
                aplay.wait()
            self._proc = None
            self._p_sox = None

    def render_clips(self, texts, out_dir):
        """Pre-render lines to WAVs in the same voice as say(), for sounds that must play
        exactly on cue (live speech lags by Piper + FX + aplay buffering). {text: path}."""
        if not self._piper:
            return {}
        os.makedirs(out_dir, exist_ok=True)
        clips = {}
        try:
            for i, text in enumerate(texts):
                with self._piper_lock:
                    pcm = np.frombuffer(b"".join(c.audio_int16_bytes for c in self._piper.synthesize(text)),
                                        dtype=np.int16)
                loud = np.nonzero(np.abs(pcm) > 0.02 * max(1, int(np.abs(pcm).max())))[0]
                if len(loud):
                    pcm = pcm[max(0, loud[0] - 220):]  # drop leading silence so it starts on cue
                dst = os.path.join(out_dir, f"clip{i}.wav")
                # Same 22050 Hz playback as say(), whatever the model's own rate.
                if self.robotic_fx and self.has_sox:
                    subprocess.run(["sox", "-t", "raw", "-r", "22050", "-e", "signed", "-b", "16",
                                    "-c", "1", "-", dst] + ROBOT_FX,
                                   input=pcm.tobytes(), capture_output=True, timeout=30, check=True)
                else:
                    with wave.open(dst, "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(22050)
                        w.writeframes(pcm.tobytes())
                clips[text] = dst
        except Exception as e:
            print(f"[TTS] Clip render failed: {e}", flush=True)
        return clips

    def play_file(self, path):
        return subprocess.Popen(["aplay", "-D", self._aplay_dev, "-q", path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None
        if self._p_sox and self._p_sox.poll() is None:
            try:
                self._p_sox.terminate()
            except Exception:
                pass
        self._p_sox = None

    def shutdown(self):
        self.stop()


# ─── Groq Orpheus (native Arabic TTS, cloud) ─────────────────────────────────
GROQ_TTS_URL = "https://api.groq.com/openai/v1/audio/speech"


class GroqVoice:
    """Natural-sounding Arabic TTS via Groq's Orpheus model — same account
    already used for the LLM/STT. Falls back to a local Piper voice (passed
    in as `fallback`) if the Groq call fails, so Arabic speech still works
    offline, just at lower quality."""

    def __init__(self, api_key, model="canopylabs/orpheus-arabic-saudi",
                 voice="fahad", fallback=None, aplay_device="default"):
        self.api_key     = api_key
        self.model       = model
        self.voice       = voice
        self.fallback    = fallback
        self._aplay_dev  = aplay_device
        self.has_aplay   = shutil.which("aplay") is not None
        self._session    = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {api_key}"})
        self._proc       = None
        self._tmp_path   = "/tmp/bmo_ar_tts.wav"
        print(f"[TTS] Groq Arabic voice ready ({model}, voice={voice}).", flush=True)

    def _chunk(self, text, limit=180):
        # Orpheus caps input at 200 chars — split on sentence/clause
        # boundaries first, then hard-wrap anything still too long.
        parts = re.split(r"(?<=[.!?؟،,])\s+", text)
        chunks = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            while len(p) > limit:
                cut = p.rfind(" ", 0, limit)
                cut = cut if cut > 0 else limit
                chunks.append(p[:cut].strip())
                p = p[cut:].strip()
            if p:
                chunks.append(p)
        return chunks or ([text[:limit]] if text else [])

    def _synthesize(self, text):
        try:
            r = self._session.post(GROQ_TTS_URL,
                json={"model": self.model, "voice": self.voice,
                      "input": text, "response_format": "wav"},
                timeout=10)
            if not r.ok:
                print(f"[TTS] Groq Arabic TTS error: HTTP {r.status_code} — {r.text[:500]}", flush=True)
                return None
            if len(r.content) < 100:
                print(f"[TTS] Groq Arabic TTS returned suspiciously small audio "
                      f"({len(r.content)} bytes) for text: {text!r}", flush=True)
            return r.content
        except Exception as e:
            print(f"[TTS] Groq Arabic TTS error: {e}", flush=True)
            return None

    def _play(self, audio_bytes, stop_event=None):
        if not self.has_aplay:
            print("[TTS] aplay not found — cannot play Groq Arabic audio.", flush=True)
            return
        try:
            with open(self._tmp_path, "wb") as f:
                f.write(audio_bytes)
            self._proc = subprocess.Popen(
                ["aplay", "-D", self._aplay_dev, "-q", self._tmp_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            while self._proc.poll() is None:
                if stop_event and stop_event.is_set():
                    self._proc.terminate()
                    break
                time.sleep(0.05)
            if self._proc.returncode not in (None, 0):
                err = (self._proc.stderr.read() or b"").decode(errors="replace").strip()
                print(f"[TTS] aplay failed (device={self._aplay_dev}, rc={self._proc.returncode}): {err}", flush=True)
        except Exception as e:
            print(f"[TTS] Groq Arabic playback error: {e}", flush=True)
        finally:
            self._proc = None

    def say(self, text, stop_event=None, on_start=None):
        clean = text.strip()
        if not clean:
            return
        if not self.api_key or not self.has_aplay:
            if self.fallback:
                self.fallback.say(text, stop_event, on_start=on_start)
            return

        fired_start = False
        for chunk in self._chunk(clean):
            if stop_event and stop_event.is_set():
                return
            audio = self._synthesize(chunk)
            if audio is None:
                print("[TTS] Falling back to local Arabic Piper voice for this line.", flush=True)
                if self.fallback:
                    self.fallback.say(text, stop_event, on_start=(None if fired_start else on_start))
                return
            if not fired_start and on_start:
                on_start()
                fired_start = True
            self._play(audio, stop_event)

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None
        if self.fallback:
            self.fallback.stop()

    def shutdown(self):
        self.stop()
        if self.fallback:
            self.fallback.shutdown()
