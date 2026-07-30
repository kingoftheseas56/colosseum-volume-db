"""TASK 11 - COMPUTE THE INTERSECTION (zero network calls).

Both lists are on disk:
  - reports/weebcentral_catalogue.json   10,600 {weebcentralId, slug}  (the reader side)
  - cache/wikipedia_pages.json            4,245 page titles              (the data-source side)

The harvestable population = series Wikipedia documents AND Colosseum can open = where they
overlap. This script joins them and reports THREE numbers, not one:

  1. CONFIDENT   - exact match on canonical form (lowercase, alphanumerics only, Wikipedia-side
                   'List of '/' chapters'/' volumes' stripped, parenthetical disambiguation
                   stripped). Score = 1.0. This is the go/no-go number.
  2. AMBIGUOUS   - not exact, but SequenceMatcher ratio >= AMBIGUOUS_THRESHOLD (0.85). These are
                   near-threshold candidates a human must eyeball -- they are NOT folded into the
                   confident count and NOT into no-match. The Kanon->Kanokon risk lives here.
  3. NO-MATCH    - ratio < AMBIGUOUS_THRESHOLD (or no candidate in the block). No data source
                   overlap found for this series.

Every match (confident + ambiguous) is recorded with BOTH raw strings + the score, so a human can
audit. No-match records the best candidate + score it COULD find, for the same audit purpose.

The matching is STRICT: exact canonical equality is the only path to 'confident'. Nothing is
loosened, abbreviated, or substring-matched to inflate the count.

Writes reports/harvestable_population.json and prints the summary.
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CATALOGUE_PATH = REPO / "reports" / "weebcentral_catalogue.json"
WIKI_PATH = REPO / "cache" / "wikipedia_pages.json"
OUT_PATH = REPO / "reports" / "harvestable_population.json"

# A match below this is no-match; at-or-above but not exact is ambiguous. 0.85 is deliberately
# HIGH -- higher than weebcentral_client.MATCH_THRESHOLD (0.8) -- because we have no human in the
# loop to veto a false accept, and the Kanon->Kanokon (0.83) wrong-series accept proved 0.8 leaks.
AMBIGUOUS_THRESHOLD = 0.85

# Parenthetical disambiguation: "Berserk (manga)", "Tokyo Ghoul (manga)" -> drop the qualifier.
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*")
# "List of X chapters" -> "X". Handles "chapters" and "volumes" suffixes (both carry volume data).
_LIST_PREFIX_RE = re.compile(r"^list of\s+", re.IGNORECASE)
_VOL_SUFFIX_RE = re.compile(r"\s+(chapters|volumes)\s*$", re.IGNORECASE)
# Keep only lowercase alphanumerics for the canonical comparable form.
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def canonical(raw):
    """Reduce a raw title OR slug to a canonical comparable form.

    Strips parenthetical disambiguation, 'List of ' prefix, ' chapters'/' volumes' suffix, then
    lowercases and drops every non-alphanumeric char. Both Wikipedia titles and WeebCentral slugs
    pass through the SAME function so the comparison is apples-to-apples.

    Examples:
      'List of Vinland Saga chapters' -> 'vinlandsaga'
      'Vinland Saga'                   -> 'vinlandsaga'
      'Ao-No-Exorcist'                 -> 'aonoexorcist'
      'Berserk (manga)'                -> 'berserk'
    """
    s = _PAREN_RE.sub(" ", raw)
    s = _LIST_PREFIX_RE.sub("", s)
    s = _VOL_SUFFIX_RE.sub("", s)
    s = s.lower()
    s = _NON_ALNUM_RE.sub("", s)
    return s


def block_key(canonical_form):
    """First 2 alphanumeric chars -> blocking key for the fuzzy pass.

    Keeps the fuzzy comparison set small (~tens of catalogue entries per block) so the whole join
    is fast without an all-pairs blowup. Legit matches share a prefix after canonicalization;
    aliasing (Blue Exorcist vs Ao no Exorcist) correctly lands in different blocks -> no-match,
    which is the strict-and-correct call."""
    return canonical_form[:2]


def ratio(a, b):
    return SequenceMatcher(None, a, b).ratio()


def main():
    catalogue = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    wiki_titles = json.loads(WIKI_PATH.read_text(encoding="utf-8"))

    # --- Build catalogue index: canonical -> list of (id, slug); block -> set of canonicals ---
    canon_to_cat = {}   # canonical -> [(weebcentralId, slug), ...]
    block_to_canons = {}  # block_key -> set of canonical forms
    for entry in catalogue:
        slug = entry["slug"]
        c = canonical(slug)
        canon_to_cat.setdefault(c, []).append((entry["weebcentralId"], slug))
        block_to_canons.setdefault(block_key(c), set()).add(c)

    confident = []
    ambiguous = []
    no_match = []

    for raw_wiki in wiki_titles:
        cw = canonical(raw_wiki)
        if not cw:
            no_match.append({"rawWikipedia": raw_wiki, "canonical": "",
                             "bestCandidateSlug": None, "bestCandidateId": None,
                             "score": 0.0, "reason": "empty canonical form"})
            continue

        # --- Pass 1: exact canonical match -> confident ---
        exact_hits = canon_to_cat.get(cw)
        if exact_hits:
            if len(exact_hits) == 1:
                wid, slug = exact_hits[0]
                confident.append({"rawWikipedia": raw_wiki, "canonical": cw,
                                  "matchedSlug": slug, "weebcentralId": wid, "score": 1.0})
            else:
                # Multiple catalogue entries share a canonical form -> ambiguous (cannot pick one).
                ambiguous.append({
                    "rawWikipedia": raw_wiki, "canonical": cw, "score": 1.0,
                    "reason": f"{len(exact_hits)} catalogue entries share canonical form",
                    "candidates": [{"slug": s, "weebcentralId": i} for i, s in exact_hits],
                })
            continue

        # --- Pass 2: fuzzy within block -> ambiguous or no-match ---
        blk = block_key(cw)
        candidates = block_to_canons.get(blk, set())
        best_canon, best_ratio = None, 0.0
        for cc in candidates:
            r = ratio(cw, cc)
            if r > best_ratio:
                best_ratio, best_canon = r, cc
        if best_canon is not None and best_ratio >= AMBIGUOUS_THRESHOLD:
            # Pick the first catalogue entry under that canonical for the audit record.
            wid, slug = canon_to_cat[best_canon][0]
            ambiguous.append({"rawWikipedia": raw_wiki, "canonical": cw,
                              "bestCandidateSlug": slug, "weebcentralId": wid,
                              "score": round(best_ratio, 4),
                              "bestCandidateCanonical": best_canon})
        else:
            best_slug, best_id = None, None
            if best_canon is not None:
                best_id, best_slug = canon_to_cat[best_canon][0]
            no_match.append({"rawWikipedia": raw_wiki, "canonical": cw,
                             "bestCandidateSlug": best_slug, "bestCandidateId": best_id,
                             "score": round(best_ratio, 4) if best_canon else 0.0})

    # --- Deduplicate confident to UNIQUE weebcentral series ---
    # A series with N arc-split Wikipedia pages (e.g. One Piece: 6 "List of ... chapters (X-Y)"
    # pages, Hajime no Ippo: 7) appears N times in the raw confident list, all mapping to ONE
    # WeebCentral id. The harvestable POPULATION is unique series, so the go/no-go number is the
    # unique count, not the raw match-record count. We keep both for transparency.
    confident_ids = {m["weebcentralId"] for m in confident}
    n_confident_unique = len(confident_ids)

    # --- db/ intersection: how many confident series are ALREADY in db/ (fence-excluded)? ---
    # A series already in db/ with qualified:true is never re-harvested (the fence at
    # fallback.py:295). So the NEW harvestable population = confident_unique MINUS db ids.
    import glob as _glob
    import os as _os
    db_ids = set()
    for _f in _glob.glob(str(REPO / "db" / "*.json")):
        db_ids.add(_os.path.basename(_f).replace(".json", ""))
    already_in_db = confident_ids & db_ids
    n_new_harvestable = len(confident_ids - db_ids)

    # --- Fandom side: for the confident WeebCentral matches, how many ALSO survive the DNS
    #     63-octet label cap (so Fandom is a REACHABLE fallback source too)? This is a zero-network
    #     computation: we slugify the matched slug the same way fandom_source does. We CANNOT
    #     enumerate Fandom wikis offline (no Fandom sitemap on disk), so this is 'potential Fandom
    #     reachability', not 'confirmed Fandom wiki exists'. Reported separately, NOT merged.
    from comick_volume_db import fandom_source as fs
    fandom_reachable_confident = 0
    fandom_blocked_confident = 0
    seen_fandom = set()
    for m in confident:
        if m["weebcentralId"] in seen_fandom:
            continue  # count each UNIQUE series once
        seen_fandom.add(m["weebcentralId"])
        # fandom_source derives the host from the SERIES TITLE; the closest title we have is the
        # WeebCentral slug with hyphens->spaces. This mirrors how harvest_qualified would call it.
        title = m["matchedSlug"].replace("-", " ").strip()
        if fs._host_for(title) is not None:
            fandom_reachable_confident += 1
        else:
            fandom_blocked_confident += 1

    report = {
        "task": "Task 11 - compute the harvestable intersection (zero network calls)",
        "inputs": {
            "weebcentralCatalogue": str(CATALOGUE_PATH.relative_to(REPO)),
            "catalogueCount": len(catalogue),
            "wikipediaCache": str(WIKI_PATH.relative_to(REPO)),
            "wikipediaCount": len(wiki_titles),
        },
        "matchingRules": {
            "canonicalForm": "lowercase; strip parenthetical disambiguation; strip 'List of ' prefix; "
                             "strip ' chapters'/' volumes' suffix; drop all non-alphanumerics",
            "confident": "exact match on canonical form (score = 1.0), single catalogue entry",
            "ambiguous": f"SequenceMatcher ratio >= {AMBIGUOUS_THRESHOLD} (but not exact), "
                         "OR multiple catalogue entries share the canonical form",
            "noMatch": f"ratio < {AMBIGUOUS_THRESHOLD} or no candidate in the 2-char block",
            "blocking": "first 2 alphanumeric chars of canonical form (fuzzy pass only)",
            "strictnessNote": "Exact canonical equality is the ONLY path to confident. Nothing is "
                              "loosened, abbreviated, or substring-matched to inflate the count.",
        },
        "summary": {
            "confident": len(confident),
            "confidentUniqueSeries": n_confident_unique,
            "newHarvestableUniqueSeries": n_new_harvestable,
            "alreadyInDb": len(already_in_db),
            "ambiguous": len(ambiguous),
            "noMatch": len(no_match),
            "deduplicationNote": (
                f"{len(confident)} confident match-records collapse to {n_confident_unique} unique "
                "WeebCentral series because long series have multiple arc-split Wikipedia pages "
                "(e.g. One Piece: 6 'List of ... chapters (X-Y)' pages, Hajime no Ippo: 7) that "
                "all transclude the same template and match the same id. The harvestable POPULATION "
                "is unique series; the go/no-go number is confidentUniqueSeries."
            ),
        },
        "fandomSide": {
            "note": "Potential Fandom reachability for the CONFIDENT UNIQUE WeebCentral matches only. "
                    "Computed offline: slugify the matched slug (hyphens->spaces) and check the "
                    "DNS 63-octet label cap. NOT a confirmed-wiki count (no Fandom sitemap on disk); "
                    "a reachable host MIGHT still have no wiki. Reported separately, NOT merged.",
            "fandomReachable": fandom_reachable_confident,
            "fandomBlockedByDnsCap": fandom_blocked_confident,
        },
        "confidentMatches": confident,
        "ambiguousMatches": ambiguous,
        "noMatches": no_match,
    }

    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("TASK 11 - COMPUTE THE INTERSECTION (zero network calls)")
    print(f"  catalogue:  {len(catalogue)} series  ({CATALOGUE_PATH.relative_to(REPO)})")
    print(f"  wikipedia:  {len(wiki_titles)} pages ({WIKI_PATH.relative_to(REPO)})")
    print()
    print("THREE NUMBERS (the go/no-go is the first):")
    print(f"  CONFIDENT (exact canonical match):  {len(confident)} match-records")
    print(f"    -> unique WeebCentral series:     {n_confident_unique}")
    print(f"    -> already in db/ (fence-excluded): {len(already_in_db)}")
    print(f"    -> NEW harvestable unique series:   {n_new_harvestable}")
    print(f"  AMBIGUOUS (ratio >= {AMBIGUOUS_THRESHOLD}, not exact):  {len(ambiguous)}")
    print(f"  NO-MATCH (ratio < {AMBIGUOUS_THRESHOLD}):             {len(no_match)}")
    print()
    print("FANDOM SIDE (separate, not merged; potential reachability, not confirmed wikis):")
    print(f"  of the {n_confident_unique} unique confident matches, Fandom host fits DNS cap: "
          f"{fandom_reachable_confident}")
    print(f"  of the {n_confident_unique} unique confident matches, blocked by DNS cap:        "
          f"{fandom_blocked_confident}")
    print()
    print(f"wrote {OUT_PATH.relative_to(REPO)}")
    print()
    print("CONFIDENT MATCHES (full audit list):")
    for m in confident:
        print(f"  {m['rawWikipedia']!r:45s} -> {m['matchedSlug']!r:30s} score={m['score']}")
    print()
    print("AMBIGUOUS MATCHES (human must eyeball):")
    for m in ambiguous:
        if "reason" in m:
            print(f"  {m['rawWikipedia']!r:45s} score={m['score']}  {m['reason']}")
        else:
            print(f"  {m['rawWikipedia']!r:45s} -> {m['bestCandidateSlug']!r:30s} "
                  f"score={m['score']}")


if __name__ == "__main__":
    main()
