#!/usr/bin/env python3
"""
Spotify OAuth setup helper — run this ONCE in a terminal before starting ARIA.
Runnable directly: python bmo/tools/spotify_setup.py
"""
import json, os, webbrowser
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# 3 levels up from bmo/tools/spotify_setup.py -> project root. No bmo.paths
# import needed here, so this stays runnable without -m.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
cfg_path = os.path.join(_ROOT, "config.json")
with open(cfg_path) as f:
    cfg = json.load(f)

cid = cfg.get("spotify_client_id", "")
cs  = cfg.get("spotify_client_secret", "")
ru  = cfg.get("spotify_redirect_uri", "http://localhost:8888/callback")

if not cid or not cs:
    print("ERROR: Add your spotify_client_id and spotify_client_secret to config.json first.")
    exit(1)

scope = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
sp    = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=cid, client_secret=cs, redirect_uri=ru,
    scope=scope, open_browser=False
))

try:
    user = sp.current_user()
    print(f"\nSpotify connected as: {user['display_name']} ({user['id']})")
    print("You can now run: python aria.py")
except Exception as e:
    print(f"Error: {e}")
    print("Make sure your redirect URI is set to http://localhost:8888/callback in the Spotify dashboard.")
