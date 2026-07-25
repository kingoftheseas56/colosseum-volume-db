"""One-shot: record real Comick chapter responses so pure-logic tests run offline."""
import json, pathlib, requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
FIX = pathlib.Path(__file__).parent / "fixtures"
TITLES = {"death-note": "death note", "bleach": "bleach",
          "berserk": "berserk", "yani-neko": "chainsmoker cat"}


def get(url):
    return requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=60)


def main():
    FIX.mkdir(exist_ok=True)
    for slug, title in TITLES.items():
        s = get(f"https://api.comick.dev/v1.0/search?q={requests.utils.quote(title)}&limit=5").json()
        hid = s[0]["hid"]
        ch = get(f"https://api.comick.dev/comic/{hid}/chapters?lang=en&limit=100000&chap-order=1").json()
        (FIX / f"comick_chapters_{slug}.json").write_text(json.dumps(ch), encoding="utf-8")
        print(slug, hid, len(ch.get("chapters", [])), "chapters")


if __name__ == "__main__":
    main()
