#!/usr/bin/env python3
import os
import json
from urllib.parse import unquote

# 3 levels up from bmo/tools/import_playwright_session.py -> project root.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def import_to_playwright():
    print("=== Instagram Playwright Session Injector ===")
    print("This will inject your real browser session into BMO's Playwright browser.")
    print("This bypasses the login wall, and Playwright will keep the session alive for weeks.\n")

    sessionid = input("Paste your sessionid from Chrome/Firefox: ").strip()
    if not sessionid:
        print("No sessionid provided.")
        return

    sessionid = unquote(unquote(sessionid))

    # Create a Playwright-compatible cookie object
    cookie = {
        "name": "sessionid",
        "value": sessionid,
        "domain": ".instagram.com",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax"
    }

    cookies_file = os.path.join(_ROOT, "data", "ig_cookies.json")
    os.makedirs(os.path.dirname(cookies_file), exist_ok=True)

    # Load existing or create new
    cookies = []
    if os.path.exists(cookies_file):
        try:
            with open(cookies_file) as f:
                cookies = json.load(f)
            # Remove any existing sessionid to prevent duplicates
            cookies = [c for c in cookies if c.get("name") != "sessionid"]
        except Exception:
            pass

    cookies.append(cookie)

    with open(cookies_file, "w") as f:
        json.dump(cookies, f, indent=2)

    print(f"\n[✓] Session injected into {cookies_file}!")
    print("Run the test script again — it will instantly log in without typing credentials.")

if __name__ == "__main__":
    import_to_playwright()
