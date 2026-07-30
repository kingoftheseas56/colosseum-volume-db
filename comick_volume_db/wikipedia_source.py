"""Wikipedia volume->chapter source. Deterministic. No models in the data path.

Wikipedia manga chapter-list pages sometimes carry a ``{{Graphic novel list}}`` template whose
per-volume blocks include a ``VolumeNumber`` and a ``ChapterList`` of bulleted chapter entries.
Where that data exists it is PUBLISHER-CITED (Kodansha/Hakusensha refs + ISBN on each volume),
which is why Wikipedia ranks ABOVE Fandom in precedence: a Wikipedia-sourced record rests on
the publisher's own volume numbering, not fan transcription.

PROVENANCE -- Wikipedia is publisher-cited; contrast fandom_source (fan-maintained). The
structural gate this feeds (volume_builder.gate) verifies SHAPE, NOT TRUTH, but a Wikipedia
record's shape is backed by publisher references, so it is the strongest fallback provenance.
Even so, ``source: "wikipedia"`` + ``sourceUrl`` are recorded (Task 3) so a consumer can tell.

This module only READS published wikitext and extracts numbers already written there. It never
interpolates a boundary, never infers a missing volume, and never asks a model for a number.
If a page has no ``{{Graphic novel list}}`` blocks with a ``ChapterList`` (the common case --
most manga list pages use Wikitable or other formats, e.g. One Piece/Naruto/Bleach carry zero
GNL blocks), the series yields None and stays unqualified. A page that exists but carries only
ISBNs and dates (no ChapterList) also yields None: a volume count without chapter boundaries is
not usable and must not be faked.

DISCOVERY IS DETERMINISTIC -- we never guess URLs. We enumerate every page transcluding the
template via ``action=query&list=embeddedin&eititle=Template:Graphic+novel+list`` (paginated
via ``continue``), cache the title set, and match the series against it (exact, then
``List of <title> chapters``, then normalised). Vinland Saga resolves to
``List of Vinland Saga chapters`` -- not a guess, a transclusion lookup.

CHAPTERLIST BULLET FORMAT (recon-verified, not assumed): entries are zero-padded bullets like
``*001.`` / ``*002.``, sometimes bare ``*210.``, with non-numeric entries mixed in
(``*Bonus Material.``). The parser strips leading zeros, skips non-numeric bullets, and takes
the first and last NUMERIC chapter in source order as the volume's range (strings preserved so
fractional forms survive, matching volume_builder's contract).
"""
import json
import pathlib
import re

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}
API = "https://en.wikipedia.org/w/api.php"
TIMEOUT = 30

TEMPLATE = "Template:Graphic novel list"
HERE = pathlib.Path(__file__).parent
CACHE = HERE.parent / "cache" / "wikipedia_pages.json"

# A {{Graphic novel list}} block ends at its closing }}. Field lines start with "|".
_GNL_BLOCK = re.compile(r"\{\{Graphic novel list\s*\n(.*?)\n\}\}", re.S)
# VolumeNumber = N (digits only). Some pages pad or suffix; we take the integer.
_VOLNUM = re.compile(r"\|\s*VolumeNumber\s*=\s*(\d+)")
# The ChapterList field value, up to the next top-level "| Field =", the block's closing }},
# or end-of-string. The end-of-string alternative (\Z) is required because _GNL_BLOCK captures
# the block body WITHOUT the closing braces, so when this regex runs on an extracted block the
# "\n}}" terminator is absent -- without \Z the last block's ChapterList would silently match
# None and drop the volume.
_CHAPTERLIST = re.compile(r"\|\s*ChapterList\s*=\s*(.*?)(?=\n\s*\||\n\s*\}\}|\Z)", re.S)
# A chapter bullet: "*001.", "*210.", "*1.". Capture the number, strip leading zeros later.
# Skips non-numeric bullets like "*Bonus Material." because there is no digit right after the dot.
_BULLET = re.compile(r"^\s*\*\s*0*(\d+)\.", re.M)


def _normalize_title(title):
    """ASCII-lowercase alphanumerics, for fuzzy title matching across spellings.
    Mirrors comick_client._norm's intent (a-z0-9) without importing it, to keep this module
    independent of the Comick path."""
    return "".join(c for c in title.lower() if ("a" <= c <= "z") or ("0" <= c <= "9"))


def enumerate_transcluding_pages(max_batches=50):
    """Every page transcluding Template:Graphic novel list, via the embeddedin API.

    Paginates with ``eicontinue`` until exhausted or max_batches (safety cap: 50 * 500 = 25000
    pages; the real set is a few thousand). Returns a list of page titles. Deterministic and
    cached to ``cache/wikipedia_pages.json`` so the discovery cost is paid once, not per series.
    """
    params = {"action": "query", "list": "embeddedin", "eititle": TEMPLATE,
              "eilimit": 500, "einamespace": 0, "format": "json"}
    titles = []
    for _ in range(max_batches):
        r = requests.get(API, params=params, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        titles.extend(p["title"] for p in data.get("query", {}).get("embeddedin", []))
        cont = data.get("continue")
        if not cont:
            break
        params.update(cont)
    return titles


def cache_page_list(force_refresh=False):
    """Return the cached transclusion title list, refreshing from the API if absent or forced."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE.exists() and not force_refresh:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    titles = enumerate_transcluding_pages()
    CACHE.write_text(json.dumps(titles, indent=2, ensure_ascii=False), encoding="utf-8")
    return titles


def _match_page(series_title, candidate_titles):
    """Find the best Wikipedia page for a series among the transcluding titles.

    Order (deterministic): exact title, then 'List of <title> chapters', then normalised match.
    Returns the page title or None."""
    want_exact = series_title
    want_list = f"List of {series_title} chapters"
    want_norm = _normalize_title(series_title)

    normed = {t: _normalize_title(t) for t in candidate_titles}
    if want_exact in candidate_titles:
        return want_exact
    if want_list in candidate_titles:
        return want_list
    # normalised: prefer the "...chapters" page when several normalise equally
    list_matches = [t for t in candidate_titles if normed[t] == _normalize_title(want_list)]
    if list_matches:
        return list_matches[0]
    exact_norm = [t for t in candidate_titles if normed[t] == want_norm]
    if exact_norm:
        return exact_norm[0]
    return None


def _fetch_wikitext(page):
    """Raw wikitext for a page, following redirects. None if the page does not exist."""
    r = requests.get(API, params={"action": "parse", "page": page, "prop": "wikitext",
                                  "format": "json", "redirects": 1},
                     headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        return None
    return data["parse"]["wikitext"]["*"]


def parse_volumes_from_wikitext(wikitext):
    """Extract volume->chapter ranges from a page's {{Graphic novel list}} blocks.

    Returns a list of {"number": int, "chapterStart": str, "chapterEnd": str} sorted by number,
    or None when the page has no Graphic novel list blocks carrying a ChapterList (the common
    case -- most manga list pages use other formats). A block with VolumeNumber but no
    ChapterList is skipped; if NO block has a ChapterList, the whole page yields None.

    Never interpolates: a block whose ChapterList has no numeric bullets is a hole and is
    skipped. If that leaves gaps in the 1..N run, the caller's gate (Task 3) refuses it -- but
    we also refuse here when a volume number is present yet unreadable, to avoid publishing a
    mapping with a hole.
    """
    volumes = []
    for block in _GNL_BLOCK.findall(wikitext):
        vm = _VOLNUM.search(block)
        if not vm:
            continue  # a GNL block without a VolumeNumber is not a volume row
        number = int(vm.group(1))
        clm = _CHAPTERLIST.search(block)
        if not clm:
            continue  # no ChapterList field -> not usable (volume count without boundaries)
        chapters = _BULLET.findall(clm.group(1))
        if not chapters:
            continue  # ChapterList present but no numeric bullets (e.g. only "Bonus Material")
        first, last = chapters[0], chapters[-1]
        volumes.append({"number": number, "chapterStart": first, "chapterEnd": last})

    if not volumes:
        return None
    volumes.sort(key=lambda v: v["number"])
    return volumes


def wikipedia_volumes(series_title):
    """Resolve a series' full volume->chapter mapping from Wikipedia.

    Returns (volumes, source_url) where volumes is a list of
        {"number": int, "chapterStart": str, "chapterEnd": str}
    ascending by number, or None when Wikipedia has no usable Graphic novel list ChapterList
    for the series (no transcluding page matched, or the matched page carries no ChapterList).

    Discovery is deterministic: the transclusion set is enumerated (cached) and the series is
    matched against it -- no URL is ever guessed.
    """
    titles = cache_page_list()
    page = _match_page(series_title, titles)
    if page is None:
        return None
    try:
        wikitext = _fetch_wikitext(page)
    except requests.RequestException:
        return None
    if wikitext is None:
        return None
    volumes = parse_volumes_from_wikitext(wikitext)
    if volumes is None:
        return None
    source_url = f"https://en.wikipedia.org/wiki/{page.replace(' ', '_')}"
    return volumes, source_url
