#!/usr/bin/env python3
"""Quick test for the Playwright Instagram poster in non-headless mode.
Run from the project root with:  python -m bmo.tools.test_ig_web
(needs -m since this imports from the bmo package)."""
import sys
import json
import time

from bmo.instagram.web import InstagramWebPoster
from bmo.paths import CONFIG_PATH

# Load credentials
try:
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
except Exception as e:
    print(f"Error loading config.json: {e}")
    sys.exit(1)

username = cfg.get("instagram_username", "")
password = cfg.get("instagram_password", "")

if not username or not password:
    print("Error: instagram_username or instagram_password not set in config.json")
    sys.exit(1)

print("Starting Instagram Web Poster test in NON-HEADLESS mode...")
print(f"Username: {username}")
print()

poster = InstagramWebPoster(username, password, headless=False)
try:
    success = poster.connect()
    print(f"\nConnection / Login result: {'✓ SUCCESS' if success else '✗ FAILED'}")
    if success:
        # Get followers as a quick api test
        followers = poster.get_followers()
        print(f"Followers count: {followers}")
finally:
    # Let it stay open for a few seconds so the user can see
    print("\nTest finished. Keeping browser open for 10 seconds before exit...")
    time.sleep(10)
    poster.stop()
