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
    # No `lang` filter on purpose: English scanlators often leave `vol` untagged, so an
    # en-only pull comes out sparse (My Hero Academia: 3 volumes vs 42 all-language).
    # Chapter numbers are canonical across translations, so ranges transfer safely; the
    # extra cross-language disagreement is resolved by majority vote in volume_builder.
    r = requests.get(f"{BASE}/comic/{hid}/chapters",
                     params={"limit": 100000, "chap-order": 1},
                     headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json().get("chapters", [])
