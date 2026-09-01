import json
import secrets
import threading
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer
import urllib.parse
import re

from bmo.paths import WEB_DIR, CONFIG_PATH as _CFG_PATH


def _load_or_create_token():
    """Load api_token from config.json, generating and persisting one if absent."""
    try:
        with open(_CFG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    token = cfg.get("api_token")
    if not token:
        token = secrets.token_hex(16)
        cfg["api_token"] = token
        try:
            with open(_CFG_PATH, "w") as f:
                json.dump(cfg, f, indent=4)
            print(f"[API] Generated new api_token and saved to config.json: {token}", flush=True)
        except Exception as e:
            print(f"[API] Could not persist api_token: {e}", flush=True)
    return token


API_TOKEN = _load_or_create_token()


class BMOAPIHandler(SimpleHTTPRequestHandler):
    agent = None  # Will be set before starting

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def _authorized(self):
        return secrets.compare_digest(self.headers.get("X-BMO-Token", ""), API_TOKEN)

    def do_GET(self):
        # API Endpoints
        if self.path.startswith("/api/status"):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()

            # Gather state
            spotify_playing = getattr(self.agent, "_spotify_playing", False)
            state = self.agent.state if self.agent else "unknown"

            resp = {
                "state": state,
                "spotify_playing": spotify_playing
            }
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        return super().do_GET()

    def _read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0) or 0)
        post_data = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(post_data.decode('utf-8') or "{}")

    def do_POST(self):
        if self.path in ("/api/command", "/api/speak") and not self._authorized():
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": "unauthorized"}).encode('utf-8'))
            return

        if self.path == "/api/command":
            try:
                data = self._read_json_body()
            except Exception:
                self.send_error(400, "Invalid request body")
                return
            command = data.get("command", "")

            if command and self.agent:
                # Process the command just like _main_loop does
                self._process_command(command)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "command": command}).encode('utf-8'))
            return

        if self.path == "/api/speak":
            try:
                data = self._read_json_body()
            except Exception:
                self.send_error(400, "Invalid request body")
                return
            text = data.get("text", "")

            if text and self.agent:
                self.agent.enqueue(text)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            return

        self.send_error(404, "Endpoint not found")

    def _process_command(self, text):
        """Silently process a command as if it were spoken."""
        low = text.lower()

        # Check interrupts
        if any(x in low for x in ["stop", "cancel", "be quiet", "shut up"]):
            self.agent._do_interrupt()
            return

        # Try skills
        fast_action = self.agent.skills.match_intent(text)
        if fast_action:
            self.agent._set_state("think", "Executing action...")
            result = self.agent.skills.route(fast_action, original_query=text)
            if result:
                self.agent.enqueue(result)
            self.agent.sfx.play("done")
            return

        # Fallback to LLM
        self.agent._set_state("think", "Thinking...")
        # Start a thread so we don't block the HTTP response
        threading.Thread(target=self._ask_llm, args=(text,), daemon=True).start()

    def _ask_llm(self, text):
        try:
            reply = self.agent.ai.ask(text + "\n(OOC: CRITICAL INSTRUCTION: Keep it short!)")
            safe_reply = reply.replace("'", "").replace("<think>", "").replace("</think>", "")

            extracted_emotion = None
            for tag in ["[HAPPY]", "[SAD]", "[ANGRY]", "[EXCITED]", "[CONFUSED]", "[LAUGH]", "[IN_LOVE]"]:
                if tag in safe_reply:
                    extracted_emotion = tag.strip("[]").lower()
                    safe_reply = safe_reply.replace(tag, "")

            if extracted_emotion and self.agent._bmo_faces and self.agent._bmo_faces._emotion != "rude":
                self.agent._bmo_faces.set_emotion(extracted_emotion)

            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', safe_reply) if s.strip()]
            for s in sentences:
                self.agent.enqueue(s)
            self.agent.sfx.play("done")
        except Exception as e:
            print(f"[API] Error in LLM thread: {e}")

def run_server(agent, port=8080):
    BMOAPIHandler.agent = agent

    # Create web dir if it doesn't exist
    if not os.path.exists(WEB_DIR):
        os.makedirs(WEB_DIR)

    server_address = ('', port)
    httpd = HTTPServer(server_address, BMOAPIHandler)
    print(f"[API] Starting BMO Web App on port {port}...")
    httpd.serve_forever()

def start_bmo_app(agent):
    thread = threading.Thread(target=run_server, args=(agent,), daemon=True)
    thread.start()
    return thread
