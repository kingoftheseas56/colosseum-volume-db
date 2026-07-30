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
import time

from comick_volume_db.http_retry import SourceUnreachable, fetch_with_retry

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}
TIMEOUT = 30

# Polite inter-fetch delay for sequential page walks. The category path lists then fetches every
# ``Volume_N`` page one by one (One Piece = ~115 sequential fetches); the next-link walk does the
# same. Without a gap we hammer a fan-maintained wiki whose operators owe us nothing. The sleep
# is between fetches only -- never after the last one, which would waste wall-clock to no end.
# (Added 2026-07-30 per Hemanth: "do not hijack fan-wiki servers. One Piece is 115 sequential
# fetches; a 1s gap is the minimum politeness a fan-maintained resource is owed.)
FETCH_DELAY = 1.0

# Field names that hold the chapter range/list, across wikis. Match by NAME, never template.
CHAPTER_FIELD_KEYS = ("chapters", "chapter", "chapter_list", "chapter list", "contents")

# Field names that hold the volume's DISPLAY TITLE (its prose name, e.g. One Piece vol 1 =
# "Romance Dawn"). Ordered ENGLISH-FIRST: ``title`` and ``ename`` (English name) are tried
# before ``name``/``volume_title``, because ``jname``/``rname`` (Japanese/romanized) are
# deliberately excluded -- keeping them would mean guessing which transliteration a reader
# wants, and the task said "keep the Japanese/romanized only if you can do it without guessing
# which is which." A volume with none of these keys has no title (Mushishi, Vinland Saga) --
# that is normal for tankobon that genuinely carry none, not a failure. A missing ``name`` is
# valid and NEVER affects the gate.
NAME_FIELD_KEYS = ("title", "ename", "name", "volume_title")

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
    """Series title -> fandom subdomain slug. 'Vinland Saga' -> 'vinlandsaga'.

    lowercase, drop punctuation, drop whitespace. Crockford-clean ASCII for the subdomain.
    """
    keep = (ch for ch in title.lower() if ch in string.ascii_lowercase + string.digits)
    return "".join(keep)


# DNS (RFC 1035) limits a single label to 63 octets. A Fandom host is one label -- the slug --
# immediately followed by '.fandom.com'. Fandom subdomains derived from long light-novel / isekai
# romaji titles routinely blow past 63 chars (observed in the wild 2026-07-31: slugs of 76, 87,
# and 103 chars all raised urllib3 LocationParseError, which previously crashed the whole batch).
# Such a host CAN NEVER EXIST -- no DNS resolver will serve a >63-char label -- so a series whose
# slug exceeds the cap has no reachable Fandom wiki under the slug-derived host. We do not truncate
# (a truncated label is a different, wrong series' potential host); we return None so the caller
# treats it as clean 'no data', never as an exception. See _host_for.
DNS_LABEL_MAX = 63


def _host_for(title):
    """Fandom host for a series title, or None when no valid host can be built.

    Returns f"{slug}.fandom.com" when slug fits DNS's 63-octet label limit; None when it does not.
    A None here is a settled negative -- the slug-derived host cannot exist, so there is no Fandom
    wiki reachable under that name -- NOT a transport failure. Callers that fetched the host and
    got None should treat it as 'no data' (the series simply has no slug-valid Fandom wiki), not as
    'unreachable' (which means a real host could not be contacted).
    """
    slug = _slugify(title)
    if len(slug) > DNS_LABEL_MAX:
        return None
    return f"{slug}.fandom.com"


def _fetch_wikitext(host, page):
    """Return wikitext for a page, following redirects. None if the page does not exist
    (404 or MediaWiki ``missingtitle``).

    Raises ``SourceUnreachable`` (from http_retry) on transport failure after retries -- a
    DISTINCT outcome from the None 'no page' return. A 404 / missingtitle is a REAL server
    response -> None ('no data', settled); a connection refused / timeout / reset raises ->
    'unreachable', the caller propagates it so a batch run can re-run the series. The two must
    never collapse to the same value (Task 5b)."""
    params = {"action": "parse", "page": page, "prop": "wikitext", "format": "json",
              "redirects": 1}
    r = fetch_with_retry(f"https://{host}/api.php", params=params, headers=HEADERS, timeout=TIMEOUT)
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


# --- volume display-name extraction (additive, optional, never gates) ----------------

# Markup shapes stripped from a name value. MediaWiki italic/bold ('' / ''' / ''), wikilinks
# ([[Target|label]] or [[label]] -> keep label), template calls ({{Nihongo|en|ja|rom}} -> keep
# first arg), and <ref>...</ref> citation refs (including a self-closing <ref/>). Anything left
# after stripping is the prose title as a reader would see it.
_REF = re.compile(r"<ref[^>]*?/>|<ref[^>]*?>.*?</ref>", re.S | re.I)
_TEMPLATE_CALL = re.compile(r"\{\{([^{}]*)\}\}")
_WIKILINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_ITALIC = re.compile(r"'{2,}")


def _strip_markup(value):
    """Strip wiki markup + citation refs from any field value -> plain text or None.

    Shared by _clean_name (volume titles) and _clean_synopsis (volume blurbs). Handles the
    markup observed in the wild: ''italic'' / '''bold''', [[wikilink|label]] (keep the label),
    {{Template|arg}} (keep the first positional arg), and <ref>...</ref> citation refs.
    Returns the cleaned string, or None when nothing readable remains.
    """
    if value is None:
        return None
    s = _REF.sub("", value)
    def _tpl_first_positional(m):
        parts = m.group(1).split("|")
        body = parts[1:] if parts and "=" not in parts[0] else parts
        for p in body:
            if "=" not in p and p.strip():
                return p.strip()
        return ""
    s = _TEMPLATE_CALL.sub(_tpl_first_positional, s)
    s = _WIKILINK.sub(r"\1", s)
    s = _ITALIC.sub("", s)
    s = s.strip()
    return s or None


def _clean_name(value):
    """Strip wiki markup + citation refs from a volume-title field value -> plain text or None.

    Thin wrapper over _strip_markup (kept as a named entry point because the volume-title and
    synopsis paths were historically separate, and the name documents intent at the call site).
    Returns None when nothing readable remains (a value that was ONLY markup, e.g. an empty
    '' '' or a lone ref).
    """
    return _strip_markup(value)


# --- per-volume synopsis (additive, optional, never gates) ---------------------------

# A level-2 (==) section heading whose name matches the publisher's-blurb intent. Fandom wikis
# use several spellings: "Publisher's summary" (Mushishi -- the publisher's own back-cover
# blurb), "Summary" (Vinland Saga, Tokyo Ghoul -- fan-written synopsis), "Synopsis",
# "Description". The apostrophe in "Publisher's" may be a curly ' (U+2019) or straight ', so we
# match case-insensitively on the alphabetic stem and tolerate any apostrophe shape.
_SYNOPSIS_HEADING = re.compile(
    r"^==\s*([^=\n]*?(?:publisher'?s summary|summary|synopsis|description)[^=\n]*?)\s*==\s*$",
    re.M | re.I)


def _extract_synopsis_section(wikitext):
    """Return the raw text body under the first synopsis-like == heading, or None.

    The body runs from the heading's end to the NEXT level-2 (==) heading (or end of page).
    Level-3 (===) sub-headings within the summary are kept as part of the body -- a publisher's
    blurb is a single prose block, and a stray === inside it should not truncate the blurb.

    Returns None when no synopsis-like heading is present (the common case -- many wikis carry
    no blurb at all, e.g. One Piece). That is a valid, gate-irrelevant absence.
    """
    m = _SYNOPSIS_HEADING.search(wikitext)
    if m is None:
        return None
    rest = wikitext[m.end():]
    nxt = re.search(r"^==\s", rest, re.M)  # next level-2 heading
    return rest[:nxt.start()] if nxt else rest


def _clean_synopsis(value):
    """Strip wiki markup + blockquote/quote markers from a synopsis body -> plain text or None.

    Same markup discipline as _clean_name (wikilinks, refs, templates, italics), PLUS the
    shapes a blurb carries that a title does not:
      - a leading blockquote colon (``: "..."`` -- Mushishi wraps the publisher's blurb in a
        definition-list blockquote; the colon is MediaWiki markup, not prose)
      - surrounding straight or curly quotes that wrap the whole blurb (Mushishi's blurb is
        wrapped in a single pair of double quotes; the quotes are not part of the publisher's
        text)
      - leading/trailing whitespace per line and collapsed blank lines

    Multi-paragraph blurbs are joined with a single newline. Returns None when nothing readable
    remains after stripping (a heading whose body was only markup or empty) -- recording nothing
    rather than garbage.
    """
    if value is None:
        return None
    s = _strip_markup(value)
    if s is None:
        return None
    # Drop a leading blockquote colon per line (Mushishi's ': "blurb"' shape).
    lines = []
    for ln in s.splitlines():
        ln = ln.strip()
        if ln.startswith(":"):
            ln = ln[1:].strip()
        if ln:
            lines.append(ln)
    if not lines:
        return None
    body = "\n".join(lines)
    # Strip ONE pair of surrounding double quotes if the whole blurb is wrapped (curly or
    # straight). Mushishi's publisher blurb is wrapped in straight quotes; some wikis use curly.
    body = body.strip()
    if len(body) >= 2 and body[0] in '“"„' and body[-1] in '”"':
        # only strip if they are a matched pair (both opening / both closing variants)
        if (body[0] == body[-1]) or (body[0] == '“' and body[-1] == '”'):
            body = body[1:-1].strip()
    return body or None


def _parse_synopsis(wikitext):
    """Extract a cleaned per-volume synopsis from a Volume_N page, or None when absent.

    Reads the body under the first synopsis-like == heading (see _extract_synopsis_section) and
    cleans it via _clean_synopsis. Additive + optional: a volume with no summary is normal and
    NEVER affects the gate. Returns None for both 'no heading' and 'heading present but body
    unreadable' -- a consumer cannot distinguish them and does not need to (both mean 'no blurb').
    """
    raw = _extract_synopsis_section(wikitext)
    return _clean_synopsis(raw)


def _parse_volume_name(fields):
    """Extract the English volume display-name from parsed fields, or None when absent.

    Tries NAME_FIELD_KEYS in English-preferred order (title, ename, name, volume_title) and
    returns the FIRST one that is present AND cleans to non-empty. The value is markup-stripped
    via _clean_name. jname/rname are intentionally not consulted (Japanese/romanized -- the task
    said to keep them only without guessing, and we cannot tell a reader which they want).

    A volume with no title field, or one that cleans to empty, yields None -- that is a valid,
    gate-irrelevant absence (Mushishi's tankobon genuinely carry no volume titles).
    """
    fmap = {}
    for k, v in fields:
        if k not in fmap:  # first occurrence wins, mirroring how infoboxes read top-down
            fmap[k] = v
    for key in NAME_FIELD_KEYS:
        raw = fmap.get(key)
        if raw is None:
            continue
        cleaned = _clean_name(raw)
        if cleaned:
            return cleaned
    return None


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
    """Return (parsed, next_page_title, has_nav_field, name, synopsis) for a Volume_N page.

    - parsed: (first, last) chapter strings, or None if the page has no usable chapters field.
    - next_page_title: the canonical next-volume page title (e.g. 'Volume_4'), or None.
    - has_nav_field: True if this page's template carries a 'next' OR 'previous' field. This is
      the schema signal that distinguishes link-chaining wikis (Mushishi) from
      category-organized ones (One Piece): a wiki that uses next/previous anywhere chains by
      links; one that uses neither must be enumerated via category.
    - name: the volume's English display-title (e.g. "Romance Dawn"), or None when the page
      carries none. Additive + optional; NEVER affects the gate (a missing name is valid).
    - synopsis: the volume's publisher/fan blurb (cleaned plain text), or None when the page
      carries no synopsis section. Additive + optional; NEVER affects the gate. Read from the
      SAME page already fetched for chapters+name, so it costs zero extra requests.
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
    name = _parse_volume_name(fields)
    synopsis = _parse_synopsis(wikitext)
    return parsed, _next_volume(fields), has_nav, name, synopsis


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
        if volumes:  # not the first fetch -> polite gap between Volume_N fetches
            time.sleep(FETCH_DELAY)
        # _fetch_wikitext retries internally and raises SourceUnreachable on transport failure.
        # We do NOT catch it as ([], False) -- that was the Task 5b bug (a blip returned the same
        # value as 'this wiki has no nav links'). Let it propagate so the caller reports
        # 'unreachable', distinct from the [],False 'defer to category' / None 'no data' paths.
        wt = _fetch_wikitext(host, page)
        if wt is None:
            break  # no such page -> end (or no wiki at all on the first iteration)
        parsed, nxt, has_nav, name, synopsis = _parse_one_volume(wt)
        if not has_nav:
            # This wiki does not chain by next/previous links. If we already walked some volumes
            # via links this won't fire (has_nav was True on Volume_1 to get here); reaching here
            # on the first page means abandon -> defer to category enumeration.
            return [], False
        if parsed is None:
            break  # hole -> incomplete, do not publish
        first, last = parsed
        entry = {"number": len(volumes) + 1, "chapterStart": first, "chapterEnd": last}
        if name is not None:
            entry["name"] = name  # additive + optional; absent when the page carries no title
        if synopsis is not None:
            entry["synopsis"] = synopsis  # additive + optional; absent when no blurb exists
        volumes.append(entry)
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
        # fetch_with_retry retries transport failures and raises SourceUnreachable after the
        # last attempt -- we do NOT catch that as `continue` (Task 5b): a transport failure is
        # "unreachable," not "this category has no data." A non-200 or API error is a real server
        # response, so those still `continue` to the next category spelling.
        r = fetch_with_retry(f"https://{host}/api.php", params={
            "action": "query", "list": "categorymembers", "cmtitle": cat,
            "cmlimit": 500, "format": "json"}, headers=HEADERS, timeout=TIMEOUT)
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
        for idx, (number, page) in enumerate(numbered):
            if idx > 0:
                time.sleep(FETCH_DELAY)  # polite gap between sequential Volume_N fetches
            # _fetch_wikitext retries internally and raises SourceUnreachable on transport
            # failure. We do NOT catch it as `return None` (Task 5b): that was the bug -- a
            # hiccup mid-walk returned None, identical to "this series has no volume data."
            wt = _fetch_wikitext(host, page)
            if wt is None:
                return None  # category listed a page that 404s -> inconsistent, refuse
            parsed, _, _, name, synopsis = _parse_one_volume(wt)
            if parsed is None:
                return None  # hole -> refuse, no partial publish
            first, last = parsed
            entry = {"number": number, "chapterStart": first, "chapterEnd": last}
            if name is not None:
                entry["name"] = name  # additive + optional; absent when the page carries no title
            if synopsis is not None:
                entry["synopsis"] = synopsis  # additive + optional; absent when no blurb exists
            volumes.append(entry)
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
    if host is None:
        # Slug-derived host cannot exist (DNS 63-octet label cap exceeded). Clean 'no data',
        # not an exception -- see _host_for.
        return None

    walked, complete = _walk_via_next_links(host, max_volumes)
    if complete and walked:
        return walked, f"https://{host}/wiki/Volume_1"

    # No usable next-link chain -> try category enumeration (One Piece-style wikis).
    enumerated = _enumerate_via_category(host, series_title, max_volumes)
    if enumerated:
        return enumerated, f"https://{host}/wiki/Volume_1"

    return None


def _walk_synopses_via_next_links(host, max_volumes):
    """Synopsis-only next-link walk -> (synopses, source_url) or (None, None).

    Same page-to-page chain as ``_walk_via_next_links``, but collects ONLY synopses (and names
    them by walk POSITION, since the synopsis walk does not gate on chapter readability). A
    volume with no blurb on its page is simply absent from the dict -- it does not terminate
    the chain, because synopses are independent of chapter data. This is the heart of the
    decoupling (Task 6): a series whose chapters came from Wikipedia still gets its Fandom
    blurbs fetched here, independently.

    Returns (None, None) when the wiki does not chain by next/previous links (defers to the
    category strategy) or when Volume_1 does not exist.
    """
    page = "Volume_1"
    synopses = {}
    visited = set()
    number = 0
    while number < max_volumes:
        if page in visited:
            break
        visited.add(page)
        if number:  # not the first fetch -> polite gap
            time.sleep(FETCH_DELAY)
        # _fetch_wikitext retries internally and raises SourceUnreachable on transport failure.
        # We do NOT catch it as (None, None) (Task 5b): that would conflate a network stutter
        # with "no synopsis here." SourceUnreachable propagates to the caller as an unreachable
        # outcome for the whole synopsis fetch, distinct from "no blurbs."
        wt = _fetch_wikitext(host, page)
        if wt is None:
            break
        _, nxt, has_nav, _, synopsis = _parse_one_volume(wt)
        if not has_nav:
            return None, None  # not link-chained -> defer to category strategy
        number += 1
        if synopsis is not None:
            synopses[number] = synopsis
        if not nxt:
            return synopses, f"https://{host}/wiki/Volume_1"
        page = nxt
    return None, None


def _walk_synopses_via_category(host, series_title, max_volumes):
    """Synopsis-only category walk -> (synopses, source_url) or (None, None).

    Mirrors ``_enumerate_via_category`` but collects ONLY synopses, keyed by the volume NUMBER
    from the page title (``Volume N``). A volume page with no blurb is simply absent from the
    dict. Independent of chapter readability -- the decoupling that lets a Wikipedia-ranged
    series still gain Fandom blurbs.
    """
    for cat in (f"Category:{series_title} Volumes", "Category:Volumes"):
        # fetch_with_retry retries transport failures and raises SourceUnreachable after the
        # last attempt -- we do NOT catch it as `continue` (Task 5b): a transport failure is
        # "unreachable," not "this category has no data." A non-200 or API error is a real
        # server response, so those still `continue` to the next category spelling.
        r = fetch_with_retry(f"https://{host}/api.php", params={
            "action": "query", "list": "categorymembers", "cmtitle": cat,
            "cmlimit": 500, "format": "json"}, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            continue
        data = r.json()
        if "error" in data:
            continue
        titles = [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        numbered = []
        for t in titles:
            m = _VOLUME_PAGE.match(t)
            if m:
                n = int(m.group(1))
                if 1 <= n <= max_volumes:
                    numbered.append((n, t.replace(" ", "_")))
        if not numbered:
            continue
        numbered.sort()
        synopses = {}
        for idx, (number, page) in enumerate(numbered):
            if idx > 0:
                time.sleep(FETCH_DELAY)
            # _fetch_wikitext retries and raises SourceUnreachable on transport failure; we do
            # NOT catch it as (None, None) (Task 5b). A missing page (404) is a real None and is
            # skipped -- it does not kill the synopsis walk, only that one volume.
            wt = _fetch_wikitext(host, page)
            if wt is None:
                continue  # a missing page does not kill the synopsis walk -- skip it
            _, _, _, _, synopsis = _parse_one_volume(wt)
            if synopsis is not None:
                synopses[number] = synopsis
        if synopses:
            return synopses, f"https://{host}/wiki/Volume_1"
        # category listed pages but none had a blurb -> still a valid "no blurbs" outcome,
        # not a fall-through to the other category spelling. Return empty.
        return {}, f"https://{host}/wiki/Volume_1"
    return None, None


def fetch_fandom_synopses(series_title, max_volumes=200):
    """Fetch per-volume synopses from the series' Fandom wiki, INDEPENDENT of range precedence.

    This is the Task 6 decoupling. Range precedence (comick > wikipedia > fandom) settles a
    CONTEST between sources for chapter RANGES. Synopses are not a contest -- Wikipedia carries
    no blurbs at all, so there is nothing to compete over. Letting the range contest decide
    whether we ever look for a blurb was a category error (Agent 1, ruled a bug): a series
    whose ranges came from Wikipedia should still get its Fandom blurbs fetched here.

    Returns (synopses, source_url) where synopses is {volume_number (int): blurb (str)}, or
    (None, None) when the wiki is absent / has no Volume_1 / no blurb was found on any page.
    An empty-but-present result ({}, url) means the wiki exists but no volume carried a blurb
    -- a valid "no blurbs" signal, distinct from None (no wiki / not reachable).

    Two strategies, tried in order, mirroring ``fandom_volumes``:
      A. Next-link walk (Mushishi-style link-chained wikis).
      B. Category enumeration (One Piece-style category wikis).
    """
    host = _host_for(series_title)
    if host is None:
        # Slug-derived host cannot exist (DNS 63-octet label cap exceeded). Clean 'no data',
        # not an exception -- see _host_for.
        return None, None
    synopses, url = _walk_synopses_via_next_links(host, max_volumes)
    if synopses is not None:
        return synopses, url
    return _walk_synopses_via_category(host, series_title, max_volumes)


def split_synopses(volumes):
    """Strip per-volume ``synopsis`` keys out of a volumes list -> (clean_volumes, synopses).

    Returns (clean_volumes, synopses) where:
      - clean_volumes: a NEW list with the same entries minus any ``synopsis`` key. The original
        list is not mutated. Every volume keeps number/chapterStart/chapterEnd and the optional
        ``name``. This is the list that goes into the main record the app fetches to draw a
        shelf -- synopses must NOT ride along (a blurb is 500-1500 chars and One Piece has 117
        volumes; inlining would bloat the shelf record the app loads in one shot).
      - synopses: a dict {volume_number (int): blurb (str)} for every volume that carried one.
        Empty dict when no volume had a synopsis (the common case -- patchy coverage, and many
        wikis carry no blurb section at all, e.g. One Piece). This dict is written to the SIBLING
        file ``db/<weebcentral-id>.synopsis.json`` by the caller, so blurbs lazy-load only when a
        volume is opened, never when the shelf is drawn.

    The split is the ONLY correct place to remove ``synopsis``: the key is threaded into volume
    entries during the walk because that is where the page is already fetched (zero extra
    requests), but it must not survive into the record. Splitting here keeps the record- and
    gate-facing volume shape identical to the pre-synopsis era, so the gate and the app see no
    new field.
    """
    clean = []
    synopses = {}
    for v in volumes:
        entry = {k: val for k, val in v.items() if k != "synopsis"}
        if "synopsis" in v and v["synopsis"] is not None:
            synopses[v["number"]] = v["synopsis"]
        clean.append(entry)
    return clean, synopses
