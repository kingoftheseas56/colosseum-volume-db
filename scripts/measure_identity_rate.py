"""Task 9 - MEASURE THE IDENTITY-RESOLUTION FAILURE RATE.

The reading side (Comick chapter fetch + Wikipedia/Fandom fallback + gate) is ready.
The IDENTIFYING side is the wall at scale: every record is keyed by WeebCentral series
id, and weebcentral_client.resolve() refuses any match below MATCH_THRESHOLD (0.8
string similarity). That check is correct and load-bearing - it is what caught
"Beet the Vandel Buster" resolving to "Buster-Keel". But it also refuses legitimate
series WeebCentral lists under a string-dissimilar slug (Demon Slayer -> Kimetsu-No-Yaiba
scored 0.24; Attack on Titan -> Shingeki-no-Kyojin etc.). Demon Slayer only shipped
because Hemanth personally ruled on it using a chapter-count signal. That does not scale.

This script MEASURES the rate. It builds nothing, writes no db/, and changes nothing.
Output: reports/identity_rate.json.

WHAT IT MEASURES, per sampled series:
  - resolved   : resolve() returned a (sid, slug) -- best candidate cleared 0.8.
  - refused    : search returned candidates but the best score < 0.8.
  - unreachable: the search HTTP call itself failed (transport) -- distinct from refused.
  For refusals we ALSO record the best candidate slug + its score, and the top-3 scored
  candidates, so the distribution (clustered near 0.8 = tunable, vs near 0.2 = romaji/
  English, needs alternate-title data) is visible.

SAMPLE SOURCE: C:\\Users\\Suprabha\\Desktop\\Brotherhood\\Colosseum\\data\\mal_catalog.db
(20k manga rows). The Colosseum app reads manga titles as `title_english || title`
(see Colosseum qml/GenreApi.js:94, MagazineApi.js:52, TheatreApi.js:214) -- English
preferred, romaji fallback. We query resolve() with THAT same field so the measurement
reflects the real production call shape. We also carry the romaji `title` alongside so
the romaji-vs-English dimension is inspectable per refusal.

EXCLUSIONS: the 11 seeds (comick_volume_db/seeds.json) and the 40 titles already
sampled in measure_gap_rate.py SAMPLE -- no re-measurement of work already done.

TIER STRATIFICATION by MAL `members` (popularity), NOT fame: bucket the 15,451
type='Manga' rows into 5 equal member-count tiers and draw ~30 per tier, so the sample
spans the popularity distribution rather than concentrating on famous series.
"""
import json
import pathlib
import sqlite3
import time
from collections import Counter

import requests

from comick_volume_db import weebcentral_client as wc

HERE = pathlib.Path(__file__).parent
REPO = HERE.parent
REPORTS = REPO / "reports"

MAL_DB = pathlib.Path(r"C:\Users\Suprabha\Desktop\Brotherhood\Colosseum\data\mal_catalog.db")
SEEDS_JSON = REPO / "comick_volume_db" / "seeds.json"

# Pull the already-sampled 40 by importing the SAMPLE list (single source of truth).
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "measure_gap_rate", REPO / "comick_volume_db" / "measure_gap_rate.py")
_mgm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mgm)
ALREADY_SAMPLED = {t for t, _ in _mgm.SAMPLE}

SEEDS = set(json.loads(SEEDS_JSON.read_text(encoding="utf-8")))

PER_TIER = 30          # ~30 per tier x 5 tiers ~= 150
N_TIERS = 5
INTER_SERIES_SLEEP = 1.2   # be polite to WeebCentral's search endpoint
SEARCH_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 4.0


def draw_sample():
    """Tier-stratified sample of type='Manga' titles, excluding seeds + already-sampled.

    Tiers are equal member-count buckets across the whole type='Manga' population, so
    tier 1 = most popular, tier 5 = least. We draw PER_TIER per tier with a fixed seed
    for reproducibility, skipping rows whose English-preferred title collides with an
    exclusion or is null/blank.
    """
    con = sqlite3.connect(str(MAL_DB))
    cur = con.cursor()
    rows = cur.execute(
        "SELECT mal_id, title, title_english, members FROM manga "
        "WHERE type='Manga' ORDER BY members DESC"
    ).fetchall()
    con.close()

    # English-preferred title, exactly as the Colosseum app reads it.
    def en_pref(t, te):
        return (te or t or "").strip()

    excluded = SEEDS | ALREADY_SAMPLED
    # Pre-filter: drop nulls, blanks, and exact-title exclusions.
    clean = [(mid, t, te, m, en_pref(t, te)) for (mid, t, te, m) in rows
             if en_pref(t, te) and en_pref(t, te).lower() not in {x.lower() for x in excluded}]

    tier_size = len(clean) // N_TIERS
    sample = []
    import random
    rng = random.Random(20260730)  # deterministic for reproducibility
    for i in range(N_TIERS):
        start = i * tier_size
        end = (i + 1) * tier_size if i < N_TIERS - 1 else len(clean)
        tier = clean[start:end]
        # sample without replacement; if tier is small, take what's there
        k = min(PER_TIER, len(tier))
        picks = rng.sample(tier, k)
        for p in picks:
            sample.append({
                "malId": p[0], "titleRomaji": p[1], "titleEnglish": p[2],
                "members": p[3], "tier": i + 1,
                "queriedTitle": p[4],  # en-pref, the real call
            })
    return sample


def search_candidates(title):
    """Replicate weebcentral_client.resolve()'s search + parse, but return the scored
    candidate list instead of just the (sid, slug) decision. Raises requests.RequestException
    on transport failure (caller marks unreachable). Identical HTTP call to resolve().
    """
    r = requests.post("https://weebcentral.com/search/simple",
                      params={"location": "main"}, data={"text": title},
                      headers={"User-Agent": wc.UA, "HX-Request": "true"},
                      timeout=SEARCH_TIMEOUT)
    r.raise_for_status()
    cands = wc.parse_all_series_ids(r.text)  # [(sid, slug), ...] in rank order
    scored = []
    for sid, slug in cands:
        scored.append({"sid": sid, "slug": slug, "score": wc._verify_match(title, slug)})
    # rank by score desc (resolve() takes the best ABOVE threshold)
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored


def search_with_retry(title):
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            return search_candidates(title), None
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(RETRY_BACKOFF * (2 ** attempt))
    return None, last or "exhausted retries"


def measure_one(item):
    """Resolve one series. outcome is one of:
      - resolved           : best candidate cleared MATCH_THRESHOLD.
      - refused_no_match   : WeebCentral returned candidates but the best scored < 0.8.
                             (The romaji-vs-English / threshold question.)
      - refused_no_result  : WeebCentral's search returned ZERO candidates for this query.
                             (Genuinely absent, OR the query needs the romaji title.)
      - unreachable        : the search HTTP call failed (transport) -- distinct from refusal.
    """
    title = item["queriedTitle"]
    out = dict(item)
    out.update(outcome=None, bestSlug=None, bestScore=None,
               topCandidates=[], error=None)
    try:
        scored, err = search_with_retry(title)
    except Exception as e:  # defensive -- never crash the whole run
        out["outcome"] = "unreachable"
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    if scored is None:
        out["outcome"] = "unreachable"
        out["error"] = err
        return out

    # Empty candidate list = WeebCentral's search genuinely found nothing for this query.
    # Distinct from transport failure AND from "candidates existed but scored too low".
    if not scored:
        out["outcome"] = "refused_no_result"
        out["bestScore"] = None
        out["error"] = "search returned 0 candidates"
        return out

    best = scored[0]
    out["bestSlug"] = best["slug"]
    out["bestScore"] = round(best["score"], 4)
    out["topCandidates"] = [
        {"slug": c["slug"], "score": round(c["score"], 4)} for c in scored[:3]
    ]
    if best["score"] >= wc.MATCH_THRESHOLD:
        out["outcome"] = "resolved"
    else:
        out["outcome"] = "refused_no_match"
    return out


def main():
    excluded_note = (f"Excludes {len(SEEDS)} seeds + {len(ALREADY_SAMPLED)} already-sampled "
                     f"(measure_gap_rate SAMPLE).")
    sample = draw_sample()
    print(f"Sample drawn: {len(sample)} series across {N_TIERS} member tiers. {excluded_note}")
    print(f"Per tier: {Counter(s['tier'] for s in sample)}")

    results = []
    for i, item in enumerate(sample, 1):
        rec = measure_one(item)
        results.append(rec)
        flag = {"resolved": "OK  ", "refused_no_match": "REF ",
                "refused_no_result": "ABS ", "unreachable": "DOWN"}[rec["outcome"]]
        bs = f"{rec['bestScore']:.2f}" if rec['bestScore'] is not None else "  -  "
        romaji_note = ""
        if rec["outcome"] in ("refused_no_match", "refused_no_result") and \
                item["titleRomaji"] and \
                (item["titleEnglish"] or "").lower() != (item["titleRomaji"] or "").lower():
            romaji_note = "  [romaji differs]"
        print(f"[{i:>3}/{len(sample)}] t{item['tier']} {flag} {item['queriedTitle'][:34]:34} "
              f"best={bs} {rec['bestSlug'] or '-'}{romaji_note}")
        time.sleep(INTER_SERIES_SLEEP)

    n = len(results)
    n_res = sum(1 for r in results if r["outcome"] == "resolved")
    n_ref_match = sum(1 for r in results if r["outcome"] == "refused_no_match")
    n_ref_absent = sum(1 for r in results if r["outcome"] == "refused_no_result")
    n_down = sum(1 for r in results if r["outcome"] == "unreachable")
    n_ref = n_ref_match + n_ref_absent

    # "refused_no_match" refusals are the ones with a SCORE -- these drive the
    # near-0.8 (tunable) vs near-0.2 (needs alt-title) split.
    scored_refusals = [r for r in results if r["outcome"] == "refused_no_match"]
    ref_scores = [r["bestScore"] for r in scored_refusals]

    # Refusal split: near-0.8 (tunable by threshold) vs near-0.2 (romaji/English, needs
    # alternate-title data). 0.5 is the natural midpoint between 0.8 floor and the 0.2
    # band where romaji-vs-English lives.
    near_threshold = [s for s in ref_scores if s >= 0.5]
    near_zero = [s for s in ref_scores if s < 0.5]

    # "Obvious correct candidate" = a SCORED refusal (refused_no_match) whose best slug
    # scored > 0 -- i.e. WeebCentral returned a real candidate, just below threshold. That
    # is the set a stronger signal (chapter count, alternate titles) COULD confirm. We do
    # NOT use a model judgement (no LLM in the data path).
    obvious_candidate = [r for r in scored_refusals if r["bestScore"] > 0.0]

    # Distribution histogram of refusal scores (0.1 buckets).
    hist = Counter()
    for s in ref_scores:
        hist[f"{int(s * 10) / 10:.1f}"] += 1

    report = {
        "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "purpose": "Identity-resolution failure rate of weebcentral_client.resolve() "
                   "across a popularity-stratified MAL manga sample.",
        "sampleSource": str(MAL_DB),
        "sampleSize": n,
        "tierStratification": f"{N_TIERS} member tiers x ~{PER_TIER} = {n} (type='Manga' only)",
        "titleFieldQueried": "title_english || title (matches Colosseum app read shape)",
        "exclusions": excluded_note,
        "matchThreshold": wc.MATCH_THRESHOLD,
        "summary": {
            "resolved": n_res, "resolvedPercent": round(n_res / n * 100, 1),
            "refused_total": n_ref, "refusedPercent": round(n_ref / n * 100, 1),
            "refused_no_match": n_ref_match,
            "refused_no_matchPercent": round(n_ref_match / n * 100, 1),
            "refused_no_match_definition": "WeebCentral returned candidates but the best scored "
                "< 0.8 -- the threshold / romaji-vs-English question.",
            "refused_no_result": n_ref_absent,
            "refused_no_resultPercent": round(n_ref_absent / n * 100, 1),
            "refused_no_result_definition": "WeebCentral's search returned ZERO candidates for "
                "the query -- genuinely absent, or the query needs the romaji title.",
            "unreachable": n_down, "unreachablePercent": round(n_down / n * 100, 1),
        },
        "refusalAnalysis": {
            "scoredRefusals": len(scored_refusals),
            "obviousCorrectCandidateAvailable": len(obvious_candidate),
            "obviousCorrectCandidatePercent": (
                round(len(obvious_candidate) / len(scored_refusals) * 100, 1)
                if scored_refusals else 0.0),
            "obviousCandidateDefinition": "a refused_no_match whose best WeebCentral candidate "
                "scored > 0.0 (a real candidate existed, just below threshold -- confirmable by "
                "a stronger signal like chapter count or alternate titles; NOT a model judgement).",
            "nearThreshold_count": len(near_threshold),
            "nearThreshold_definition": "best score >= 0.5 (clustered near the 0.8 floor -- a "
                "THRESHOLD question, tunable by lowering MATCH_THRESHOLD).",
            "nearZero_count": len(near_zero),
            "nearZero_definition": "best score < 0.5 (romaji-vs-English territory -- no string "
                "comparison solves this; needs alternate-title data).",
            "scoreHistogram": dict(sorted(hist.items())),
            "scoreBands": {
                "0.0-0.2": len([s for s in ref_scores if s <= 0.2]),
                "0.2-0.4": len([s for s in ref_scores if 0.2 < s <= 0.4]),
                "0.4-0.5": len([s for s in ref_scores if 0.4 < s <= 0.5]),
                "0.5-0.7": len([s for s in ref_scores if 0.5 < s <= 0.7]),
                "0.7-0.8": len([s for s in ref_scores if 0.7 < s < 0.8]),
            },
        },
        "perSeries": results,
    }

    REPORTS.mkdir(exist_ok=True)
    out_path = REPORTS / "identity_rate.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 72)
    print("TASK 9 -- identity-resolution failure rate")
    print("=" * 72)
    print(f"Sample:                  {n} series ({N_TIERS} member tiers)")
    print(f"  resolved:              {n_res} ({n_res/n*100:.1f}%)")
    print(f"  refused (total):       {n_ref} ({n_ref/n*100:.1f}%)")
    print(f"    refused_no_match:    {n_ref_match} ({n_ref_match/n*100:.1f}%)  <- scored refusals")
    print(f"    refused_no_result:   {n_ref_absent} ({n_ref_absent/n*100:.1f}%)  <- search empty")
    print(f"  unreachable:           {n_down} ({n_down/n*100:.1f}%)")
    print()
    print(f"Of {len(scored_refusals)} scored refusals (refused_no_match):")
    print(f"  obvious-correct-candidate (>0.0 score): {len(obvious_candidate)} "
          f"({(len(obvious_candidate)/len(scored_refusals)*100 if scored_refusals else 0):.1f}%)")
    print(f"  near-threshold (>=0.5, TUNABLE):       {len(near_threshold)}")
    print(f"  near-zero (<0.5, needs alt-title):     {len(near_zero)}")
    print("  refusal score histogram:")
    for band, c in report["refusalAnalysis"]["scoreBands"].items():
        print(f"    {band:>7}: {c}")
    print()
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
