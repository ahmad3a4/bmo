import os
import json
from urllib.parse import unquote

# 3 levels up from bmo/tools/import_session.py -> project root.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def import_session():
    print("=== Instagram Manual Session Import ===")
    print("Because Instagram blocks automated logins from your IP, you need to copy")
    print("your session cookie directly from your web browser.")
    print("\nHow to get it:")
    print("1. Open Google Chrome or Firefox on your computer")
    print("2. Go to https://www.instagram.com/ and log in as hey.bmo.ai")
    print("3. Right-click anywhere and select 'Inspect' (or press F12)")
    print("4. Go to the 'Application' tab (Chrome) or 'Storage' tab (Firefox)")
    print("5. On the left sidebar, expand 'Cookies' and click 'https://www.instagram.com'")
    print("6. Find the row named 'sessionid' and double-click its Value to copy it.")
    print("   (It usually looks like: 1234567890%3Aabcd...)")

    sessionid = input("\nPaste your sessionid here: ").strip()

    if not sessionid:
        print("No sessionid provided. Exiting.")
        return

    # Double unquote to ensure it's raw
    sessionid = unquote(unquote(sessionid))

    # Save minimal session file — instagrapi handles everything else
    session_data = {"sessionid": sessionid}

    session_file = os.path.join(_ROOT, "data", "ig_session.json")
    os.makedirs(os.path.dirname(session_file), exist_ok=True)

    with open(session_file, "w") as f:
        json.dump(session_data, f, indent=4)

    print(f"\n[✓] Session saved to {session_file}!")
    print("You can now start BMO. It will use login_by_sessionid() to connect.")

if __name__ == "__main__":
    import_session()
