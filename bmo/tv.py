#!/usr/bin/env python3
"""
BMO TV & Smart Device Control
===============================
Controls TVs and smart devices on the same local network using multiple methods:

  1. HDMI-CEC  — direct TV control via Raspberry Pi HDMI port (cec-utils)
  2. Samsung SmartThings — Samsung TVs and SmartThings-connected devices
  3. LG WebOS  — LG smart TVs via websocket (aiowebostv)
  4. Roku      — Roku TVs / streaming sticks via REST API
  5. Generic HTTP — any device exposing a local HTTP API

All methods are auto-detected and enabled based on config.json entries.

Config keys (all optional):
    "tv_type":                "cec" | "samsung" | "lg" | "roku" | "http"
    "smartthings_token":      "<token>"
    "smartthings_device_id":  "<device-id>"
    "roku_ip":                "192.168.x.x"
    "lg_tv_ip":               "192.168.x.x"
    "lg_tv_mac":              "AA:BB:CC:DD:EE:FF"  (for wake-on-LAN)
    "samsung_tv_ip":          "192.168.x.x"
    "samsung_tv_mac":         "AA:BB:CC:DD:EE:FF"
    "http_device_base_url":   "http://192.168.x.x"
"""

import os, json, time, subprocess, socket, struct, threading, re, shlex
import requests

# ─── Optional deps ────────────────────────────────────────────────────────────
try:
    import samsungtvws
    HAS_SAMSUNG = True
except ImportError:
    HAS_SAMSUNG = False

try:
    from wakeonlan import send_magic_packet
    HAS_WOL = True
except ImportError:
    HAS_WOL = False


# ─── Wake On LAN (fallback implementation) ────────────────────────────────────
def _send_wol(mac: str, broadcast="255.255.255.255", port=9):
    """Send a Wake-on-LAN magic packet."""
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    payload   = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(payload, (broadcast, port))


def wake_on_lan(mac: str) -> str:
    """Wake a device by MAC address."""
    if not mac:
        return "No MAC address configured for wake-on-LAN."
    try:
        if HAS_WOL:
            send_magic_packet(mac)
        else:
            _send_wol(mac)
        return "Wake-on-LAN packet sent."
    except Exception as e:
        return f"Wake-on-LAN error: {e}"


# ─── HDMI-CEC (Raspberry Pi built-in) ────────────────────────────────────────
class CECController:
    """
    Control TVs / AV receivers via HDMI-CEC using the 'cec-client' CLI tool.
    Only works when BMO is connected via HDMI to the target device.
    """

    def __init__(self):
        self.available = bool(subprocess.run(
            ["which", "cec-client"], capture_output=True
        ).returncode == 0)
        if self.available:
            print("[CEC] cec-client found — HDMI-CEC available.", flush=True)
        else:
            print("[CEC] cec-client not found. Install: sudo apt install cec-utils", flush=True)

    def _send(self, cmd: str) -> bool:
        """Send a raw CEC command."""
        try:
            proc = subprocess.run(
                ["cec-client", "-s", "-d", "1"],
                input=cmd, capture_output=True, text=True, timeout=5
            )
            return proc.returncode == 0
        except Exception as e:
            print(f"[CEC] Error: {e}", flush=True)
            return False

    def tv_on(self) -> str:
        if not self.available:
            return "HDMI-CEC not available. Install cec-utils."
        self._send("on 0")
        return "TV turned on via HDMI-CEC."

    def tv_off(self) -> str:
        if not self.available:
            return "HDMI-CEC not available."
        self._send("standby 0")
        return "TV standby via HDMI-CEC."

    def tv_mute(self) -> str:
        if not self.available:
            return "HDMI-CEC not available."
        self._send("volmute")
        return "TV muted."

    def tv_volume_up(self) -> str:
        if not self.available:
            return "HDMI-CEC not available."
        self._send("volup")
        return "TV volume up."

    def tv_volume_down(self) -> str:
        if not self.available:
            return "HDMI-CEC not available."
        self._send("voldown")
        return "TV volume down."

    def set_input(self, hdmi_num: int) -> str:
        """Switch TV to HDMI input 1–4."""
        if not self.available:
            return "HDMI-CEC not available."
        # CEC logical address: HDMI1=1, HDMI2=2, etc.
        self._send(f"tx 1F:82:{hdmi_num:02X}:00")
        return f"TV switched to HDMI {hdmi_num}."


# ─── Roku ─────────────────────────────────────────────────────────────────────
class RokuController:
    """
    Control Roku TVs / streaming sticks via the Roku External Control Protocol (ECP).
    REST-based, no auth needed on the local network.
    """
    KEYS = {
        "home": "Home", "back": "Back", "select": "Select",
        "up": "Up", "down": "Down", "left": "Left", "right": "Right",
        "play": "Play", "pause": "Play", "mute": "VolumeMute",
        "volume_up": "VolumeUp", "volume_down": "VolumeDown",
        "power": "Power", "forward": "Fwd", "rewind": "Rev",
        "netflix": "Netflix", "prime": "AmazonVideo",
        "info": "Info", "search": "Search",
    }

    def __init__(self, ip: str):
        self.base = f"http://{ip}:8060" if ip else None
        if self.base:
            print(f"[ROKU] Controller ready at {self.base}", flush=True)

    def _post(self, path: str) -> bool:
        if not self.base:
            return False
        try:
            r = requests.post(f"{self.base}/{path}", timeout=4)
            return r.status_code == 200
        except Exception as e:
            print(f"[ROKU] Error: {e}", flush=True)
            return False

    def press(self, key: str) -> str:
        if not self.base:
            return "Roku IP not configured."
        mapped = self.KEYS.get(key.lower().replace(" ", "_"), key)
        ok = self._post(f"keypress/{mapped}")
        return f"Roku: {key}." if ok else f"Roku command failed: {key}"

    def power_on(self) -> str:
        return self.press("power")

    def power_off(self) -> str:
        return self.press("power")

    def launch_app(self, app_name: str) -> str:
        """Launch an app by scanning the installed app list."""
        if not self.base:
            return "Roku IP not configured."
        try:
            r = requests.get(f"{self.base}/query/apps", timeout=4)
            # Parse simple XML
            name_lower = app_name.lower()
            for line in r.text.splitlines():
                m = re.search(r'id="(\d+)".*?>(.*?)</app>', line, re.IGNORECASE)
                if m and name_lower in m.group(2).lower():
                    self._post(f"launch/{m.group(1)}")
                    return f"Launching {m.group(2)} on Roku."
            return f"App '{app_name}' not found on Roku."
        except Exception as e:
            return f"Roku error: {e}"

    def set_volume(self, level: int) -> str:
        """Roku doesn't support absolute volume, so we do incremental."""
        return "Roku volume control is press-based. Say 'volume up' or 'volume down'."

    def get_apps(self) -> str:
        if not self.base:
            return "Roku IP not configured."
        try:
            r = requests.get(f"{self.base}/query/apps", timeout=4)
            apps = re.findall(r'>(.*?)</app>', r.text)
            return "Roku apps: " + ", ".join(apps[:10]) + "."
        except Exception as e:
            return f"Roku error: {e}"


# ─── Samsung TV (SmartThings API) ────────────────────────────────────────────
class SamsungSmartThingsController:
    """
    Control Samsung TVs (and other SmartThings devices) via the cloud API.
    Requires a SmartThings Personal Access Token.
    """
    BASE = "https://api.smartthings.com/v1"

    def __init__(self, token: str, device_id: str):
        self.token     = token
        self.device_id = device_id
        self.enabled   = bool(token and device_id)
        if self.enabled:
            print("[SMARTTHINGS] Samsung SmartThings ready.", flush=True)

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"}

    def _command(self, component, capability, command, args=None) -> str:
        if not self.enabled:
            return "SmartThings not configured. Add token + device_id to config.json."
        payload = {
            "commands": [{
                "component": component,
                "capability": capability,
                "command":    command,
            }]
        }
        if args is not None:
            payload["commands"][0]["arguments"] = args
        try:
            url = f"{self.BASE}/devices/{self.device_id}/commands"
            r   = requests.post(url, headers=self._headers(),
                                json=payload, timeout=8)
            return "OK" if r.status_code in (200, 202) else f"Error {r.status_code}"
        except Exception as e:
            return f"SmartThings error: {e}"

    def tv_on(self) -> str:
        res = self._command("main", "switch", "on")
        return "TV turned on via SmartThings." if res == "OK" else res

    def tv_off(self) -> str:
        res = self._command("main", "switch", "off")
        return "TV turned off via SmartThings." if res == "OK" else res

    def set_volume(self, level: int) -> str:
        level = max(0, min(100, level))
        res = self._command("main", "audioVolume", "setVolume", [level])
        return f"TV volume set to {level}." if res == "OK" else res

    def mute(self) -> str:
        res = self._command("main", "audioMute", "mute")
        return "TV muted." if res == "OK" else res

    def unmute(self) -> str:
        res = self._command("main", "audioMute", "unmute")
        return "TV unmuted." if res == "OK" else res

    def set_channel(self, channel: int) -> str:
        res = self._command("main", "tvChannel", "setTvChannel",
                             [str(channel)])
        return f"TV channel set to {channel}." if res == "OK" else res

    def set_input(self, source: str) -> str:
        res = self._command("main", "mediaInputSource", "setInputSource",
                             [source.upper()])
        return f"TV input set to {source}." if res == "OK" else res

    def get_status(self) -> str:
        if not self.enabled:
            return "SmartThings not configured."
        try:
            url = f"{self.BASE}/devices/{self.device_id}/status"
            r   = requests.get(url, headers=self._headers(), timeout=6).json()
            comps = r.get("components", {}).get("main", {})
            sw    = comps.get("switch", {}).get("switch", {}).get("value", "?")
            vol   = comps.get("audioVolume", {}).get("volume", {}).get("value", "?")
            return f"TV is {sw}, volume {vol}."
        except Exception as e:
            return f"SmartThings error: {e}"


# ─── Generic HTTP device ──────────────────────────────────────────────────────
class GenericHTTPDevice:
    """
    Control any device with a simple HTTP REST API.
    Configure endpoint patterns in config.json under "http_device_endpoints".
    """

    def __init__(self, base_url: str, endpoints: dict = None):
        self.base = base_url.rstrip("/") if base_url else None
        self.endpoints = endpoints or {
            "on":      "/on",
            "off":     "/off",
            "toggle":  "/toggle",
            "status":  "/status",
        }
        if self.base:
            print(f"[HTTP DEVICE] Generic device at {self.base}", flush=True)

    def call(self, action: str) -> str:
        if not self.base:
            return "HTTP device base URL not configured."
        path = self.endpoints.get(action.lower(), f"/{action}")
        try:
            r = requests.get(f"{self.base}{path}", timeout=5)
            return f"Device response: {r.text[:100]}"
        except Exception as e:
            return f"HTTP device error: {e}"


# ─── ADB (Android TV / Fire TV / Nvidia Shield) ──────────────────────────────
class ADBController:
    """
    Control any Android TV device over the network via ADB (Android Debug Bridge).

    Setup (one-time on the TV):
      Settings → Device Preferences → Developer Options → Network debugging: ON

    Config keys:
        "adb_tv_ip":   "192.168.x.x"   (required)
        "adb_tv_port": 5555             (optional, default 5555)

    Requires 'adb' to be installed:
        sudo apt install adb
    """

    # Android TV keycodes
    KEYS = {
        "home":        3,
        "back":        4,
        "menu":        82,
        "play":        126,
        "pause":       127,
        "play_pause":  85,
        "stop":        86,
        "next":        87,
        "previous":    88,
        "rewind":      89,
        "fast_forward":90,
        "volume_up":   24,
        "volume_down": 25,
        "mute":        164,
        "power":       26,
        "up":          19,
        "down":        20,
        "left":        21,
        "right":       22,
        "select":      23,   # DPAD_CENTER
        "enter":       66,
    }

    # Common app packages
    APPS = {
        "netflix":        "com.netflix.ninja",
        "youtube":        "com.google.android.youtube.tv",
        "spotify":        "com.spotify.tv.android",
        "prime":          "com.amazon.amazonvideo.livingroom",
        "amazon prime":   "com.amazon.amazonvideo.livingroom",
        "disney":         "com.disney.disneyplus",
        "disney plus":    "com.disney.disneyplus",
        "hbo":            "com.hbo.hbonow",
        "hbo max":        "com.hbo.hbonow",
        "plex":           "com.plexapp.android",
        "twitch":         "tv.twitch.android.app",
        "kodi":           "org.xbmc.kodi",
        "vlc":            "org.videolan.vlc",
        "settings":       "com.android.tv.settings",
    }

    def __init__(self, ip: str, port: int = 5555):
        self.ip        = ip
        self.port      = port
        self.target    = f"{ip}:{port}"
        self.available = False
        self.connected = False
        self._lock     = threading.Lock()

        if not ip:
            print("[ADB] No TV IP configured. Add 'adb_tv_ip' to config.json.", flush=True)
            return

        try:
            r = subprocess.run(["adb", "version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                self.available = True
                print(f"[ADB] adb found. Target: {self.target}", flush=True)
            else:
                print("[ADB] 'adb' command failed. Install: sudo apt install adb", flush=True)
                return
        except FileNotFoundError:
            print("[ADB] 'adb' not found. Install: sudo apt install adb", flush=True)
            return
        except Exception as e:
            print(f"[ADB] Init error: {e}", flush=True)
            return

        # Connect in background — never block BMO startup
        threading.Thread(target=self._connect, daemon=True).start()

    def _is_reachable(self, timeout: float = 2.0) -> bool:
        """TCP ping — check if the TV's ADB port is open before adb connect."""
        try:
            with socket.create_connection((self.ip, self.port), timeout=timeout):
                return True
        except Exception:
            return False

    def _connect(self) -> bool:
        """Connect (or reconnect) to the TV over ADB. Thread-safe."""
        if not self.available:
            return False
        with self._lock:
            try:
                print(f"[ADB] Connecting to {self.target}...", flush=True)
                r = subprocess.run(
                    ["adb", "connect", self.target],
                    capture_output=True, text=True, timeout=10
                )
                out = (r.stdout + r.stderr).strip()
                if "connected" in out.lower():
                    if not self.connected:
                        print(f"[ADB] ✓ Connected to {self.target}", flush=True)
                    self.connected = True
                    return True
                print(f"[ADB] Connect response: {out}", flush=True)
                self.connected = False
                return False
            except subprocess.TimeoutExpired:
                print(f"[ADB] Connect timed out for {self.target}. TV may be off.", flush=True)
                self.connected = False
                return False
            except Exception as e:
                print(f"[ADB] Connect error: {e}", flush=True)
                self.connected = False
                return False

    def _ensure_connected(self) -> bool:
        if self.connected:
            return True
        return self._connect()

    def _shell(self, cmd: str, timeout: int = 8) -> str | None:
        """Run an adb shell command. Returns None on failure, '' on empty success."""
        if not self.available:
            return None
        if not self._ensure_connected():
            return None
        try:
            r = subprocess.run(
                ["adb", "-s", self.target, "shell", cmd],
                capture_output=True, text=True, timeout=timeout
            )
            if r.returncode != 0 and "error" in (r.stderr or "").lower():
                self.connected = False
                return None
            return r.stdout.strip()
        except subprocess.TimeoutExpired:
            self.connected = False
            return None
        except Exception as e:
            self.connected = False
            print(f"[ADB] Shell error: {e}", flush=True)
            return None

    def _keyevent(self, code) -> bool:
        """Send an Android key event. Returns False if not connected."""
        if isinstance(code, str):
            code = self.KEYS.get(code.lower(), code)
        result = self._shell(f"input keyevent {code}")
        return result is not None   # None = failed, "" = success (keyevent returns empty)

    def _not_available(self, action: str = "") -> str | None:
        """Return an error string if ADB can't execute commands, else None."""
        if not self.available:
            return "ADB not installed. Run: sudo apt install adb"
        if not self._ensure_connected():
            if action == "off":
                return "TV is unreachable — it may already be off."
            if action == "on":
                return "TV is unreachable — it may be in deep sleep. Try the physical remote first."
            return (f"Cannot reach TV at {self.target}. "
                    "Check: Settings → System → Developer Options → Network debugging: ON")
        return None

    def pair(self, pair_port: int, pair_code: str) -> str:
        """
        Pair with Android 11+ TV using the wireless debugging pairing flow.
        On TV: Settings → System → Developer Options → Wireless Debugging → Pair device with code
        Then call: bmo.tv.adb.pair(pair_port, '123456')
        """
        try:
            r = subprocess.run(
                ["adb", "pair", f"{self.ip}:{pair_port}", pair_code],
                capture_output=True, text=True, timeout=15
            )
            out = r.stdout.strip() or r.stderr.strip()
            if "successfully" in out.lower() or "paired" in out.lower():
                print(f"[ADB] ✓ Paired with TV.", flush=True)
                self._connect()
                return "TV paired successfully! ADB is now connected."
            return f"Pairing response: {out}"
        except Exception as e:
            return f"Pairing error: {e}"

    def turn_on(self) -> str:
        err = self._not_available("on")
        if err: return err
        state = self._shell("dumpsys power | grep 'Display Power'") or ""
        if "OFF" in state.upper() or not state:
            self._keyevent("power")
        return "TV turned on."

    def turn_off(self) -> str:
        err = self._not_available("off")
        if err: return err
        self._keyevent("power")
        return "TV turned off."

    def volume_up(self, steps: int = 3) -> str:
        err = self._not_available()
        if err: return err
        for _ in range(steps):
            self._keyevent("volume_up")
        return "Volume up."

    def volume_down(self, steps: int = 3) -> str:
        err = self._not_available()
        if err: return err
        for _ in range(steps):
            self._keyevent("volume_down")
        return "Volume down."

    def mute(self) -> str:
        err = self._not_available()
        if err: return err
        self._keyevent("mute")
        return "TV muted."

    def set_volume(self, level: int) -> str:
        """Set absolute volume. Queries max range for accuracy."""
        err = self._not_available()
        if err: return err
        level = max(0, min(100, level))
        
        # 1. Try to detect max volume range (default is often 15)
        max_vol = 15
        info = self._shell("media volume --stream 3 --get") or ""
        # Example output: "volume is 5 in range 0..15"
        m = re.search(r"range 0..(\d+)", info)
        if m:
            max_vol = int(m.group(1))
            print(f"[ADB] Detected max volume: {max_vol}", flush=True)

        steps = round(level * max_vol / 100)
        
        # Try 'media' command first
        res = self._shell(f"media volume --stream 3 --set {steps}")
        
        # Fallback: cmd audio (newer Android)
        if res is None:
            self._shell(f"cmd audio volume --stream 3 --set {steps}")
        
        return f"TV volume set to {level} percent."

    def go_home(self) -> str:
        err = self._not_available()
        if err: return err
        self._keyevent("home")
        return "TV home screen."

    def go_back(self) -> str:
        err = self._not_available()
        if err: return err
        self._keyevent("back")
        return "TV back."

    def set_channel(self, channel: int) -> str:
        err = self._not_available()
        if err: return err
        for digit in str(channel):
            self._shell(f"input keyevent {7 + int(digit)}")
        time.sleep(0.3)
        self._keyevent("enter")
        return f"TV channel {channel}."

    def launch_app(self, app_name: str) -> str:
        err = self._not_available()
        if err: return err
        
        key = app_name.lower().strip()
        pkg = self.APPS.get(key)
        
        if not pkg:
            # Try to find in the installed packages dynamically
            print(f"[ADB] Searching for app: {key}", flush=True)
            pkgs_raw = self._shell("pm list packages") or ""
            pkgs = [p.replace("package:", "").strip() for p in pkgs_raw.splitlines()]
            
            # Look for matches
            matches = [p for p in pkgs if key in p.lower()]
            if matches:
                # Prioritize shorter package names or common patterns
                matches.sort(key=len)
                pkg = matches[0]
                print(f"[ADB] Found dynamic match: {pkg}", flush=True)
        
        if not pkg:
            # Final fallback: fuzzy match on the hardcoded list
            for k, v in self.APPS.items():
                if k in key or key in k:
                    pkg = v
                    break
        
        if not pkg:
            return f"App '{app_name}' not found. You can try saying 'open package [package name]' if you know it."

        result = self._shell(f"monkey -p {shlex.quote(pkg)} -c android.intent.category.LAUNCHER 1", timeout=10)
        if result is None:
            return f"Failed to launch {app_name}."
        return f"Launching {app_name} on TV."

    def search(self, query: str) -> str:
        """Open YouTube search or generic search and type the query."""
        err = self._not_available()
        if err: return err
        
        # 1. Try to open YouTube search directly if it's a common search request
        # intent: android.intent.action.SEARCH
        # YouTube TV search intent: "vnd.youtube.tv://search"
        print(f"[ADB] Searching for '{query}' on TV...", flush=True)
        
        # Generic approach: Open search bar (Keycode 84) or YouTube Search
        # Best way for TV: Launch YouTube and send search query
        uri = f"vnd.youtube.tv://search?q={query.replace(' ', '+')}"
        self._shell(f"am start -a android.intent.action.VIEW -d {shlex.quote(uri)}")
        
        # Fallback if YouTube isn't the target or doesn't work:
        # self._keyevent(84) # Search key
        # time.sleep(1)
        # self.send_text(query)
        # self._keyevent(66) # Enter
        
        return f"Searching for '{query}' on TV."

    def send_key(self, key_name: str) -> str:
        err = self._not_available()
        if err: return err
        
        code = self.KEYS.get(key_name.lower())
        if code:
            self._keyevent(code)
            return f"Pressed {key_name} on TV."
        
        # Fallback: try to type it as text
        return self.send_text(key_name)

    def get_status(self) -> str:
        if not self.available:
            return "ADB not installed."
        if not self._ensure_connected():
            return f"TV at {self.target} is not reachable (off or sleeping)."
        state       = self._shell("dumpsys power | grep 'Display Power'") or ""
        current_app = self._shell(
            "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'"
        ) or ""
        status   = "on" if "ON" in state.upper() else "standby"
        app_line = current_app.split("\n")[0].strip() if current_app else ""
        return f"TV is {status}. {app_line or 'No app info.'}"

    def send_text(self, text: str) -> str:
        """Type text on the TV (useful for search boxes)."""
        err = self._not_available()
        if err: return err
        escaped = text.replace(" ", "%s")
        self._shell(f"input text {shlex.quote(escaped)}")
        return f"Typed '{text}' on TV."

    def reconnect(self) -> str:
        self.connected = False
        if self._connect():
            return f"Reconnected to TV at {self.target}."
        return f"Could not reach TV at {self.target}. Make sure Network debugging is enabled."


# ─── TV Skill (unified entry point) ──────────────────────────────────────────
class TVSkill:
    """
    Unified smart TV / device controller.  Picks the right backend
    based on config.json 'tv_type' setting.

    Set "tv_type": "adb" and "adb_tv_ip": "192.168.x.x" for Android TV.
    """

    def __init__(self, cfg: dict):
        self.cfg  = cfg
        self.mode = cfg.get("tv_type", "cec").lower()

        # Always init CEC (it's free on Pi)
        self.cec  = CECController()

        # Roku
        self.roku = RokuController(cfg.get("roku_ip", ""))

        # Samsung SmartThings
        self.samsung = SamsungSmartThingsController(
            token=cfg.get("smartthings_token", ""),
            device_id=cfg.get("smartthings_device_id", ""),
        )

        # Generic HTTP
        self.http_dev = GenericHTTPDevice(
            base_url=cfg.get("http_device_base_url", ""),
            endpoints=cfg.get("http_device_endpoints", {}),
        )

        # ADB (Android TV)
        self.adb = ADBController(
            ip=cfg.get("adb_tv_ip", ""),
            port=int(cfg.get("adb_tv_port", 5555)),
        )

        print(f"[TV] Primary mode: {self.mode}", flush=True)

    # ─── Public commands ──────────────────────────────────────────────────

    def turn_on(self, device="tv") -> str:
        if self.mode == "adb":    return self.adb.turn_on()
        if self.mode == "roku":   return self.roku.power_on()
        if self.mode == "samsung":return self.samsung.tv_on()
        if self.mode == "cec":    return self.cec.tv_on()
        if self.mode == "http":   return self.http_dev.call("on")
        return self.cec.tv_on()

    def turn_off(self, device="tv") -> str:
        if self.mode == "adb":    return self.adb.turn_off()
        if self.mode == "roku":   return self.roku.power_off()
        if self.mode == "samsung":return self.samsung.tv_off()
        if self.mode == "cec":    return self.cec.tv_off()
        if self.mode == "http":   return self.http_dev.call("off")
        return self.cec.tv_off()

    def set_volume(self, level: int) -> str:
        if self.mode == "adb":    return self.adb.set_volume(level)
        if self.mode == "samsung":return self.samsung.set_volume(level)
        if self.mode == "roku":   return self.roku.set_volume(level)
        return f"Volume control not available in mode '{self.mode}'."

    def volume_up(self) -> str:
        if self.mode == "adb":    return self.adb.volume_up()
        if self.mode == "roku":   return self.roku.press("volume_up")
        if self.mode == "cec":    return self.cec.tv_volume_up()
        return "Volume up not available."

    def volume_down(self) -> str:
        if self.mode == "adb":    return self.adb.volume_down()
        if self.mode == "roku":   return self.roku.press("volume_down")
        if self.mode == "cec":    return self.cec.tv_volume_down()
        return "Volume down not available."

    def mute(self) -> str:
        if self.mode == "adb":    return self.adb.mute()
        if self.mode == "samsung":return self.samsung.mute()
        if self.mode == "roku":   return self.roku.press("mute")
        if self.mode == "cec":    return self.cec.tv_mute()
        return "Mute not available."

    def set_channel(self, channel: int) -> str:
        if self.mode == "samsung":return self.samsung.set_channel(channel)
        return f"Channel changing not supported in mode '{self.mode}'."

    def set_input(self, source: str) -> str:
        """Switch input: hdmi1, hdmi2, usb, etc."""
        m = re.search(r"hdmi\s*(\d)", source.lower())
        if self.mode == "cec" and m: return self.cec.set_input(int(m.group(1)))
        if self.mode == "samsung":   return self.samsung.set_input(source)
        return f"Input switching not supported in mode '{self.mode}'."

    def launch_app(self, app_name: str) -> str:
        if self.mode == "adb":  return self.adb.launch_app(app_name)
        if self.mode == "roku": return self.roku.launch_app(app_name)
        return f"App launching not supported in mode '{self.mode}'."

    def search(self, query: str) -> str:
        if self.mode == "adb":  return self.adb.search(query)
        if self.mode == "roku": return self.roku.press("search") + " (Manual typing required on Roku)"
        return f"Search not supported in mode '{self.mode}'."

    def press_key(self, key: str) -> str:
        if self.mode == "adb":    return self.adb.send_key(key)
        if self.mode == "roku":   return self.roku.press(key)
        return f"Key injection not supported in mode '{self.mode}'."

    def get_status(self) -> str:
        if self.mode == "adb":    return self.adb.get_status()
        if self.mode == "samsung":return self.samsung.get_status()
        if self.mode == "roku":   return "Roku status: connected."
        if self.mode == "cec":    return "HDMI-CEC: connected." if self.cec.available else "HDMI-CEC: unavailable."
        return "Status not available."

    def wake_tv(self) -> str:
        mac = self.cfg.get("samsung_tv_mac", "") or self.cfg.get("lg_tv_mac", "")
        if self.mode == "adb": return self.adb.turn_on()
        if mac:                return wake_on_lan(mac)
        return self.turn_on()
