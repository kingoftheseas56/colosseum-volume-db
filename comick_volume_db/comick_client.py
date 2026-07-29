import requests

BASE = "https://api.comick.dev"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}

# SHARED RULE — series resolution. Keep pick_best(), _norm() and SEARCH_LIMIT in step
# with matchKey() and the best-match loop in Colosseum's
# native/engine/ComickCatalogClient.cpp (stepSearch). Three parts, and all three have to
# agree: an 8-candidate window, lowercase-ASCII-alphanumeric normalisation, and an exact
# hit on `title` OR any `md_titles[].title`, else the first result.
#
# This is the step that decides WHICH COMIC gets grouped. A divergence here does not
# produce a different shelf for the same comic — it produces a shelf for a DIFFERENT
# comic depending on whether the series was pre-baked by this batch job or scraped live
# by the app, which is the one failure the whole C++/Python mirror exists to prevent,
# and it sits one layer above where the volume_builder tests can see it.
#
# The md_titles half came FROM the C++ (ported here 2026-07-30, along with the window
# narrowing from 10 to 8) because it is the more forgiving rule for a series whose
# Comick title differs from WeebCentral's spelling. It is INERT on today's corpus and
# that is worth stating plainly: measured 2026-07-30, all 11 seeded series match on
# `title` at result index 0, so title-only picking resolves every one of them
# identically. It is here for parity with the C++ and for the series that isn't in the
# seeds yet — it is not protecting anything now. All 11 published records were rebuilt
# after the change and re-resolved to their existing comickHid.
#
# KNOWN SHARED EDGE, deliberately left alone on both sides so they stay identical: a
# series title with no ASCII alphanumerics at all normalises to "", and an empty want
# would exact-match the first candidate whose names also normalise to "". Unreachable
# from today's seeds (every WeebCentral title is romanised), and fixing it in one
# implementation only would be worse than the edge.
SEARCH_LIMIT = 8


def _norm(s):
    # Lowercase ASCII alphanumerics only. NOT str.isalnum(), which also keeps Unicode
    # letters and digits — the C++ side keeps a-z0-9 and nothing else, and "the same
    # normalisation" has to mean byte-for-byte the same.
    return "".join(ch for ch in str(s).lower() if ("a" <= ch <= "z") or ("0" <= ch <= "9"))


def _names(result):
    """Every name this candidate answers to: its own title plus each md_title."""
    yield result.get("title")
    for alt in result.get("md_titles") or []:
        if isinstance(alt, dict):
            yield alt.get("title")


def pick_best(results, title):
    if not results:
        return None
    want = _norm(title)
    for r in results:
        # `if name` skips a missing title rather than letting str(None) normalise to
        # "none" and match a series actually called "None".
        if any(_norm(name) == want for name in _names(r) if name):
            return r
    return results[0]


def search(title):
    r = requests.get(f"{BASE}/v1.0/search", params={"q": title, "limit": SEARCH_LIMIT},
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
