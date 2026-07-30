"""WeebCentral clients: series resolution + chapter-list fetch.

TWO functions:

  - resolve(title): series ULID + slug for a title, or (None, None) when WeebCentral does not
    carry the series. The match is VERIFIED by string similarity (see _verify_match), not trusted
    from the search endpoint's first hit. A title WeebCentral does not carry must return None --
    never a different series that happens to share a word. (Added 2026-07-30 after the
    "Beet the Vandel Buster" -> "Buster-Keel" mis-resolution: records are KEYED by WeebCentral
    id, so a wrong-series match would write one manga's volumes into another manga's record --
    wrong data on the wrong series, passing every structural gate because the numbers are
    self-consistent. That is the silent-wrong class this check exists to refuse.)

  - fetch_chapter_list(sid): the raw HTML of WeebCentral's full-chapter-list fragment for a
    series, or None when the series has no servable list. Endpoint discovered 2026-07-30:
    GET /series/{sid}/full-chapter-list with the HX-Request: true header and NO slug in the path
    (including the slug returns a 404 page). The fragment is htmx-served and large (1-4 MB);
    callers parse it. This repo previously had no WeebCentral chapter-list path at all.
"""
import difflib
import re

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
# WeebCentral series ids are 26-char Crockford-base32 ULIDs, e.g. 01J76XY7E9FNDZ1DBBM6PBJPFK.
# The slug is the trailing path segment, hyphen-separated title words.
SERIES_RE = re.compile(r"weebcentral\.com/series/([0-9A-Z]{26})/([^\"'/?]+)")

# Similarity floor for accepting a search hit as the requested series. Chosen empirically against
# the existing seed corpus and known wrong-series traps (2026-07-30):
#   - Every existing seed record resolves at >= 0.848 (lowest: "My Hero Academia" ->
#     "my-hero-academia-color" at 0.848, a legitimate -color suffix).
#   - Known wrong-series matches all fall below 0.8: "Beet the Vandel Buster" -> "Buster-Keel"
#     (0.414), "Vinland Saga" -> "Sand-Land" (0.526), "Naruto" -> "Boruto" (0.667),
#     "Bleach" -> "Bleach-Black" (0.706).
# 0.8 is the floor that passes every known-good seed while rejecting every known-bad match.
# It does reject legitimate-but-string-dissimilar matches (e.g. an English title vs its
# romanized-Japanese original, like "Attack on Titan" vs "Shingeki-no-Kyojin" at 0.207) -- those
# are not string-similar and need a title-alias resolution path, which is out of scope here.
# Refusing such a match returns None, which is the SAFE outcome (no wrong-series record written).
MATCH_THRESHOLD = 0.8

# WeebCentral's full-chapter-list is an htmx fragment served at this path. The {sid} is the
# series ULID; NO slug in the path (with-slug returns a 404 page). Requires the HX-Request header.
CHAPTER_LIST_URL = "https://weebcentral.com/series/{sid}/full-chapter-list"
CHAPTER_LIST_HEADERS = {"User-Agent": UA, "HX-Request": "true"}
CHAPTER_LIST_TIMEOUT = 45


def _normalize(s):
    """Lowercase ASCII alphanumerics only -- the same normalisation comick_client._norm uses, so
    title/slug comparison is consistent across the two sources. NOT str.isalnum() (keeps Unicode)."""
    return "".join(ch for ch in str(s).lower() if ("a" <= ch <= "z") or ("0" <= ch <= "9"))


def _verify_match(requested_title, candidate_slug):
    """Similarity ratio between a requested title and a candidate WeebCentral slug, on normalised
    forms. Returns a float in [0, 1]; >= MATCH_THRESHOLD is accepted as the same series.

    The slug's hyphens are WeebCentral's word separators, equivalent to spaces in the title, so
    both are normalised to a flat alphanumeric string before comparison -- "Vinland-Saga" and
    "Vinland Saga" both become "vinlandsaga" and match at 1.0.
    """
    a = _normalize(requested_title)
    b = _normalize(candidate_slug)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def parse_series_id(html):
    """First series result in a WeebCentral /search/simple response -> (ulid, slug).

    DEPRECATED for direct use: this returns the FIRST regex hit with no title verification, which
    is the source of the wrong-series bug. Use parse_all_series_ids + resolve instead. Retained
    for backwards compatibility and for tests of the raw-parse layer.
    """
    m = SERIES_RE.search(html)
    return (m.group(1), m.group(2)) if m else (None, None)


def parse_all_series_ids(html):
    """ALL series results in a WeebCentral /search/simple response -> list of (ulid, slug).

    WeebCentral's search is fuzzy: "Vinland Saga" returns both Vinland-Saga AND Sand-Land;
    "Beet the Vandel Buster" returns Buster-Keel. The caller must verify which (if any) is the
    requested series via _verify_match. Ordered as WeebCentral returns them (best-rank first).
    """
    return SERIES_RE.findall(html)


def resolve(title):
    """Resolve a title to its WeebCentral (series_id, slug), or (None, None).

    Fetches the search results, then verifies each candidate against the requested title by
    string similarity. Returns the best-scoring candidate IF it clears MATCH_THRESHOLD, else
    (None, None). A title WeebCentral does not carry, or carries only under a dissimilar slug,
    returns (None, None) -- never a wrong-series match.

    Why best-of-above-threshold rather than first-hit: WeebCentral ranks fuzzy matches and the
    first hit is not always the requested series (Sand-Land can rank alongside Vinland-Saga for
    a "Vinland Saga" query). Taking the highest-similarity candidate above the floor is both
    precise (rejects dissimilar wrong-series) and tolerant (handles -color / -suffix slugs).
    """
    r = requests.post("https://weebcentral.com/search/simple",
                      params={"location": "main"}, data={"text": title},
                      headers={"User-Agent": UA, "HX-Request": "true"}, timeout=30)
    r.raise_for_status()
    best_sid, best_slug, best_score = None, None, 0.0
    for sid, slug in parse_all_series_ids(r.text):
        score = _verify_match(title, slug)
        if score > best_score:
            best_sid, best_slug, best_score = sid, slug, score
    if best_score >= MATCH_THRESHOLD:
        return best_sid, best_slug
    return None, None


def fetch_chapter_list(series_id):
    """Raw HTML of WeebCentral's full-chapter-list fragment for a series, or None.

    Returns None when the series has no servable list (404 page or request failure). The fragment
    is htmx-served (hence the HX-Request header) and the path takes the series ULID with NO slug
    -- a slug in the path returns a 404 page that also comes back HTTP 200, so we detect the 404
    by content rather than status code. Callers parse chapter numbers/links out of the returned
    HTML; the markup varies across series (some use 'Chapter N' text, others embed numbers in
    sibling elements), so a caller that cannot extract numbers must treat that series as
    UNTESTABLE rather than substituting a link count for a maximum.
    """
    try:
        r = requests.get(CHAPTER_LIST_URL.format(sid=series_id),
                         headers=CHAPTER_LIST_HEADERS, timeout=CHAPTER_LIST_TIMEOUT)
    except requests.RequestException:
        return None
    # WeebCentral serves its 404 page at HTTP 200; detect by the canonical link / title markers.
    if "weebcentral.com/404" in r.text[:2000] or ("Page not found" in r.text[:2000] and "404" in r.text[:2000]):
        return None
    return r.text


def max_chapter_served(series_id):
    """Highest WHOLE chapter number WeebCentral serves for a series, or None.

    None means: the series has no servable list, OR the list's markup does not expose chapter
    numbers in the 'Chapter N' form this parser looks for. In the latter case the series is
    UNTESTABLE by this function -- a caller must not substitute a link count for a maximum.

    Side chapters (N.5) are ignored: only whole-numbered 'Chapter N' tokens count, because volume
    boundaries are defined on whole chapters.
    """
    html = fetch_chapter_list(series_id)
    if html is None:
        return None
    nums = []
    for m in re.findall(r"Chapter\s+(\d+(?:\.\d+)?)", html):
        try:
            f = float(m)
        except ValueError:
            continue
        if f == int(f):  # whole chapter only
            nums.append(int(f))
    return max(nums) if nums else None
