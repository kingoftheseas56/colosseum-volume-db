"""TASK 12 - PILOT 100, THEN WE DECIDE THE FULL RUN.

This is the FIRST sample drawn from the RIGHT population: the 1,466 NEW confident unique series
(series Wikipedia documents via Template:Graphic novel list transclusion AND Colosseum can open,
excluding the 12 already in db/ which the fence forbids). Every earlier sample (Task 9 title->
resolve, Task 10 random-from-catalogue) was drawn wrong -- both of those briefs were Hemanth's.

Method:
  1. Load reports/harvestable_population.json, take the CONFIDENT matches.
  2. Dedup by weebcentralId BEFORE any fetch (One Piece appears 6x, Hajime no Ippo 7x -- a naive
     run refetches the same series repeatedly).
  3. Exclude the 12 ids already in db/.
  4. Sample 100 at random (fixed seed, reproducible).
  5. For each, run the FULL real harvest path: fallback.resolve_fallback(series_title). This is
     byte-identical to what harvest_qualified.py does; build_fallback_record wraps it in a record
     but does not change qualification, so calling resolve_fallback directly measures the truth
     without writing anything to db/.
  6. Record source + sourceUrl for every qualified result; gate_reason for unqualified.

The series_title passed to resolve_fallback is the slug with hyphens->spaces, title-cased. This is
the closest representation of 'what the reader knows the series by' that a real harvest would pass;
it matches Task 10's slug_to_query. resolve_fallback's own matcher (_match_page, 5 tiers incl. a
containment fallback) is LOOSER than my join's exact-canonical equality, so the pilot may resolve
some series the join's 'no-match' bucket missed -- that is expected and correct; the join was a
population estimate, the pilot is ground truth.

WRITE NOTHING TO db/. This is a measurement.

Spot-check: after the run, five qualified results are verified by hand against the live Wikipedia
page (separate step) -- the tiling guard proves SHAPE, not TRUTH.
"""
import glob
import json
import os
import random
import time
from pathlib import Path

from comick_volume_db import fallback as fb
from comick_volume_db.http_retry import SourceUnreachable

REPO = Path(__file__).resolve().parent.parent
POP_PATH = REPO / "reports" / "harvestable_population.json"
DB_DIR = REPO / "db"
OUT_PATH = REPO / "reports" / "task12_pilot100.json"

SEED = 20260801
SAMPLE_SIZE = 100


def slug_to_title(slug):
    """WeebCentral slug -> series title for resolve_fallback. 'Ao-No-Exorcist' -> 'Ao No Exorcist'.

    resolve_fallback's matcher normalises both sides (lowercase, drop punctuation), so the exact
    casing of the title does not change the match; we keep the slug's own casing to stay faithful
    to what the reader shows."""
    return slug.replace("-", " ").strip()


def main():
    pop = json.loads(POP_PATH.read_text(encoding="utf-8"))
    confident = pop["confidentMatches"]

    # --- Step 1+2: dedup by weebcentralId BEFORE any fetch ---
    # Long series have N arc-split Wikipedia pages matching one id. Keep one representative slug
    # per id (the first the join found -- deterministic given the cache order).
    by_id = {}
    for m in confident:
        wid = m["weebcentralId"]
        if wid not in by_id:
            by_id[wid] = {"weebcentralId": wid, "slug": m["matchedSlug"],
                          "wikiPage": m["rawWikipedia"]}
    print(f"confident match-records: {len(confident)}")
    print(f"unique weebcentralIds:   {len(by_id)}")

    # --- Step 3: exclude ids already in db/ ---
    db_ids = {os.path.basename(f).replace(".json", "")
              for f in glob.glob(str(DB_DIR / "*.json"))}
    new_ids = {wid: info for wid, info in by_id.items() if wid not in db_ids}
    print(f"already in db/ (excluded): {len(by_id) - len(new_ids)}")
    print(f"NEW unique series (population): {len(new_ids)}")

    # --- Step 4: sample 100 at random (fixed seed) ---
    random.seed(SEED)
    population = sorted(new_ids.values(), key=lambda x: x["weebcentralId"])
    sample = random.sample(population, SAMPLE_SIZE)
    print(f"sampled: {SAMPLE_SIZE} (seed={SEED})")
    print()

    # --- Step 5: run each through the full path ---
    results = []
    counts = {"qualified": 0, "unqualified": 0, "no_fallback_data": 0,
              "unreachable": 0, "error": 0}
    for i, item in enumerate(sample, 1):
        title = slug_to_title(item["slug"])
        wid = item["weebcentralId"]
        outcome = {"weebcentralId": wid, "slug": item["slug"], "title": title,
                   "wikiPage": item["wikiPage"]}
        try:
            res = fb.resolve_fallback(title)
            if res is None:
                outcome["outcome"] = "no_fallback_data"
            elif res["qualified"]:
                outcome.update({"outcome": "qualified", "source": res["source"],
                                "sourceUrl": res["source_url"],
                                "volCount": len(res["volumes"]),
                                "firstRange": f"v{res['volumes'][0]['number']}: "
                                              f"{res['volumes'][0]['chapterStart']}-"
                                              f"{res['volumes'][0]['chapterEnd']}",
                                "lastRange": f"v{res['volumes'][-1]['number']}: "
                                             f"{res['volumes'][-1]['chapterStart']}-"
                                             f"{res['volumes'][-1]['chapterEnd']}"})
            else:
                outcome.update({"outcome": "unqualified", "source": res["source"],
                                "sourceUrl": res["source_url"],
                                "gateReason": res["gate_reason"],
                                "volCount": len(res["volumes"])})
        except SourceUnreachable as e:
            outcome["outcome"] = "unreachable"
            outcome["error"] = str(e)[:200]
        except Exception as e:  # crash-resilient (LocationParseError lesson): capture + continue
            outcome["outcome"] = "error"
            outcome["error"] = f"{type(e).__name__}: {e}"[:200]

        counts[outcome["outcome"]] += 1
        results.append(outcome)
        tag = {"qualified": "QUAL", "unqualified": "UNQU", "no_fallback_data": "NONE",
               "unreachable": "UNRC", "error": "ERR "}[outcome["outcome"]]
        extra = ""
        if outcome["outcome"] == "qualified":
            extra = f"{outcome['volCount']}v src={outcome['source']}"
        elif outcome["outcome"] == "unqualified":
            extra = f"reason={outcome['gateReason'][:40]}"
        elif outcome["outcome"] in ("unreachable", "error"):
            extra = outcome.get("error", "")[:50]
        print(f"[{i:3d}/{SAMPLE_SIZE}] {tag} {item['slug'][:42]:42s} {extra}")
        time.sleep(0.5)  # be a polite client to Wikipedia / Fandom

    # --- Summary ---
    qualified_rate = counts["qualified"] / SAMPLE_SIZE
    report = {
        "task": "Task 12 - pilot 100 from the 1,466 NEW confident unique series",
        "population": {
            "confidentMatchRecords": len(confident),
            "uniqueWeebcentralIds": len(by_id),
            "alreadyInDb": len(by_id) - len(new_ids),
            "newUniqueSeries": len(new_ids),
        },
        "sample": {"size": SAMPLE_SIZE, "seed": SEED},
        "summary": {
            "qualified": counts["qualified"],
            "qualifiedRate": round(qualified_rate, 4),
            "unqualified": counts["unqualified"],
            "noFallbackData": counts["no_fallback_data"],
            "unreachable": counts["unreachable"],
            "error": counts["error"],
            "projectedFullRunYield": int(round(qualified_rate * len(new_ids))),
            "projectedFullRunPopulation": len(new_ids),
        },
        "results": results,
    }
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 70)
    print(f"PILOT 100 RESULTS (population = {len(new_ids)} NEW confident unique series)")
    print("=" * 70)
    print(f"  QUALIFIED:       {counts['qualified']:3d}  ({qualified_rate:.1%})  "
          f"-> projected full-run yield ~{report['summary']['projectedFullRunYield']} shelves")
    print(f"  UNQUALIFIED:     {counts['unqualified']:3d}  (gate refused)")
    print(f"  NO FALLBACK DATA:{counts['no_fallback_data']:3d}  (no Wikipedia/Fandom page)")
    print(f"  UNREACHABLE:     {counts['unreachable']:3d}  (transport failure)")
    print(f"  ERROR:           {counts['error']:3d}  (crash; should be 0)")
    print()
    if counts["qualified"]:
        print("QUALIFIED records (source + sourceUrl for spot-check):")
        for r in results:
            if r["outcome"] == "qualified":
                print(f"  {r['title'][:32]:32s} {r['volCount']:3d}v  src={r['source']:9s} "
                      f"{r['firstRange']}..{r['lastRange']}")
                print(f"    {r['sourceUrl']}")
    print()
    print(f"wrote {OUT_PATH.relative_to(REPO)}")


if __name__ == "__main__":
    main()
