import requests


# ─── PC Control ──────────────────────────────────────────────────────────────
class PCControlSkill:
    def __init__(self, cfg):
        self.ip = cfg.get("pc_ip", "")
        self.mac = cfg.get("pc_mac", "")
        self.token = cfg.get("pc_agent_token", "")
        self.port = 8080
        self.enabled = bool(self.ip)
        if self.enabled:
            print(f"[PC CONTROL] PC Agent at {self.ip}:{self.port} configured.", flush=True)
            if not self.token:
                print("[PC CONTROL] WARNING: no 'pc_agent_token' set in config.json — "
                      "the PC agent will reject all commands until BMO_PC_TOKEN matches it.", flush=True)

    def turn_on(self):
        if not self.mac:
            return "I don't know your PC's MAC address to wake it up."
        import socket
        try:
            mac = self.mac.replace("-", "").replace(":", "")
            data = bytes.fromhex('FF' * 6 + mac * 16)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(data, ('255.255.255.255', 9))
            sock.close()
            return "Sending magic wake up packet to your PC!"
        except Exception as e:
            return f"Failed to wake PC: {e}"

    def _send(self, command, timeout=5, **extra):
        if not self.enabled:
            return "PC Control is not configured."
        try:
            url = f"http://{self.ip}:{self.port}"
            headers = {"X-BMO-Token": self.token} if self.token else {}
            payload = {"command": command, **extra}
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            try:
                msg = r.json().get("message", "")
            except Exception:
                msg = ""
            if r.status_code != 200:
                return msg or "PC command failed."
            return msg or "Command sent to PC."
        except Exception as e:
            return f"Could not reach PC Agent: {e}"

    def lock(self): return self._send("lock")
    def sleep(self): return self._send("sleep")
    def shutdown(self): return self._send("shutdown")
    def restart(self): return self._send("restart")
    def mute(self): return self._send("mute")
    def youtube(self): return self._send("youtube")
    def spotify(self): return self._send("spotify")
    def launch_app(self, app_name):
        return self._send("launch_app", app=app_name.strip().lower())
    def close_app(self, app_name):
        return self._send("close_app", app=app_name.strip().lower())
    def set_volume(self, level):
        return self._send("set_volume", level=level)
    def top_processes(self):
        return self._send("top_processes")
    def screenshot(self):
        return self._send("screenshot", timeout=15)  # first PowerShell call compiles C# — can be slow
    def read_clipboard(self):
        return self._send("read_clipboard")
    def playtime(self, app_name):
        return self._send("playtime", app=app_name.strip().lower())
    def gpu_temp(self):
        return self._send("gpu_temp")
