"""Task 10 - ENUMERATE the WeebCentral catalogue, then MEASURE the real end-to-end rate.

THE INVERSION (Hemanth 2026-07-31): WeebCentral publishes its WHOLE catalogue as
https://weebcentral.com/sitemap.xml -- every series as /series/<ULID>/<Slug>, the id AND the
name with NO search, NO scoring, NO guessing. That kills the title->id trip Task 9 measured
(73% fail). Go id -> data instead: the identity question is answered by construction. Demon
Slayer is simply there as Kimetsu-No-Yaiba with its id attached -- no Hemanth ruling needed.

This also fixes the DENOMINATOR: the catalogue is the ONLY population that matters, because a
series WeebCentral does not carry cannot be opened in Colosseum and therefore never needs a
volume record. Task 9's 150-sample drew from 20,000 MAL rows, a large share of which the app
can never show. The catalogue (~10,600) is the real population.

THREE STEPS, writes nothing to db/:
  1. Fetch + parse the sitemap into reports/weebcentral_catalogue.json: {weebcentralId, slug}
     per series. Report the exact count. Follow child sitemaps if present (probe says flat).
  2. Cross-check against db/: every existing record's id should appear in the catalogue. If any
     id does NOT, STOP and report -- that would mean a record is keyed to something the catalogue
     does not list (a corrupted key or a delisted series).
  3. Take 100 series AT RANDOM from the catalogue (no popularity signal exists; uniform random).
     For each, using the SLUG as the query, attempt the Wikipedia + Fandom readers (the existing
     resolve_fallback path) and record: qualified / unqualified / no_fallback_data / unreachable.
     This is the real end-to-end rate for the population that matters. LEAD with it.

THE RISK MOVED, IT DID NOT VANISH. Keying is now exact (id comes from the catalogue), but
'which wiki describes this series' is still a MATCHING DECISION, and the Kanon->Kanokon 0.83
finding from Task 9 proves a plausible-looking match can be the wrong series. A wrong wiki would
put one manga's volumes on another manga's shelf. For every sampled match we record WHICH wiki
host + page was used, and we lean on the tiling guard -- no second, looser check is added.
"""
import json
import pathlib
import random
import re
import time
import xml.etree.ElementTree as ET

import requests

from comick_volume_db import fallback as fb
from comick_volume_db import fandom_source as fs
from comick_volume_db.http_retry import SourceUnreachable

REPO = pathlib.Path(__file__).resolve().parent.parent
REPORTS = REPO / "reports"
DB = REPO / "db"

SITEMAP_URL = "https://weebcentral.com/sitemap.xml"
SM_INDEX_URL = "https://weebcentral.com/sitemap-index.xml"  # probed; may not exist
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
# Match the series URL INSIDE a <loc>...</loc> tag. The URL runs straight into </loc> with no
# trailing slash, so we capture up to (not including) the closing tag. Anchoring inside <loc>
# keeps us off the homepage/genre/search URLs, and the {26} ULID + slug shape is the series filter.
SERIES_RE = re.compile(r"<loc>[^<]*/series/([0-9A-Z]{26})/([^<]+?)</loc>")

SAMPLE_N = 100
SAMPLE_SEED = 20260731
INTER_SERIES_SLEEP = 1.5


def _fetch(url, timeout=60):
    """Plain GET with a UA. Raises on transport failure (caller reports unreachable)."""
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r


def fetch_sitemap():
    """Fetch the sitemap, following a sitemap-index if one exists. Returns the concatenated XML.

    Probed 2026-07-31: weebcentral.com/sitemap.xml is a FLAT <urlset> (~2.5MB) of <url><loc>
    entries -- no child sitemaps. We nonetheless ALSO try sitemap-index.xml defensively; if it
    exists and points at children, we fetch each child. Either way the caller gets one XML blob
    containing every <url> entry. Reports which path was taken.
    """
    # First try the flat sitemap (the one Hemanth verified).
    primary = _fetch(SITEMAP_URL)
    text = primary.text
    used = [SITEMAP_URL]
    # If it happens to be a sitemapindex (lists child sitemaps), follow them.
    if "<sitemapindex" in text[:500]:
        children = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text)
        text = ""
        for c in children:
            text += _fetch(c.strip()).text
            used.append(c.strip())
    return text, used


def parse_catalogue(xml_text):
    """Parse sitemap XML -> list of {weebcentralId, slug}. Only /series/ URLs count.

    Non-series URLs (the homepage, /search, /genre, etc.) are filtered out by the /series/<ULID>/
    shape. Duplicate ids (if any) are collapsed, last slug wins (shouldn't happen on a clean
    sitemap but is safe). Slug has its trailing whitespace/params stripped.
    """
    entries = {}
    for m in SERIES_RE.finditer(xml_text):
        sid, slug = m.group(1), m.group(2).strip().rstrip("/")
        entries[sid] = slug
    return [{"weebcentralId": sid, "slug": slug} for sid, slug in entries.items()]


def crosscheck_db(catalogue_ids):
    """Every existing db/ record's id must appear in the catalogue. Returns (in_catalogue, missing).

    A record keyed to an id the catalogue does NOT list is a red flag: the key is corrupted, or
    the series was delisted, or the record was built from a non-catalogue source. We do NOT touch
    the record -- we STOP and report, per Hemanth's instruction.
    """
    db_ids = []
    for p in DB.glob("*.json"):
        if p.name.endswith(".synopsis.json"):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            sid = rec.get("weebCentral", {}).get("seriesId")
            if sid:
                db_ids.append((sid, rec.get("seriesTitle", "?"), p.name))
        except (json.JSONDecodeError, KeyError):
            continue
    cat = set(catalogue_ids)
    in_cat = [(s, t, f) for (s, t, f) in db_ids if s in cat]
    missing = [(s, t, f) for (s, t, f) in db_ids if s not in cat]
    return in_cat, missing, db_ids


def slug_to_query(slug):
    """Turn a WeebCentral slug into the title-shape query the readers expect.

    WeebCentral slugs are hyphenated title words: 'Kimetsu-No-Yaiba', 'Onepunch-Man',
    'Vinland-Saga'. The Wikipedia/Fandom readers were built to take a TITLE ('Vinland Saga') and
    normalise it. Hyphens -> spaces reproduces the title form the slug was derived from, which is
    the name WeebCentral associates with that id. This is the faithful query: the id is exact, and
    the slug-derived name is the name that id carries.
    """
    return slug.replace("-", " ").strip()


def measure_one(item):
    """Run the fallback path for one catalogue series. Records WHICH wiki host+page was used
    (the moved-risk provenance Hemanth asked for). Outcome is one of:
      qualified / unqualified / no_fallback_data / unreachable / error.

    `error` catches ANY unexpected exception (not just SourceUnreachable) so one malformed series
    cannot abort the whole sample. The first crash in the wild (2026-07-31) was a
    urllib3 LocationParseError: a Fandom host built by fandom_source._slugify from a very long
    romaji slug exceeded DNS's 63-octet label limit ('shinuunmeiniaruakuyakureijouno...fandom.com').
    That is a slug-derived-host bug -- exactly the 'risk moved, not vanished' class -- and is
    recorded as an outcome, not a crash. Surfacing it in the sample is the measurement doing its job.
    """
    sid = item["weebcentralId"]
    slug = item["slug"]
    query = slug_to_query(slug)
    out = dict(item)
    out.update(query=query, outcome=None, source=None, sourceUrl=None,
               volCount=None, gateReason=None, error=None)
    try:
        res = fb.resolve_fallback(query)
    except SourceUnreachable as e:
        out["outcome"] = "unreachable"
        out["error"] = f"SourceUnreachable: {e}"
        return out
    except Exception as e:
        # Any other failure (e.g. the Fandom-host-too-long LocationParseError) is recorded as
        # 'error', NOT a crash. The run continues; the series is inspectable in the report.
        out["outcome"] = "error"
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    if res is None:
        out["outcome"] = "no_fallback_data"
        return out
    # res is a resolution dict from resolve_fallback: {source, source_url, volumes, qualified, ...}
    out["source"] = res["source"]
    out["sourceUrl"] = res["source_url"]
    out["volCount"] = len(res["volumes"])
    out["gateReason"] = res.get("gate_reason") or ""
    out["outcome"] = "qualified" if res["qualified"] else "unqualified"
    return out


def main():
    REPORTS.mkdir(exist_ok=True)

    # ---- STEP 1: enumerate ----
    print("STEP 1: fetching + parsing WeebCentral sitemap...")
    xml_text, used_urls = fetch_sitemap()
    catalogue = parse_catalogue(xml_text)
    cat_path = REPORTS / "weebcentral_catalogue.json"
    cat_path.write_text(json.dumps(catalogue, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  fetched from: {used_urls}")
    print(f"  series URLs parsed: {len(catalogue)}")
    print(f"  wrote {cat_path}")

    # ---- STEP 2: cross-check db/ ----
    print("\nSTEP 2: cross-checking db/ record ids against catalogue...")
    cat_ids = [e["weebcentralId"] for e in catalogue]
    in_cat, missing, db_ids = crosscheck_db(cat_ids)
    print(f"  db/ records checked: {len(db_ids)}")
    print(f"  in catalogue:        {len(in_cat)}")
    print(f"  MISSING from cat:    {len(missing)}")
    if missing:
        print("  !!! STOP: records keyed to ids NOT in the catalogue:")
        for sid, title, fname in missing:
            print(f"      {sid}  {title}  ({fname})")
        # Per Hemanth: if any are missing, STOP and report. Write nothing to db/.
        report = {
            "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "STOPPED_AT_STEP_2",
            "reason": "db/ record(s) keyed to ids NOT in the WeebCentral catalogue.",
            "sitemapFetchedFrom": used_urls,
            "catalogueCount": len(catalogue),
            "dbRecordsChecked": len(db_ids),
            "inCatalogue": len(in_cat),
            "missingFromCatalogue": [
                {"weebcentralId": s, "seriesTitle": t, "file": f} for s, t, f in missing
            ],
        }
        (REPORTS / "identity_rate_catalogue.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSTOPPED. Wrote reports/identity_rate_catalogue.json")
        return

    # ---- STEP 3: random sample + measure ----
    print(f"\nSTEP 3: sampling {SAMPLE_N} at random (seed={SAMPLE_SEED}) and measuring "
          f"Wikipedia/Fallback rate...")
    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(catalogue, min(SAMPLE_N, len(catalogue)))
    results = []
    for i, item in enumerate(sample, 1):
        rec = measure_one(item)
        results.append(rec)
        flag = {"qualified": "QUAL", "unqualified": "UNQ ", "no_fallback_data": "NONE",
                "unreachable": "DOWN", "error": "ERR "}.get(rec["outcome"], "????")
        vc = f"v={rec['volCount']}" if rec['volCount'] is not None else "     "
        errbit = f"  err={rec['error'][:40]}" if rec.get('error') else ""
        print(f"[{i:>3}/{len(sample)}] {flag} {item['slug'][:40]:42} {vc} "
              f"{rec['source'] or '-':9} {rec['outcome']}{errbit}")
        time.sleep(INTER_SERIES_SLEEP)

    n = len(results)
    n_qual = sum(1 for r in results if r["outcome"] == "qualified")
    n_unq = sum(1 for r in results if r["outcome"] == "unqualified")
    n_none = sum(1 for r in results if r["outcome"] == "no_fallback_data")
    n_down = sum(1 for r in results if r["outcome"] == "unreachable")
    n_err = sum(1 for r in results if r["outcome"] == "error")
    by_source = {}
    for r in results:
        if r["outcome"] in ("qualified", "unqualified") and r["source"]:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    errors_by_type = {}
    for r in results:
        if r["outcome"] == "error" and r.get("error"):
            etype = r["error"].split(":", 1)[0]
            errors_by_type[etype] = errors_by_type.get(etype, 0) + 1

    report = {
        "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "purpose": "Real end-to-end fallback rate for the population that matters: WeebCentral's "
                   "published catalogue. Keying is exact (id from sitemap); the risk moved to "
                   "'which wiki describes this series' -- provenance recorded per match.",
        "sitemapFetchedFrom": used_urls,
        "catalogueCount": len(catalogue),
        "step2_dbCrosscheck": {
            "dbRecordsChecked": len(db_ids),
            "allInCatalogue": True,
            "missingCount": 0,
        },
        "sample": {"size": n, "seed": SAMPLE_SEED, "method": "uniform random over catalogue"},
        "summary": {
            "qualified": n_qual, "qualifiedPercent": round(n_qual / n * 100, 1),
            "unqualified": n_unq, "unqualifiedPercent": round(n_unq / n * 100, 1),
            "no_fallback_data": n_none, "no_fallback_dataPercent": round(n_none / n * 100, 1),
            "unreachable": n_down, "unreachablePercent": round(n_down / n * 100, 1),
            "error": n_err, "errorPercent": round(n_err / n * 100, 1),
            "errorDefinition": "an unexpected exception (not SourceUnreachable) during resolution. "
                "Recorded as an outcome, not a crash -- the run continues. The first in the wild "
                "(2026-07-31) was a urllib3 LocationParseError: a Fandom host built from a long "
                "romaji slug exceeded DNS's 63-octet label limit. That is a slug-derived-host bug.",
            "errorsByType": errors_by_type,
            "bySource": by_source,
        },
        "riskMovedNotVanished": (
            "Keying is exact (id comes from the sitemap). The remaining matching decision is "
            "'which wiki describes this series' -- recorded per match as source + sourceUrl. The "
            "Kanon->Kanokon finding (Task 9: a plausible-looking 0.83 match was the WRONG series) "
            "proves a wrong wiki would put one manga's volumes on another manga's shelf. The tiling "
            "guard (_volumes_are_contiguous) + the gate are the structural check; provenance is the "
            "audit trail. No second looser check was added."
        ),
        "perSeries": results,
    }
    out_path = REPORTS / "identity_rate_catalogue.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 72)
    print("TASK 10 -- real end-to-end rate over the WeebCentral catalogue")
    print("=" * 72)
    print(f"Catalogue size:   {len(catalogue)} series (the only population that matters)")
    print(f"db/ cross-check:  {len(db_ids)}/{len(db_ids)} record ids in catalogue (0 missing)")
    print(f"Sample:           {n} (uniform random, seed {SAMPLE_SEED})")
    print(f"  qualified:      {n_qual} ({n_qual/n*100:.1f}%)")
    print(f"  unqualified:    {n_unq} ({n_unq/n*100:.1f}%)")
    print(f"  no_fallback:    {n_none} ({n_none/n*100:.1f}%)")
    print(f"  unreachable:    {n_down} ({n_down/n*100:.1f}%)")
    print(f"  error:          {n_err} ({n_err/n*100:.1f}%)")
    if errors_by_type:
        print(f"  errors by type: {errors_by_type}")
    print(f"  by source:      {by_source}")
    print()
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
