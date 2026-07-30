"""Fandom volume->chapter source. Deterministic. No models in the data path.

Fandom wikis publish a per-volume page (``Volume_1``, ``Volume_2``, ...) carrying an infobox
with a ``chapters`` field plus ``previous``/``next`` links. The chain walks itself: parse
volume N, follow ``next = [[Volume N+1]]``, repeat until the link is absent. We never assume
the volume count -- the chain terminates itself.

PROVENANCE -- Fandom is FAN-MAINTAINED, not publisher-cited (contrast wikipedia_source).
A record sourced from here is fan-collected and unverified. The structural gate this feeds
(volume_builder.gate) verifies SHAPE, NOT TRUTH: a uniform-looking wrong answer passes it.
That is why every fandom record carries ``source: "fandom"`` + ``sourceUrl`` -- so a later
consumer can tell what it is trusting, and so fandom-sourced records deserve A1's spot-check
before anyone treats them as settled.

This module only READS published wikitext and extracts numbers already written there. It
never interpolates a boundary, never infers a missing volume, and never asks a model for a
number. If a boundary is not present, the volume (and therefore the series) yields None and
the record stays unqualified.

TRAPS ALREADY PAID FOR (do not rediscover):
  1. The ``chapters`` value format varies per wiki: en-dash ``11-15`` (U+2013), hyphen+spaces
     ``18 - 26``, bare hyphen ``1-8``, wikilink lists ``[[Chapter 2]]<br>[[Chapter 3]]...``,
     comma lists ``1, 2, 3``, and a bare single ``7``. A naive ``Chapter (\\d+)`` regex finds
     NOTHING on the Mushishi page that demonstrably has the data. Parse tolerantly (see
     ``parse_chapters_field``) and unit-test every form.
  2. The template NAME varies (``Volume``, ``Volume Box``, ``Volume box``, ``Volume Infobox``).
     Match on the FIELD name, never the template name.
  3. Some wikis have no ``Volume_N`` page at all (Berserk). 404 / ``missingtitle`` -> None,
     not an error.
  4. Some wikis redirect ``Volume_N`` to a named page (Bleach ->
     ``THE DEATH AND THE STRAWBERRY (Volume 1)``). Pass ``redirects=1`` so MediaWiki resolves
     it transparently.
"""
import re
import string

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}
TIMEOUT = 30

# Field names that hold the chapter range/list, across wikis. Match by NAME, never template.
CHAPTER_FIELD_KEYS = ("chapters", "chapter", "chapter_list", "chapter list", "contents")

# A chapter label is a whole number with an optional fractional part. Kept as a STRING so
# fractional forms (25.02) survive byte-for-byte, matching volume_builder's contract. Chapter
# numbers are NEVER negative, so no leading sign -- a leading '-' here would misread the ASCII
# hyphen in a range like "1-5" as a negative second number ("-5"), which is the exact bug that
# broke the chain walk. (The en-dash separator never had this problem: it is not a hyphen.)
_LABEL = re.compile(r"\d+(?:\.\d+)?")

# The next/previous link target, e.g. "next = [[Volume 4]]" or "next=[[Vol. 4]]".
# We capture the page title to fetch next, whatever the "Volume" spelling.
_LINK = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")


def _slugify(title):
    """Series title -> fandom subdomain slug. 'Vinland Saga' -> 'vinlandsaga'."""
    # lowercase, drop punctuation, drop whitespace. Crockford-clean ASCII for the subdomain.
    keep = (ch for ch in title.lower() if ch in string.ascii_lowercase + string.digits)
    return "".join(keep)


def _host_for(title):
    return f"{_slugify(title)}.fandom.com"


def _fetch_wikitext(host, page):
    """Return wikitext for a page, following redirects. None if the page does not exist
    (404 or MediaWiki ``missingtitle``). Raises on transport errors so the caller can decide."""
    params = {"action": "parse", "page": page, "prop": "wikitext", "format": "json",
              "redirects": 1}
    r = requests.get(f"https://{host}/api.php", params=params, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        # missingtitle and friends -> no usable page
        return None
    return data["parse"]["wikitext"]["*"]


def _split_fields(wikitext):
    """Yield (key_lower, raw_value) for every ``| key = value`` in the first template block.

    Templates are ``{{ ... }}``. We only inspect the FIRST top-level template (the infobox at
    the top of the page); nested ``{{...}}`` inside a value (rare for chapter fields) are left
    intact for the value parser to handle. Template NAME is irrelevant -- only fields matter.
    """
    # Take the first balanced {{ ... }} block. MediaWiki infoboxes do not nest at top level.
    start = wikitext.find("{{")
    if start == -1:
        return
    # find the matching closing braces at depth 0
    depth = 0
    end = -1
    for i in range(start, len(wikitext) - 1):
        if wikitext[i:i + 2] == "{{":
            depth += 1
        elif wikitext[i:i + 2] == "}}":
            depth -= 1
            if depth == 0:
                end = i + 2
                break
    if end == -1:
        return
    block = wikitext[start:end]

    # Field lines: "| key = value" possibly spanning inline. We match line-by-line because
    # every field in these infoboxes starts a new line.
    for line in block.splitlines():
        m = re.match(r"\s*\|\s*([^=|]+?)\s*=\s*(.*)$", line)
        if m:
            yield m.group(1).strip().lower(), m.group(2).strip()


def parse_chapters_field(value):
    """Tolerant chapters-field parser -> (first_label_str, last_label_str) | None.

    Handles every form observed in the wild (see module docstring traps). Returns the first
    and last chapter label as STRINGS (fractional forms preserved). None when no numeric
    label is present -- which is a true negative, never a guess.

    The label order follows SOURCE order (left-to-right), not numeric order: wikilink lists
    and comma lists are written ascending, and ranges are written low-high, so source order is
    a reliable proxy for "first"/"last". We do not sort, because fractional side chapters
    (315.10) sort wrong as floats -- volume_builder's ordinal sort lives there, not here.
    """
    if value is None:
        return None
    # Strip [[Target|label]] -> keep the inner text (chapter wikis link the chapter page, e.g.
    # [[Chapter 2]] -> "Chapter 2"). We need only the number inside.
    cleaned = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", value)
    # Collect every numeric label in SOURCE order (left-to-right). Robust to whichever
    # separator a wiki chose -- en-dash, hyphen+spaces, <br>, comma, semicolon -- because we
    # take the first and last label rather than splitting on a guessed delimiter. Ranges are
    # written low-high and lists ascending, so source order is a reliable first/last proxy.
    labels = _LABEL.findall(cleaned)
    if not labels:
        return None
    return labels[0], labels[-1]


def _next_volume(fields):
    """Volume page title of the next volume, e.g. 'Volume_4', or None when the chain ends.

    Reads the 'next' field; None if absent. Some wikis also omit 'next' on the final volume,
    which is the natural termination condition. The link target is normalised to underscores
    (e.g. ``[[Volume 4]]`` -> ``Volume_4``): MediaWiki treats space and underscore as identical
    in page titles, so canonicalising to the URL form makes the fetch key deterministic and
    keeps the visited-set cycle guard exact."""
    nxt = dict(fields).get("next")
    if not nxt:
        return None
    m = _LINK.search(nxt)
    if not m:
        return None
    return m.group(1).strip().replace(" ", "_")


def _parse_one_volume(wikitext):
    """Return (parsed, next_page_title, has_nav_field) for a single Volume_N page.

    - parsed: (first, last) chapter strings, or None if the page has no usable chapters field.
    - next_page_title: the canonical next-volume page title (e.g. 'Volume_4'), or None.
    - has_nav_field: True if this page's template carries a 'next' OR 'previous' field. This is
      the schema signal that distinguishes link-chaining wikis (Mushishi) from
      category-organized ones (One Piece): a wiki that uses next/previous anywhere chains by
      links; one that uses neither must be enumerated via category.
    """
    fields = list(_split_fields(wikitext))
    chapters_val = None
    for key, val in fields:
        if key in CHAPTER_FIELD_KEYS:
            chapters_val = val
            break
    parsed = parse_chapters_field(chapters_val) if chapters_val is not None else None
    field_names = {k for k, _ in fields}
    has_nav = any(n in field_names for n in ("next", "previous"))
    return parsed, _next_volume(fields), has_nav


def _walk_via_next_links(host, max_volumes):
    """Strategy A: follow the ``next = [[Volume N+1]]`` field page to page.

    Works ONLY for wikis whose volume infobox carries previous/next links (Mushishi's
    ``{{Volume}}``). We detect that on Volume_1: if its template has no next/previous field,
    this wiki is category-organized (One Piece) and the walk is abandoned (returns incomplete)
    so the caller defers to ``_enumerate_via_category``.

    Returns (volumes, complete): ``complete`` is True only when the chain ended naturally (an
    absent next-link on a nav-equipped wiki), not on a hole, cycle, or nav-less wiki.
    """
    page = "Volume_1"
    volumes = []
    visited = set()
    while len(volumes) < max_volumes:
        if page in visited:
            break  # defensive: a cycle should not loop forever
        visited.add(page)
        try:
            wt = _fetch_wikitext(host, page)
        except requests.RequestException:
            return [], False
        if wt is None:
            break  # no such page -> end (or no wiki at all on the first iteration)
        parsed, nxt, has_nav = _parse_one_volume(wt)
        if not has_nav:
            # This wiki does not chain by next/previous links. If we already walked some volumes
            # via links this won't fire (has_nav was True on Volume_1 to get here); reaching here
            # on the first page means abandon -> defer to category enumeration.
            return [], False
        if parsed is None:
            break  # hole -> incomplete, do not publish
        first, last = parsed
        volumes.append({"number": len(volumes) + 1, "chapterStart": first, "chapterEnd": last})
        if not nxt:
            return volumes, True  # natural termination on a nav-equipped wiki
        page = nxt
    return [], False  # incomplete (hole, cycle, or no Volume_1) -> empty so caller falls back


# Match "Volume N" page titles only (rejects "Chapters and Volumes", "Special Volumes", etc.).
_VOLUME_PAGE = re.compile(r"^Volume (\d+)$")


def _enumerate_via_category(host, series_title, max_volumes):
    """Strategy B: enumerate ``Volume N`` pages via the category members API.

    For wikis whose infobox has no next/previous links (One Piece's ``{{Volume Box}}``), the
    volume chain cannot be walked -- so we list the category instead. The category name is NOT
    stable across wikis (One Piece uses ``Category:One Piece Volumes``; Mushishi/Kingdom use a
    bare ``Category:Volumes``), so we probe both spellings and take whichever lists Volume_N
    pages. Deterministic: MediaWiki category membership is server-side, not a guess.

    KNOWN BOUND: ``cmlimit=500`` caps a single category query at 500 members. The longest manga
    in scope today is One Piece at 117 volumes, far under the cap. A series exceeding 500
    Fandom-listed volume pages would be silently truncated here -- revisit with evidence if a
    series that long ever appears, rather than guessing it never will.
    """
    for cat in (f"Category:{series_title} Volumes", "Category:Volumes"):
        try:
            r = requests.get(f"https://{host}/api.php", params={
                "action": "query", "list": "categorymembers", "cmtitle": cat,
                "cmlimit": 500, "format": "json"}, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        data = r.json()
        if "error" in data:
            continue
        titles = [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        # Keep only "Volume N" pages, sort by their number, cap at max_volumes.
        numbered = []
        for t in titles:
            m = _VOLUME_PAGE.match(t)
            if m:
                n = int(m.group(1))
                if 1 <= n <= max_volumes:
                    numbered.append((n, t.replace(" ", "_")))
        if not numbered:
            continue  # this category had no Volume_N pages -> try the other spelling
        numbered.sort()
        volumes = []
        for number, page in numbered:
            try:
                wt = _fetch_wikitext(host, page)
            except requests.RequestException:
                return None
            if wt is None:
                return None  # category listed a page that 404s -> inconsistent, refuse
            parsed, _, _ = _parse_one_volume(wt)
            if parsed is None:
                return None  # hole -> refuse, no partial publish
            first, last = parsed
            volumes.append({"number": number, "chapterStart": first, "chapterEnd": last})
        if volumes:
            return volumes
    return None


def fandom_volumes(series_title, max_volumes=200):
    """Resolve a series' full volume->chapter mapping from its Fandom wiki.

    Returns (volumes, source_url) where volumes is a list of
        {"number": int, "chapterStart": str, "chapterEnd": str}
    ascending by number, or None when the wiki is absent / has no Volume_1 / Volume_1 has no
    chapters field.

    TWO deterministic strategies, tried in order:
      A. Next-link walk -- for wikis whose infobox carries previous/next links (Mushishi).
         Start at Volume_1, follow ``next = [[Volume N+1]]`` until the link is absent.
      B. Category enumeration -- for wikis with no next/previous fields (One Piece). List the
         ``Volume N`` pages via ``action=query&list=categorymembers`` and fetch each.

    Both refuse a partial mapping: any volume whose chapters field can't be read is a hole, and
    a hole means the whole series returns None. We never interpolate a boundary or publish a
    mapping with a gap. Volume numbers come from the walk position (A) or the page title (B),
    never from an in-page field that can disagree with the title.

    Never interpolates: any volume whose chapters field can't be parsed terminates the chain
    and the whole series returns None (we will not publish a mapping with a hole in it).
    """
    host = _host_for(series_title)

    walked, complete = _walk_via_next_links(host, max_volumes)
    if complete and walked:
        return walked, f"https://{host}/wiki/Volume_1"

    # No usable next-link chain -> try category enumeration (One Piece-style wikis).
    enumerated = _enumerate_via_category(host, series_title, max_volumes)
    if enumerated:
        return enumerated, f"https://{host}/wiki/Volume_1"

    return None
