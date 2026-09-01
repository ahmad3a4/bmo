import requests

urls = [
    "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExOHp4Z3J4Z3J4Z3J4Z3J4Z3J4Z3J4Z3J4Z3ImZXA9djFfaW50ZXJuYWxfZ2lmX2J5X2lkJmN0PWc/3o7TKMGpxVfFfV8N9K/giphy.gif",
    "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExOHp4Z3J4Z3J4Z3J4Z3J4Z3J4Z3J4Z3J4Z3ImZXA9djFfaW50ZXJuYWxfZ2lmX2J5X2lkJmN0PWc/l0HlS6S0S0k0/giphy.gif",
    "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExOHp4Z3J4Z3J4Z3J4Z3J4Z3J4Z3J4Z3J4Z3ImZXA9djFfaW50ZXJuYWxfZ2lmX2J5X2lkJmN0PWc/3o7TKU8pZfF5fV8N9K/giphy.gif",
]

headers = {"User-Agent": "Mozilla/5.0"}

for url in urls:
    try:
        r = requests.get(url, headers=headers, timeout=5)
        print(f"URL: {url}\nStatus: {r.status_code}\n")
    except Exception as e:
        print(f"URL: {url}\nError: {e}\n")
