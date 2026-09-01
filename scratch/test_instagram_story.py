#!/usr/bin/env python3
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bmo.instagram.web import InstagramWebPoster
from bmo.instagram.scheduler import BMOCardGenerator

def main():
    print("Loading config...")
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
    with open(config_path) as f:
        cfg = json.load(f)

    username = cfg.get("instagram_username")
    password = cfg.get("instagram_password")

    print("Generating a test story card...")
    card_gen = BMOCardGenerator()
    img_path = card_gen.make_story("Diagnostic Story Test!")

    print(f"Starting InstagramWebPoster for user: {username} (headless=True)")
    poster = InstagramWebPoster(username, password, headless=True)
    
    # We will patch the post_story implementation inside our test script to save screenshots at every stage
    original_impl = poster._post_story_impl
    
    def patched_post_story_impl(image_path):
        try:
            print("[PATCHED] Starting story post flow...")
            page = poster._page
            
            # Navigate to Instagram
            page.goto(poster.IG_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(5)
            page.screenshot(path="scratch/01_homepage.png")
            print("[PATCHED] 01_homepage.png saved.")
            
            # Dismiss popups
            for dismiss_text in ["Not now", "Not Now", "Skip", "Later", "Cancel"]:
                try:
                    btn = page.locator(f"text='{dismiss_text}'").last
                    if btn.is_visible(timeout=2000):
                        btn.click(force=True)
                        print(f"[PATCHED] Dismissed popup: {dismiss_text}")
                        time.sleep(1)
                except Exception:
                    pass
            page.screenshot(path="scratch/02_after_popup_dismiss.png")
            print("[PATCHED] 02_after_popup_dismiss.png saved.")

            # Run the actual flow
            res = original_impl(image_path)
            
            # Take a final screenshot
            page.screenshot(path="scratch/03_final_state.png")
            print("[PATCHED] 03_final_state.png saved.")
            return res
        except Exception as e:
            print(f"[PATCHED] Error in flow: {e}")
            try:
                poster._page.screenshot(path="scratch/error_state.png")
                print("[PATCHED] Saved scratch/error_state.png")
            except Exception:
                pass
            raise e

    poster._post_story_impl = patched_post_story_impl

    print("Running story post...")
    res = poster.post_story(img_path)
    print(f"Result: {res}")
    
if __name__ == "__main__":
    main()
