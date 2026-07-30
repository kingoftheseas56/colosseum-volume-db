"""Measure Fandom synopsis reach across the 40-series gap_rate sample (Task 6 report).

Proof-and-report ONLY. Writes reports/synopsis_reach_40.json (NOT db/). db/ stays pristine.

Names the population explicitly (Note 1): this is the 40-series gap_rate sample -- 29 qualified
by gate, 11 failed. Applies Task 5b: an unreachable synopsis fetch lands in its own bucket,
distinct from "no blurbs."
"""
import json
import pathlib
import sys
import time

from comick_volume_db import fallback as fb
from comick_volume_db.http_retry import SourceUnreachable


def _log(msg):
    print(msg, flush=True)


def main():
    sample = json.loads(pathlib.Path("reports/gap_rate.json").read_text(encoding="utf-8"))
    titles = [s["title"] for s in sample["series"]]

    _log(f"POPULATION: {len(titles)}-series gap_rate sample "
         f"({sample['qualified']} qualified / {sample['failed']} failed by gate).")
    _log(f"Probing Fandom synopsis reach, independent of range precedence (Task 6)...")

    results = []
    t0 = time.time()
    for i, t in enumerate(titles, 1):
        try:
            syn, url = fb.fandom_source.fetch_fandom_synopses(t)
            n = len(syn) if syn else 0
            results.append({"title": t, "status": "ok", "blurbCount": n})
        except SourceUnreachable as e:
            results.append({"title": t, "status": "unreachable", "blurbCount": 0,
                            "note": str(e)[:80]})
        except Exception as e:  # noqa: BLE001 -- we want to SEE any failure type, not crash
            results.append({"title": t, "status": f"error:{type(e).__name__}",
                            "blurbCount": 0, "note": str(e)[:80]})
        _log(f"  [{i:2d}/{len(titles)}] {t:28s} -> "
             f"{results[-1]['status']:14s} {results[-1]['blurbCount']} blurbs "
             f"({time.time()-t0:.0f}s elapsed)")

    with_blurb = [r for r in results if r["blurbCount"] > 0]
    without = [r for r in results if r["status"] == "ok" and r["blurbCount"] == 0]
    unreach = [r for r in results if r["status"] == "unreachable"]
    errs = [r for r in results if r["status"].startswith("error")]
    total_blurbs = sum(r["blurbCount"] for r in with_blurb)

    _log("")
    _log("=" * 70)
    _log(f"SYNOPSIS REACH: {len(with_blurb)} of {len(titles)} series gain >=1 Fandom blurb.")
    _log(f"  with blurbs   : {len(with_blurb)}")
    _log(f"  no blurbs     : {len(without)}  (wiki reachable, no blurb section found)")
    _log(f"  unreachable   : {len(unreach)}  (Task 5b bucket -- re-run on own)")
    _log(f"  errors        : {len(errs)}")
    _log(f"TOTAL blurbs fetched: {total_blurbs}")
    _log("")
    _log("Series that GAIN blurbs:")
    for r in sorted(with_blurb, key=lambda x: -x["blurbCount"]):
        _log(f"  {r['blurbCount']:3d}  {r['title']}")
    if without:
        _log("")
        _log("Series with NO blurb (reachable):")
        for r in without:
            _log(f"  {r['title']}")
    if unreach:
        _log("")
        _log("UNREACHABLE (Task 5b):")
        for r in unreach:
            _log(f"  {r['title']}  ({r.get('note','')})")

    out = {
        "population": (f"{len(titles)}-series gap_rate sample "
                       f"({sample['qualified']} qualified / {sample['failed']} failed by gate)"),
        "synopsisReach": len(with_blurb),
        "totalSeries": len(titles),
        "totalBlurbs": total_blurbs,
        "withBlurbs": [r["title"] for r in with_blurb],
        "noBlurbsReachable": [r["title"] for r in without],
        "unreachable": [r["title"] for r in unreach],
        "errors": [{"title": r["title"], "status": r["status"]} for r in errs],
        "perSeries": results,
    }
    p = pathlib.Path("reports/synopsis_reach_40.json")
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"\nraw -> {p}")


if __name__ == "__main__":
    main()
