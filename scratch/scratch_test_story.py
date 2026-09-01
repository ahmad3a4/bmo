#!/usr/bin/env python3
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bmo.instagram.web import InstagramWebPoster

# Load credentials
config_path = "/home/ahmad/aria/config.json"
try:
    with open(config_path) as f:
        cfg = json.load(f)
except Exception as e:
    print(f"Error loading config.json: {e}")
    sys.exit(1)

username = cfg.get("instagram_username", "")
password = cfg.get("instagram_password", "")

poster = InstagramWebPoster(username, password, headless=False)
try:
    print("Connecting...", flush=True)
    success = poster.connect()
    print(f"Connected: {success}", flush=True)
    
    if success:
        page = poster._page
        # Navigate home
        page.goto(poster.IG_URL, timeout=15000)
        time.sleep(5)
        
        # Take initial screenshot of home page
        page.screenshot(path="/home/ahmad/aria/data/ig_tmp/debug_story_1_home.png")
        print("Home page loaded and screenshot saved.", flush=True)
        
        # Print all buttons and SVGs
        print("\n--- Printing all interactive element details ---", flush=True)
        elements_info = page.evaluate("""
            () => {
                const results = [];
                // Check all SVGs
                const svgs = Array.from(document.querySelectorAll('svg'));
                svgs.forEach((svg, idx) => {
                    const label = svg.getAttribute('aria-label') || '';
                    const parent = svg.closest('button') || svg.closest('[role="button"]') || svg.parentElement;
                    const parentText = parent ? parent.textContent.trim() : '';
                    results.push(`SVG [${idx}]: label="${label}", parent_text="${parentText}", tag=${parent ? parent.tagName : ''}`);
                });
                
                // Check all buttons
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                buttons.forEach((btn, idx) => {
                    results.push(`BTN [${idx}]: text="${btn.textContent.trim()}", aria-label="${btn.getAttribute('aria-label') || ''}", tag=${btn.tagName}`);
                });
                return results.slice(0, 100);
            }
        """)
        for info in elements_info:
            print(info, flush=True)
            
except Exception as e:
    print(f"Error occurred: {e}", flush=True)
finally:
    poster.stop()
