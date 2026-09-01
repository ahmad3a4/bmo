try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    HAS_SPOTIFY = True
except ImportError:
    HAS_SPOTIFY = False
    print("[SPOTIFY] spotipy not installed.")


# ─── Spotify ─────────────────────────────────────────────────────────────────
class SpotifySkill:
    def __init__(self, cfg):
        self.sp  = None
        cid = cfg.get("spotify_client_id", "")
        cs  = cfg.get("spotify_client_secret", "")
        ru  = cfg.get("spotify_redirect_uri", "http://localhost:8888/callback")
        if not HAS_SPOTIFY or not cid or not cs:
            print("[SPOTIFY] Disabled — no credentials.", flush=True)
            return
        try:
            scope = (
                "user-read-playback-state user-modify-playback-state "
                "user-read-currently-playing"
            )
            am = SpotifyOAuth(
                client_id=cid, client_secret=cs,
                redirect_uri=ru, scope=scope, open_browser=False
            )
            if not am.get_cached_token():
                print("[SPOTIFY] Run 'python spotify_setup.py' first.", flush=True)
                return
            self.sp = spotipy.Spotify(auth_manager=am)
            self.sp.current_user()
            print("[SPOTIFY] Connected.", flush=True)
        except Exception as e:
            print(f"[SPOTIFY] Auth error: {e}", flush=True)

    def _active_device(self):
        if not self.sp:
            return None
        devs = self.sp.devices().get("devices", [])
        active = [d for d in devs if d.get("is_active")]
        return (active or devs or [{}])[0].get("id")

    def play(self, query):
        if not self.sp:
            return "Spotify is not configured."
        try:
            results = self.sp.search(q=query, type="track", limit=1)
            tracks  = results["tracks"]["items"]
            if not tracks:
                return f"No track found for '{query}' on Spotify."
            dev_id = self._active_device()
            if not dev_id:
                return "No active Spotify device. Open Spotify on your phone or Pi first."
            t = tracks[0]
            self.sp.start_playback(device_id=dev_id, uris=[t["uri"]])
            return f"Now playing {t['name']} by {t['artists'][0]['name']}."
        except Exception as e:
            return f"Spotify error: {e}"

    def pause(self):
        if not self.sp: return "Spotify not connected."
        try: self.sp.pause_playback(); return "Playback paused."
        except: return "Could not pause."

    def resume(self):
        if not self.sp: return "Spotify not connected."
        try: self.sp.start_playback(); return "Playback resumed."
        except: return "Could not resume."

    def next_track(self):
        if not self.sp: return "Spotify not connected."
        try: self.sp.next_track(); return "Skipped to next track."
        except: return "Could not skip."

    def prev_track(self):
        if not self.sp: return "Spotify not connected."
        try: self.sp.previous_track(); return "Going to previous track."
        except: return "Could not go back."

    def set_volume(self, level):
        if not self.sp: return "Spotify not connected."
        level = max(0, min(100, int(level)))
        try:
            dev_id = self._active_device()
            if dev_id:
                self.sp.volume(level, device_id=dev_id)
            return f"Spotify volume set to {level} percent."
        except Exception as e:
            return f"Volume error: {e}"

    def current_track(self):
        if not self.sp: return "Spotify not connected."
        try:
            pb = self.sp.current_playback()
            if not pb or not pb.get("item"):
                return "Nothing is currently playing."
            t = pb["item"]
            st = "playing" if pb.get("is_playing") else "paused"
            return (f"Currently {st}: {t['name']} "
                    f"by {t['artists'][0]['name']}.")
        except Exception as e:
            return f"Error: {e}"

    def current_track_info(self) -> dict:
        """Return structured now-playing data for the HUD. Returns None if nothing playing."""
        if not self.sp:
            return None
        try:
            pb = self.sp.current_playback()
            if not pb or not pb.get("item"):
                return None
            t = pb["item"]
            return {
                "name":        t["name"],
                "artist":      t["artists"][0]["name"],
                "is_playing":  pb.get("is_playing", False),
                "progress_ms": pb.get("progress_ms", 0),
                "duration_ms": t.get("duration_ms", 0),
            }
        except Exception:
            return None
