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
(``*Bonus Material.``). Two written-number shapes are read:
  - bare number, dot terminator: ``*001.``, ``*210.`` (most series)
  - word prefix + number, colon/space terminator: ``*Days 1:``, ``*Fight 4 `` (Sakamoto Days,
    Battle Angel Alita)
In BOTH shapes the chapter number is written as a token in the wikitext -- we read it, we never
derive it. The parser strips leading zeros, skips non-numeric bullets, and takes the first and
last NUMERIC chapter in source order as the volume's range (strings preserved so fractional
forms survive, matching volume_builder's contract). A two-column ``ChapterListCol1`` /
``ChapterListCol2`` split is concatenated in source order (col1 = first half of the run, col2 =
second half).

DERIVATION SCHEMAS ARE READ, NOT REFUSED (re-examined 2026-07-30 per Hemanth correction).
Some ChapterList fields use MediaWiki ordered-list ``#`` markers or the nested
``{{Numbered list|start=N}}`` template, where the chapter number is NOT written per-item.
Initially these were refused as "interpolation" -- that was OVER-CAUTIOUS. The ``start`` value
IS a written token, the item COUNT is READ (each ``#`` or ``|`` line is discrete, not
estimated), and ``start + count - 1`` is arithmetic over two visible things -- exactly as
deterministic as trusting a written ``"8-10"`` range (which also trusts an editor not to mistype).
Interpolation is inventing a boundary you CANNOT see; this is arithmetic over two you CAN.

The safety net is mechanical, not blind trust: ``_volumes_are_contiguous`` (in fallback.py)
refuses the whole series if any volume's derived range fails to tile -- vol N's end + 1 must
equal vol N+1's start, AND columns within a volume must tile too (col1 end + 1 = col2 start).
A miscounted item breaks tiling and the series stays unqualified. That is the guard doing its
job, and it is a real check on the derivation.

A page that exists but carries only ISBNs and dates (Tower of God: every ChapterList field
empty) yields None, and a series whose only list page uses a different template with no GNL
blocks at all (JoJo's 'List of ... volumes') yields None for the same reason.
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

_GNL_OPEN = "{{Graphic novel list"
# VolumeNumber = N (digits only). Some pages pad or suffix; we take the integer.
_VOLNUM = re.compile(r"\|\s*VolumeNumber\s*=\s*(\d+)")


def _find_gnl_blocks(wikitext):
    """Every top-level ``{{Graphic novel list ... }}`` block body, brace-balanced.

    A regex (``\\{\\{Graphic novel list\\s*\\n(.*?)\\n\\}\\}``) gets the block boundary WRONG when
    a volume's ChapterList nests other templates (``{{Nihongo|...}}``, ``{{Numbered list|...}}``):
    the first ``}}`` it sees is the nested template's close, not the GNL's, so the captured body is
    TRUNCATED mid-ChapterList. That silently dropped the ``{{Numbered list}}`` closer and made the
    derivation series unreadable -- not because derivation is impossible, but because the block was
    cut short. Brace-balanced extraction finds the GNL's true closing ``}}`` at depth 0, so nested
    templates stay intact. Verified same block counts on bullet-style pages (Vinland: 29) and
    nested-template pages (Dandadan: 27); only the body COMPLETENESS changed.

    Skips ``{{Graphic novel list/header}}`` and other suffixed variants: the opener must be
    followed by a newline (the real volume blocks) or be the bare template end, not a ``/``.
    """
    blocks = []
    i = 0
    while True:
        i = wikitext.find(_GNL_OPEN, i)
        if i < 0:
            break
        after = wikitext[i + len(_GNL_OPEN):i + len(_GNL_OPEN) + 1]
        # Reject "/header" etc.: the char right after the opener must not be '/'.
        if after == "/":
            i += 1
            continue
        depth = 0
        j = i
        while j < len(wikitext) - 1:
            if wikitext[j:j + 2] == "{{":
                depth += 1
                j += 2
            elif wikitext[j:j + 2] == "}}":
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        if depth == 0:
            blocks.append(wikitext[i + len(_GNL_OPEN):j - 2])
        i = j if j > i else i + 1
    return blocks
# Locates a ChapterList field header (``ChapterList``, ``ChapterListCol1``, ``ChapterListCol2``)
# inside a GNL block body. Used only as an ANCHOR to find where each column's content begins;
# the actual content boundary is then computed by the parser, because a naive lookahead
# terminator would stop at the first ``\n| `` line -- which is exactly what {{Numbered list}}
# items look like. See parse_volumes_from_wikitext for the column-extraction logic.
_CHAPTERLIST_HEADER = re.compile(r"\|\s*(ChapterList(?:Col[12])?)\s*=", re.I)
# A chapter bullet. Two written-number shapes appear in the corpus:
#   "*001.", "*210.", "*1."            -- bare number, dot terminator (most series)
#   "*Days 1:", "*Fight 4 "            -- word prefix + number, colon or space terminator
#                                       (Sakamoto Days, Battle Angel Alita)
# The number is ALWAYS WRITTEN as a token in both shapes -- we read it, we never derive it
# by counting list position. The optional non-numeric prefix is tolerated, not required.
# Skips non-numeric bullets like "*Bonus Material." (no digit at the number slot).
# The terminator after the captured number is one of: ``.`` / ``:`` / whitespace. ``.`` covers the
# common ``*001.``; ``:`` covers ``*Days 1:``; whitespace covers ``*Fight 1 {{...}}`` where no
# punctuation separates the number from the title. A bare ``*1`` at end-of-line (no terminator)
# is intentionally not matched -- every real bullet in the corpus carries a title after the
# number, so requiring a terminator is a sound guard against a stray number in prose.
_BULLET = re.compile(r"^\s*\*(?:\s*[A-Za-z]+\s+)?0*(\d+)(?:[.:]|\s)", re.M)
# A {{Numbered list|start=N ...}} template opener (used by the derivation path). The start value
# is a WRITTEN token; item count is read from the balanced template body. See _derive_numbered.
_NL_START = re.compile(r"start\s*=\s*(\d+)", re.I)
# A MediaWiki "#" ordered-list item line. Counted to derive a range when no start= is present
# (implicit start = 1, per MediaWiki spec -- not a guess).
_HASH_ITEM = re.compile(r"^\s*#\s*\S", re.M)


def _normalize_title(title):
    """ASCII-lowercase alphanumerics, for fuzzy title matching across spellings.
    Mirrors comick_client._norm's intent (a-z0-9) without importing it, to keep this module
    independent of the Comick path.

    One romanisation equivalence is applied before stripping: the Unicode multiplication sign
    U+00D7 (``\u00d7``) is folded to ASCII ``x``. Wikipedia titles use the typographic ``\u00d7``
    ("Hunter \u00d7 Hunter", "Yotsuba&!") while Comick, WeebCentral, and our gap_rate sample all
    spell it ``x``. Without this fold the two never compare equal -- ``\u00d7`` is non-ASCII and
    gets stripped, so the page normalises to ``hunterhunter`` while the request normalises to
    ``hunterxhunter``. Folding to ``x`` matches how every other source romanises it and is the
    only way the Hunter x Hunter list page becomes reachable. This is normalisation parity, not
    data fabrication: it changes how two spellings of the SAME title compare, never what a title
    IS."""
    folded = title.replace("\u00d7", "x")
    return "".join(c for c in folded.lower() if ("a" <= c <= "z") or ("0" <= c <= "9"))


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

    Order (deterministic, strictest first):
      1. exact title
      2. 'List of <title> chapters'
      3. normalised equality with the 'List of ... chapters' form
      4. normalised equality with the bare title
      5. CONTAINMENT fallback (added Task 4): the normalised series title is a substring of the
         normalised candidate, AND the candidate ends in 'chapters' or 'volumes'. This reaches
         pages whose title carries a subtitle or alternate spelling the strict tiers miss:
           'Demon Slayer' -> 'List of Demon Slayer: Kimetsu no Yaiba chapters'
           'Hunter x Hunter' -> 'List of Hunter \u00d7 Hunter chapters' (after the \u00d7->x fold)
         The '...chapters'/'...volumes' suffix gate prevents a short want from matching an
         unrelated longer title ('Hunter' must not hit 'Marine Hunter'). Containment is
         intentionally LAST -- it is looser than equality, so a series with a real exact-match
         page never falls through to a substring match on a different series.
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
    # Containment fallback: want is a substring of the candidate AND the candidate is a
    # chapter/volume list page. Prefer a '...chapters' page over '...volumes' when both contain
    # the want (a chapters page carries per-volume ChapterList data; a volumes page often does
    # not, e.g. JoJo's 'List of ... volumes' has zero GNL blocks).
    suffix_pages = [t for t in candidate_titles
                    if (t.endswith("chapters") or t.endswith("volumes"))
                    and want_norm and want_norm in normed[t]]
    if suffix_pages:
        chapters_first = [t for t in suffix_pages if t.endswith("chapters")]
        return (chapters_first or suffix_pages)[0]
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


def _extract_columns(block):
    """Slice a GNL block body into per-column ChapterList content segments.

    Returns a list of strings (one per ChapterList field, in source order). A plain
    ``ChapterList`` yields one segment; a ``ChapterListCol1``/``ChapterListCol2`` split yields
    two. Each segment runs from its header's end to the START of the next ChapterList header (or
    block end) -- NOT to the next ``\n|`` line, because {{Numbered list}} items are themselves
    ``\n|`` lines and would truncate the column early. Using header positions as the sole
    boundary is what makes derivation templates readable at all.
    """
    headers = list(_CHAPTERLIST_HEADER.finditer(block))
    if not headers:
        return []
    segments = []
    for idx, h in enumerate(headers):
        start = h.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(block)
        segments.append(block[start:end])
    return segments


def _balanced_template_inner(text, open_at):
    """Return (inner, close_index) of the ``{{...}}`` template opening at ``open_at``, or (None,_).

    Brace-balanced so nested templates (``{{Nihongo|...}}`` inside ``{{Numbered list|...}}``) are
    accounted for: depth counts opens and closes, and we return when depth returns to 0.
    """
    assert text[open_at:open_at + 2] == "{{"
    depth = 0
    i = open_at
    while i < len(text) - 1:
        if text[i:i + 2] == "{{":
            depth += 1
            i += 2
        elif text[i:i + 2] == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return text[open_at + 2:i - 2], i
        else:
            i += 1
    return None, len(text)


def _count_numbered_list_items(template_inner):
    """Count the positional items in a ``{{Numbered list|...}}`` template body.

    An item is a line starting with ``|`` that does NOT carry the ``start=`` parameter. The
    opener line ``Numbered list|start=N`` and the start parameter are excluded; everything else
    beginning with ``|`` at line start is one chapter item.

    The character right after the pipe varies by page: ``| {{Nihongo|...}}`` (pipe-space, e.g.
    Dandadan vol 1) and ``|{{Nihongo|...}}`` (pipe-brace, no space, e.g. Chainsaw Man, Demon
    Slayer, Dandadan vol 5 col2) are BOTH valid item shapes -- sometimes within the SAME series.
    Requiring pipe+whitespace silently dropped the pipe-brace items, undercounting the column,
    which then broke cross-volume tiling (the very miscount the guard exists to catch). Matching
    a bare ``|`` (whitespace optional) reads both shapes.
    """
    count = 0
    for line in template_inner.splitlines():
        if re.match(r"^\s*\|", line) and "start" not in line.lower():
            count += 1
    return count


def _parse_column_range(segment):
    """Derive a single column's chapter range -> (start_str, end_str) or None.

    Three schemas, tried in order. Each returns None when the segment carries no readable
    chapter data (a true negative):

    1. WRITTEN BULLETS (``*001.``, ``*Days 1:``): the number is a token in the wikitext. First
       and last bullet number form the range. Most series.
    2. ``{{Numbered list|start=N}}``: ``start`` is a written token; the item COUNT is read from
       the balanced template body. Range = [start, start + count - 1]. Deterministic arithmetic
       over two visible values -- not interpolation.
    3. MediaWiki ``#`` ordered list (no ``start=``): implicit start = 1 per the MediaWiki spec;
       count read from ``#`` lines. Range = [1, count].

    A segment may carry bullets AND a Numbered list (Black Clover vol 1: col1 is ``#``, col2 is
    ``{{Numbered list|start=5}}``). The first schema that yields a range wins, so a column is
    read by exactly one path.
    """
    # Schema 1: written bullets.
    bullets = _BULLET.findall(segment)
    if bullets:
        return bullets[0], bullets[-1]
    # Schema 2: {{Numbered list|start=N ...}} -- find via balanced extraction (nested templates).
    nl_idx = segment.lower().find("{{numbered list")
    if nl_idx >= 0:
        inner, _ = _balanced_template_inner(segment, nl_idx)
        if inner is not None:
            sm = _NL_START.search(inner)
            if sm:
                start = int(sm.group(1))
                count = _count_numbered_list_items(inner)
                if count > 0:
                    return str(start), str(start + count - 1)
    # Schema 3: bare # ordered list (implicit start = 1).
    hash_count = len(_HASH_ITEM.findall(segment))
    if hash_count > 0:
        return "1", str(hash_count)
    return None


def parse_volumes_from_wikitext(wikitext):
    """Extract volume->chapter ranges from a page's {{Graphic novel list}} blocks.

    Returns a list of {"number": int, "chapterStart": str, "chapterEnd": str} sorted by number,
    or None when the page has no Graphic novel list blocks carrying a readable ChapterList (the
    common case -- most manga list pages use other formats). A block with VolumeNumber but no
    ChapterList is skipped; if NO block yields a range, the whole page yields None.

    Three ChapterList schemas are read (see _parse_column_range): written bullets,
    {{Numbered list|start=N}} derivation, and # ordered-list derivation. A two-column
    ChapterListCol1/Col2 split is concatenated: the volume's range spans col1.start to the last
    column's end, and columns must TILE within the volume (col[i].end + 1 == col[i+1].start) or
    the volume is refused -- a within-volume gap means a column's item count or start is wrong,
    which is exactly the miscount the tiling guard exists to catch.
    """
    volumes = []
    for block in _find_gnl_blocks(wikitext):
        vm = _VOLNUM.search(block)
        if not vm:
            continue  # a GNL block without a VolumeNumber is not a volume row
        number = int(vm.group(1))
        columns = _extract_columns(block)
        if not columns:
            continue  # no ChapterList field -> not usable (volume count without boundaries)
        col_ranges = []
        for seg in columns:
            r = _parse_column_range(seg)
            if r is not None:
                col_ranges.append(r)
        if not col_ranges:
            continue  # ChapterList present but no column yielded a readable range
        # Within-volume tiling: columns must chain (col[i].end + 1 == col[i+1].start). A break
        # means a column's derived count or start is inconsistent with its neighbour -> refuse
        # the volume rather than publish a range with an internal gap.
        start_str = col_ranges[0][0]
        end_str = col_ranges[-1][1]
        for i in range(1, len(col_ranges)):
            if int(col_ranges[i][0]) != int(col_ranges[i - 1][1]) + 1:
                start_str = None  # signal: within-volume tiling failed
                break
        if start_str is None:
            continue
        volumes.append({"number": number, "chapterStart": start_str, "chapterEnd": end_str})

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
