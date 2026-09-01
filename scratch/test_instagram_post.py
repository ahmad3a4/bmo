#!/usr/bin/env python3
"""Test: generate BMO photo and post via Playwright browser (permanent session)."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")) as f:
    cfg = json.load(f)

from bmo.instagram.scheduler import BMOCaptionAI, BMOCardGenerator
from bmo.instagram.web import InstagramWebPoster

print("=" * 50)
print("BMO Instagram Feed Post Test (Browser Mode)")
print("=" * 50)

# 1. Caption
print("\n[1] Generating AI caption...")
ai      = BMOCaptionAI(cfg.get("groq_api_key",""), cfg.get("instagram_theme","BMO adventures"))
caption = ai.generate_caption()
print(f"Caption: {caption}")

# 2. Photo card
print("\n[2] Generating photo...")
gen        = BMOCardGenerator()
photo_path = gen.make_story(caption) # Using same card generator for now
print(f"Saved: {photo_path}")

# 3. Connect browser
print("\n[3] Connecting browser to Instagram...")
poster = InstagramWebPoster(cfg.get("instagram_username",""), cfg.get("instagram_password",""))
ok     = poster.connect()

if not ok:
    print("\n✗ Could not log in. Check credentials or approve any email/phone verification Instagram sent.")
    sys.exit(1)

# 4. Post photo
print("\n[4] Posting photo...")
result = poster.post_photo(photo_path, caption)
print(f"Result: {result}")

poster.stop()
print("\nDone!")
