import shutil
import requests

players = ["mpv", "cvlc", "ffplay", "vlc"]
for p in players:
    print(f"{p}: {shutil.which(p)}")

streams = [
    "http://stream.radiorecurse.com:8000/lofi.mp3",
    "https://stream.zeno.fm/0r0xa792kwzuv",
    "https://stream.zeno.fm/f3wvbb76kwzuv",
]

for s in streams:
    try:
        r = requests.head(s, timeout=5)
        print(f"{s}: {r.status_code}")
    except Exception as e:
        print(f"{s}: Error {e}")
