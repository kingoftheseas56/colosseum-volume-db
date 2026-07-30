"""Task 0b — measure Comick's REAL qualification rate across ordinary series.

The 11 seeds are hand-picked flagships, not the population: the app's architecture is
(published DB) + (live Comick scrape on a miss), so it already serves arbitrary series that
were never seeded. The number that decides whether the fallback-source machinery (Tasks 1-5)
is worth building is Comick's FAILURE RATE across ordinary series, not across flagships.

This runs the EXISTING Comick path against a sample of NON-seed series and records, per title:
  - whether Comick produced a mapping (search + chapters + group_volumes -> volumes),
  - whether the existing gate qualified it,
  - the gateReason on failure (and the stage it failed at).

It writes NO new source module and touches db/ NOT AT ALL (read-only w.r.t. the DB). It reuses
comick_client (search resolution + chapter fetch) and volume_builder (group_volumes,
numbering_is_oddball, gate) -- the exact functions build_db.py runs, minus the orthogonal
WeebCentral record-write step, which keys records but does not affect whether Comick's data
qualifies. Keeping it out is the faithful measurement of the Comick path specifically.

Rate-limited politely (sleep between series, bounded retry on 429/5xx). If Comick throttles
past retry, the run stops early and reports what was actually sampled -- never invents coverage.
"""
import collections
import json
import pathlib
import time

import requests

from comick_volume_db import comick_client
from comick_volume_db.volume_builder import gate, group_volumes, numbering_is_oddball

HERE = pathlib.Path(__file__).parent
SEEDS = json.loads((HERE / "seeds.json").read_text(encoding="utf-8"))
REPORTS = HERE.parent / "reports"

# A spread chosen to span the population, NOT cherry-picked flagships:
#   - long-running shonen, seinen, completed, ongoing, mid-popularity, plus manhwa (Comick
#     indexes manhwa too, so it is a real edge for the rate).
# None are in seeds.json (verified at runtime -> assertion).
SAMPLE = [
    # long-running shonen
    ("Detective Conan", "long shonen"),
    ("Hunter x Hunter", "long shonen"),
    ("Kingdom", "long shonen"),
    ("Toriko", "long shonen"),
    ("Fairy Tail", "long shonen"),
    ("Gintama", "long shonen"),
    ("JoJo's Bizarre Adventure", "long shonen"),
    ("Black Clover", "long shonen"),
    # seinen
    ("Monster", "seinen"),
    ("Blade of the Immortal", "seinen"),
    ("Goodnight Punpun", "seinen"),
    ("Battle Angel Alita", "seinen"),
    ("Tokyo Ghoul", "seinen"),
    ("Delicious in Dungeon", "seinen"),
    ("Land of the Lustrous", "seinen"),
    ("Mushishi", "seinen"),
    ("Fire Punch", "seinen"),
    # completed (mixed)
    ("Demon Slayer", "completed"),
    ("Jujutsu Kaisen", "completed"),
    ("The Promised Neverland", "completed"),
    ("Attack on Titan", "completed"),
    ("Rurouni Kenshin", "completed"),
    ("Yu Yu Hakusho", "completed"),
    ("Slam Dunk", "completed"),
    ("Soul Eater", "completed"),
    ("Claymore", "completed"),
    ("Deadman Wonderland", "completed"),
    ("Eyeshield 21", "completed"),
    ("Haikyuu!!", "completed"),
    # ongoing
    ("One-Punch Man", "ongoing"),
    ("Chainsaw Man", "ongoing"),
    ("Spy x Family", "ongoing"),
    ("Oshi no Ko", "ongoing"),
    ("Kaiju No. 8", "ongoing"),
    ("Blue Box", "ongoing"),
    ("Sakamoto Days", "ongoing"),
    ("Dandadan", "ongoing"),
    ("Witch Hat Atelier", "ongoing"),
    # manhwa (Comick indexes it; real edge case for the rate)
    ("Solo Leveling", "manhwa"),
    ("Tower of God", "manhwa"),
]

INTER_SERIES_SLEEP = 1.5   # seconds between series (search+fetch = 2 calls each)
MAX_RETRIES = 3            # per-request retry on 429/5xx
RETRY_BACKOFF = 4.0        # seconds, doubled each retry


def _resolve_best(title):
    """Same resolution as comick_client.search, but returns the full best result dict so we can
    record which series Comick actually matched (surface mismatches honestly). Pure reuse of
    comick_client._norm / pick_best / SEARCH_LIMIT / HEADERS / BASE -- no new resolution logic.
    """
    r = requests.get(f"{comick_client.BASE}/v1.0/search",
                     params={"q": title, "limit": comick_client.SEARCH_LIMIT},
                     headers=comick_client.HEADERS, timeout=30)
    r.raise_for_status()
    return comick_client.pick_best(r.json(), title)


def _fetch_with_retry(hid):
    """comick_client.fetch_chapters with bounded retry on throttling/server errors."""
    url = f"{comick_client.BASE}/comic/{hid}/chapters"
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, params={"limit": 100000, "chap-order": 1},
                             headers=comick_client.HEADERS, timeout=60)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(RETRY_BACKOFF * (2 ** attempt))
                continue
            r.raise_for_status()
            return r.json().get("chapters", []), None
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(RETRY_BACKOFF * (2 ** attempt))
    return None, last or "exhausted retries"


def measure_one(title, category):
    """Run the existing Comick path for one title. Returns the measurement dict."""
    out = {"title": title, "category": category, "comickHid": None,
           "matchedTitle": None, "chapterCount": 0, "volumesMapped": 0,
           "numberingQuirk": None, "qualified": None, "gateReason": "", "stage": None,
           "error": None}
    try:
        best = _resolve_best(title)
    except requests.RequestException as e:
        out.update(stage="search_failed", error=f"{type(e).__name__}: {e}",
                   gateReason="search failed")
        return out
    if not best:
        out.update(stage="search_failed", gateReason="no comick match")
        return out
    out["comickHid"] = best.get("hid")
    out["matchedTitle"] = best.get("title")

    chapters, err = _fetch_with_retry(best["hid"])
    if chapters is None:
        out.update(stage="fetch_failed", error=err, gateReason=f"chapters fetch failed: {err}")
        return out
    out["chapterCount"] = len(chapters)

    volumes = group_volumes(chapters)
    out["volumesMapped"] = len(volumes)
    if not volumes:
        out.update(stage="no_volumes", gateReason="no volume tagging",
                   qualified=False, numberingQuirk=None)
        return out

    oddball = numbering_is_oddball(chapters)
    qualified, reason = gate(volumes, oddball, chapters)
    out.update(numberingQuirk=oddball, qualified=qualified, gateReason=reason,
               stage="gate")
    return out


def main():
    # Guard: none of the sample may be a seed -- otherwise the rate is contaminated by flagships.
    leaks = [t for t, _ in SAMPLE if t in SEEDS]
    assert not leaks, f"SAMPLE must exclude seeds; found: {leaks}"

    REPORTS.mkdir(exist_ok=True)
    results = []
    throttled = False
    for i, (title, category) in enumerate(SAMPLE, 1):
        rec = measure_one(title, category)
        # If we hit throttling on the fetch, stop early rather than invent coverage.
        if rec["stage"] == "fetch_failed" and rec["error"] and "429" in rec["error"]:
            throttled = True
            results.append(rec)
            print(f"[{i:>2}/{len(SAMPLE)}] {title:32} THROTTLED -- stopping sample early.")
            break
        results.append(rec)
        flag = "OK " if rec["qualified"] else "FAIL"
        reason = rec["gateReason"] or "-"
        print(f"[{i:>2}/{len(SAMPLE)}] {title:32} {flag}  vols={rec['volumesMapped']:>3}  "
              f"chaps={rec['chapterCount']:>5}  {reason}")
        time.sleep(INTER_SERIES_SLEEP)

    sampled = len(results)
    n_qual = sum(1 for r in results if r["qualified"])
    n_fail = sampled - n_qual
    by_reason = collections.Counter(
        r["gateReason"] for r in results if not r["qualified"])
    by_stage = collections.Counter(r["stage"] for r in results if not r["qualified"])
    rate = (n_fail / sampled * 100.0) if sampled else 0.0

    report = {
        "sampledAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requested": len(SAMPLE),
        "actuallySampled": sampled,
        "throttled": throttled,
        "qualified": n_qual,
        "failed": n_fail,
        "failureRatePercent": round(rate, 1),
        "failuresByGateReason": dict(by_reason),
        "failuresByStage": dict(by_stage),
        "series": results,
    }
    out_path = REPORTS / "gap_rate.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 72)
    print("TASK 0b -- Comick qualification rate across ordinary series")
    print("=" * 72)
    print(f"Requested sample:      {len(SAMPLE)}")
    print(f"Actually sampled:      {sampled}" + ("  [THROTTLED -- stopped early]" if throttled else ""))
    print(f"Qualified:             {n_qual}")
    print(f"Failed:                {n_fail}")
    print(f"FAILURE RATE:          {rate:.1f}%")
    print()
    print("Failures by stage:")
    for stage, n in sorted(by_stage.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:>3}  {stage}")
    print("Failures by gateReason:")
    for reason, n in sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:>3}  {reason}")
    print()
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
