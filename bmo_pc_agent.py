import os
import re
import json
import time
import ctypes
import secrets
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _mask(s):
    return f"{s[:4]}...{s[-4:]} ({len(s)} chars)" if len(s) > 8 else f"({len(s)} chars)"


# Shared secret: set BMO_PC_TOKEN in the environment to match the "pc_agent_token"
# value in the BMO Pi's config.json. Without a matching token, requests are refused.
TOKEN = os.environ.get("BMO_PC_TOKEN", "")
if not TOKEN:
    print("[WARN] BMO_PC_TOKEN is not set in this process's environment — this agent "
          "will refuse ALL commands with 401 until it is. Set it to the same value as "
          "'pc_agent_token' in config.json on the BMO Pi, then RESTART this agent "
          "(existing running processes won't pick up a newly-set env var).")
else:
    print(f"[INFO] BMO_PC_TOKEN loaded: {_mask(TOKEN)}")

# ── App launcher registry ────────────────────────────────────────────────────
# Voice/network requests only ever supply a KEY into this dict — never a raw
# command — so this stays a fixed allowlist, not arbitrary command execution.
# Each entry is {"launch": <command to run>, "process": <real process name,
# for playtime tracking>}. Old-style plain-string entries (from before
# "process" existed) are still supported for backwards compatibility.
APPS_FILE = os.path.join(BASE_DIR, "pc_agent_apps.json")
HELPER_PS1 = os.path.join(BASE_DIR, "pc_agent_helpers.ps1")

DEFAULT_APPS = {
    "valorant": {
        "launch": r'"C:\Riot Games\Riot Client\RiotClientServices.exe" --launch-product=valorant --launch-patchline=live',
        "process": "VALORANT-Win64-Shipping",
    },
    "vscode":             {"launch": "code", "process": "Code"},
    "vs code":            {"launch": "code", "process": "Code"},
    "visual studio code": {"launch": "code", "process": "Code"},
    "video studio code":  {"launch": "code", "process": "Code"},  # common STT mishearing of "visual"
    "obs":                {"launch": "obs64.exe", "process": "obs64"},
    "discord":            {"launch": r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe", "process": "Discord"},
    "steam":              {"launch": "steam", "process": "steam"},
    "chrome":             {"launch": "chrome", "process": "chrome"},
}


def _load_apps():
    if not os.path.exists(APPS_FILE):
        with open(APPS_FILE, "w") as f:
            json.dump(DEFAULT_APPS, f, indent=2)
        print(f"[APPS] Created {APPS_FILE} with default entries — edit it to add "
              "your own apps, fix install paths, or add 'process' names for playtime tracking.")
        return dict(DEFAULT_APPS)
    try:
        with open(APPS_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"[APPS] Failed to read {APPS_FILE} ({e}) — using built-in defaults.")
        return dict(DEFAULT_APPS)


APPS = _load_apps()


def _entry_launch(entry):
    return entry.get("launch", "") if isinstance(entry, dict) else (entry or "")


def _entry_process(entry, fallback_key):
    if isinstance(entry, dict) and entry.get("process"):
        return entry["process"]
    return fallback_key


# Matches bare domains ("github.com") or full URLs, rejects anything with
# spaces or shell-unsafe characters — used to decide "open X" means a
# website rather than a registered app, without ever shelling out raw input.
_URL_RE = re.compile(
    r'^(?:https?://)?[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
    r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+(?:/[\w\-./?%&=#]*)?$'
)


def _as_url(text):
    t = (text or "").strip()
    if not t or " " in t or not _URL_RE.match(t):
        return None
    return t if t.lower().startswith(("http://", "https://")) else "https://" + t


def _run_ps_helper(action, value=""):
    """Runs pc_agent_helpers.ps1. `value` is always passed as a real argv
    element (never interpolated into a shell string), safe regardless of
    where it ultimately came from."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", HELPER_PS1,
             "-Action", action, "-Value", str(value)],
            capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return None, (r.stderr or "").strip() or "helper script failed"
        return (r.stdout or "").strip(), None
    except Exception as e:
        return None, str(e)


def launch_app(app_name: str):
    key = (app_name or "").strip().lower()
    entry = APPS.get(key)
    if entry:
        target = _entry_launch(entry)
        if target:
            try:
                subprocess.Popen(target, shell=True)
                return True, f"Launching {app_name}."
            except Exception as e:
                return False, f"Failed to launch {app_name}: {e}"

    # Not a known app — maybe it's a website ("open github.com on my pc").
    url = _as_url(app_name)
    if url:
        try:
            os.startfile(url)
            return True, f"Opening {url}."
        except Exception as e:
            return False, f"Failed to open {url}: {e}"

    known = ", ".join(sorted(APPS)) or "(none configured)"
    return False, f"Don't know how to open '{app_name}'. Known apps: {known}"


def close_app(app_name: str):
    key = (app_name or "").strip().lower()
    entry = APPS.get(key)
    proc_name = _entry_process(entry, key) if entry else key
    try:
        r = subprocess.run(["taskkill", "/IM", f"{proc_name}.exe", "/F"],
                            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return True, f"Closed {app_name}."
        return False, f"{app_name} doesn't look like it's running."
    except Exception as e:
        return False, f"Couldn't close {app_name}: {e}"


def set_volume(level_raw):
    try:
        level = max(0, min(100, int(level_raw)))
    except (TypeError, ValueError):
        return False, "That's not a valid volume level."
    out, err = _run_ps_helper("SetVolume", level)
    if err:
        return False, f"Couldn't set volume: {err}"
    return True, out or f"Volume set to {level} percent."


def take_screenshot():
    shots_dir = os.path.join(BASE_DIR, "screenshots")
    os.makedirs(shots_dir, exist_ok=True)
    fname = f"screenshot_{int(time.time())}.png"
    fpath = os.path.join(shots_dir, fname)
    out, err = _run_ps_helper("Screenshot", fpath)
    if err:
        return False, f"Screenshot failed: {err}"
    return True, f"Screenshot saved as {fname}."


def get_top_processes(n=5):
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {n} -ExpandProperty ProcessName"],
            capture_output=True, text=True, timeout=10)
        names = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
        if not names:
            return False, "Couldn't read the process list."
        return True, "Top processes: " + ", ".join(names) + "."
    except Exception as e:
        return False, f"Couldn't read the process list: {e}"


def read_clipboard():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                            capture_output=True, text=True, timeout=10)
        text = (r.stdout or "").strip()
        if not text:
            return True, "Your clipboard is empty."
        return True, text[:300]
    except Exception as e:
        return False, f"Couldn't read the clipboard: {e}"


def get_playtime(app_name: str):
    key = (app_name or "").strip().lower()
    entry = APPS.get(key)
    if not entry:
        return False, f"I don't have '{app_name}' registered, so I can't track its playtime."
    proc_name = _entry_process(entry, key)
    try:
        ps_cmd = (
            f"$p = Get-Process -Name '{proc_name}' -ErrorAction SilentlyContinue | Select-Object -First 1; "
            "if ($p) { [int]((Get-Date) - $p.StartTime).TotalMinutes } else { '' }"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                            capture_output=True, text=True, timeout=10)
        out = (r.stdout or "").strip()
        if not out:
            return True, f"{app_name} doesn't look like it's running right now."
        minutes = int(out)
        if minutes < 60:
            return True, f"You've been in {app_name} for {minutes} minutes."
        hours, mins = divmod(minutes, 60)
        return True, f"You've been in {app_name} for {hours} hour{'s' if hours != 1 else ''} and {mins} minutes."
    except Exception as e:
        return False, f"Couldn't check {app_name}'s playtime: {e}"


def get_gpu_temp():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8)
        lines = (r.stdout or "").strip().splitlines()
        if r.returncode == 0 and lines:
            return True, f"GPU temperature: {lines[0].strip()} degrees Celsius."
        return False, "Couldn't read GPU temperature."
    except FileNotFoundError:
        return False, "nvidia-smi not found — GPU temperature needs an NVIDIA GPU with drivers installed."
    except Exception as e:
        return False, f"Couldn't read GPU temperature: {e}"


class BMOAgentHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

        received  = self.headers.get('X-BMO-Token', '')
        authorized = bool(TOKEN) and secrets.compare_digest(received, TOKEN)
        if not authorized:
            if not TOKEN:
                print("[AUTH] Rejected — BMO_PC_TOKEN is not set in THIS process's environment. "
                      "Set it and restart the agent.")
            else:
                print(f"[AUTH] Rejected — token mismatch. Expected {_mask(TOKEN)}, "
                      f"got {_mask(received) if received else '(no X-BMO-Token header received)'}.")
            self.send_response(401)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": "unauthorized"}).encode('utf-8'))
            return

        try:
            data = json.loads(post_data.decode('utf-8'))
            command = data.get('command', '')
            print(f"Received command: {command}")

            response = {"status": "success", "message": f"Executed {command}"}

            if command == "lock":
                ctypes.windll.user32.LockWorkStation()
            elif command == "sleep":
                os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            elif command == "shutdown":
                os.system("shutdown /s /t 1")
            elif command == "restart":
                os.system("shutdown /r /t 1")
                response = {"status": "success", "message": "Restarting the PC."}
            elif command == "mute":
                # Mute via powershell sending media key (Volume Mute = 173)
                subprocess.run(["powershell", "-c", "(new-object -com wscript.shell).SendKeys([char]173)"])
            elif command == "vol_up":
                # Volume Up = 175
                subprocess.run(["powershell", "-c", "(new-object -com wscript.shell).SendKeys([char]175)"])
            elif command == "vol_down":
                # Volume Down = 174
                subprocess.run(["powershell", "-c", "(new-object -com wscript.shell).SendKeys([char]174)"])
            elif command == "set_volume":
                ok, msg = set_volume(data.get("level", ""))
                response = {"status": "success" if ok else "error", "message": msg}
            elif command == "youtube":
                os.system("start https://youtube.com")
            elif command == "spotify":
                os.system("start spotify:")
            elif command == "launch_app":
                ok, msg = launch_app(data.get("app", ""))
                response = {"status": "success" if ok else "error", "message": msg}
            elif command == "close_app":
                ok, msg = close_app(data.get("app", ""))
                response = {"status": "success" if ok else "error", "message": msg}
            elif command == "top_processes":
                ok, msg = get_top_processes()
                response = {"status": "success" if ok else "error", "message": msg}
            elif command == "screenshot":
                ok, msg = take_screenshot()
                response = {"status": "success" if ok else "error", "message": msg}
            elif command == "read_clipboard":
                ok, msg = read_clipboard()
                response = {"status": "success" if ok else "error", "message": msg}
            elif command == "playtime":
                ok, msg = get_playtime(data.get("app", ""))
                response = {"status": "success" if ok else "error", "message": msg}
            elif command == "gpu_temp":
                ok, msg = get_gpu_temp()
                response = {"status": "success" if ok else "error", "message": msg}
            else:
                response = {"status": "error", "message": "Unknown command"}

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))

        except Exception as e:
            print(f"Error: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

def run():
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, BMOAgentHandler)
    print(f"BMO PC Agent listening on port {PORT}...")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    print("BMO PC Agent stopped.")

if __name__ == '__main__':
    run()
