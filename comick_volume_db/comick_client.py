import requests

BASE = "https://api.comick.dev"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}


def _norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def pick_best(results, title):
    want = _norm(title)
    exact = [r for r in results if _norm(r.get("title")) == want]
    return (exact or results)[0] if results else None


def search(title):
    r = requests.get(f"{BASE}/v1.0/search", params={"q": title, "limit": 10},
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    best = pick_best(r.json(), title)
    return best["hid"] if best else None


def fetch_chapters(hid):
    r = requests.get(f"{BASE}/comic/{hid}/chapters",
                     params={"lang": "en", "limit": 100000, "chap-order": 1},
                     headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json().get("chapters", [])
