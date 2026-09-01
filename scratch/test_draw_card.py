#!/usr/bin/env python3
import sys
import os

sys.path.append("/home/ahmad/aria")
from bmo.instagram.scheduler import BMOCardGenerator

def test_draw():
    print("Initializing BMOCardGenerator...")
    gen = BMOCardGenerator()
    
    caption = "Loading happiness... done. BMO is ready! #bmo #cute"
    print(f"Generating post card for caption: '{caption}'")
    post_path = gen.make_post(caption)
    print(f"Success! Post card saved at: {post_path} (Exists: {os.path.exists(post_path)})")
    
    print(f"Generating story card...")
    story_path = gen.make_story(caption)
    print(f"Success! Story card saved at: {story_path} (Exists: {os.path.exists(story_path)})")

if __name__ == "__main__":
    test_draw()
