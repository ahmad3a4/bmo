import os, subprocess, math, ast, operator
import requests
from duckduckgo_search import DDGS

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# ─── Weather ──────────────────────────────────────────────────────────────────
def get_weather(location):
    try:
        url = f"https://wttr.in/{location.replace(' ', '+')}?format=j1"
        d   = requests.get(url, timeout=6).json()
        c   = d["current_condition"][0]
        return (
            f"Weather in {location}: "
            f"{c['weatherDesc'][0]['value']}, "
            f"{c['temp_C']} degrees Celsius, "
            f"feels like {c['FeelsLikeC']}. "
            f"Humidity {c['humidity']} percent. "
            f"Wind {c['windspeedKmph']} kilometres per hour."
        )
    except Exception as e:
        return f"Could not retrieve weather for {location}."


# ─── Web Search ──────────────────────────────────────────────────────────────
def web_search(query, max_results=3):
    """DuckDuckGo search — returns concatenated snippets for LLM to summarise."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="wt-wt",
                                     safesearch="off", max_results=max_results))
        if not results:
            return "No results found."
        parts = []
        for r in results:
            title = r.get("title", "")
            body  = r.get("body", "")[:300]
            parts.append(f"{title}: {body}")
        return " | ".join(parts)
    except Exception as e:
        return f"Web search unavailable: {e}"


# ─── News ────────────────────────────────────────────────────────────────────
def get_news(count=5):
    if not HAS_FEEDPARSER:
        return web_search("latest world news today")
    try:
        feed = feedparser.parse("http://feeds.bbci.co.uk/news/rss.xml")
        headlines = [entry.title for entry in feed.entries[:count]]
        if not headlines:
            return "No news available right now."
        return "Latest BBC headlines: " + ". ".join(headlines) + "."
    except Exception as e:
        return f"Could not fetch news: {e}"


# ─── Volume ──────────────────────────────────────────────────────────────────
def set_system_volume(level):
    level = max(0, min(100, int(level)))
    import shutil
    try:
        if shutil.which("pactl"):
            result = subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                capture_output=True
            )
            if result.returncode == 0:
                return f"System volume set to {level} percent."

        if shutil.which("wpctl"):
            result = subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"],
                capture_output=True
            )
            if result.returncode == 0:
                return f"System volume set to {level} percent."

        if shutil.which("amixer"):
            controls = ["Master", "PCM", "Speaker", "Headphone", "Playback", "Digital", "Front"]
            success = False
            for card in range(3):
                for control in controls:
                    res = subprocess.run(["amixer", "-c", str(card), "sset", control, f"{level}%"], capture_output=True)
                    if res.returncode == 0:
                        success = True
            if success:
                return f"System volume set to {level} percent."
            else:
                return "Could not change volume: No valid ALSA controls found on any sound card."
    except Exception as e:
        return f"Could not change volume: {e}"


# ─── Jokes & Facts ────────────────────────────────────────────────────────────
def get_joke():
    try:
        r = requests.get(
            "https://v2.jokeapi.dev/joke/Programming,Misc,Pun?type=twopart",
            timeout=5
        ).json()
        if r.get("type") == "twopart":
            return f"{r['setup']} ... {r['delivery']}"
        return r.get("joke", "No joke available.")
    except:
        return "Could not fetch a joke right now."


def get_fact():
    try:
        r = requests.get(
            "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en",
            timeout=5
        ).json()
        return r.get("text", "No fact available.")
    except:
        return "Could not fetch a fact right now."


# ─── Bored Activity ───────────────────────────────────────────────────────────
_BORED_FALLBACK = [
    "Try drawing something — even stick figures count!",
    "Learn 5 words in a new language right now.",
    "Write a haiku about your day.",
    "Do 20 jumping jacks. Go!",
    "Message someone you haven't talked to in a while.",
    "Make a list of 10 things that make you happy.",
    "Reorganise one drawer or shelf in your room.",
    "Watch a YouTube video about something you know nothing about.",
    "Try to solve a Rubik's cube — or learn the first step.",
    "Cook or bake something you've never made before.",
    "Go outside and find something interesting you've never noticed.",
    "Start a journal entry — even one sentence is fine.",
    "Look up the etymology of your name.",
    "Try to memorise the periodic table of the first 10 elements.",
    "Listen to a song from a genre you usually skip.",
    "Sketch a map of your neighbourhood from memory.",
    "Read the first chapter of a book you own but haven't opened.",
    "Try meditating for just 5 minutes.",
    "Write a short story where BMO is the hero.",
    "Learn a magic trick from YouTube.",
]

def get_bored_activity():
    """Returns a random activity suggestion. Tries Bored API, falls back to local list."""
    import random
    try:
        r = requests.get(
            "https://bored-api.appbrewery.com/random",
            timeout=5
        ).json()
        activity = r.get("activity", "")
        if activity:
            atype = r.get("type", "").replace("_", " ")
            participants = r.get("participants", 1)
            who = "solo" if participants == 1 else f"{participants} people"
            return (f"Here's something to do: {activity}. "
                    f"It's a {atype} activity, best for {who}.")
    except Exception:
        pass
    # Local fallback
    return random.choice(_BORED_FALLBACK)


# ─── Calculator ──────────────────────────────────────────────────────────────
_CALC_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_CALC_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CALC_FUNCS = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
_CALC_FUNCS.update({"abs": abs, "round": round, "int": int, "float": float})
_CALC_NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _calc_eval(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("invalid literal")
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_BINOPS:
        return _CALC_BINOPS[type(node.op)](_calc_eval(node.left), _calc_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_UNARYOPS:
        return _CALC_UNARYOPS[type(node.op)](_calc_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CALC_NAMES:
        return _CALC_NAMES[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _CALC_FUNCS:
        args = [_calc_eval(a) for a in node.args]
        return _CALC_FUNCS[node.func.id](*args)
    raise ValueError("expression not allowed")


def calculate(expression):
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _calc_eval(tree.body)
        return f"The result is {result}."
    except Exception as e:
        return f"Could not calculate: {e}"


# ─── System Status ────────────────────────────────────────────────────────────
def get_system_status():
    parts = []
    # CPU temperature (Pi-specific)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp = int(f.read().strip()) / 1000
        parts.append(f"CPU temperature {temp:.1f} degrees Celsius")
    except:
        pass
    # RAM
    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        parts.append(
            f"RAM usage {mem.percent:.0f} percent "
            f"({mem.used // (1024**2)} of {mem.total // (1024**2)} megabytes)"
        )
        cpu = psutil.cpu_percent(interval=0.5)
        parts.append(f"CPU load {cpu:.0f} percent")
    if parts:
        return "System status: " + ", ".join(parts) + "."
    return "System status unavailable."
