"""Pure logic: Comick chapter list -> ordered volume records with chapter ranges.

Input chapters: [{ "chap": "7", "vol": "1", ... }]  (vol/chap are strings, may be empty/fractional)
Output: [{ "number": 1, "chapterStart": "1", "chapterEnd": "7" }, ...] ascending by number.
Chapters with no `vol` are ignored here (they become the app's "Latest chapters" shelf, derived live
from WeebCentral -- never from this DB). Covers are assigned app-side in Phase 1 (first chapter's
thumbnail), never stored here.

Rows come from ALL languages (see comick_client.fetch_chapters), so one chapter number arrives many
times and uploaders occasionally disagree about its volume; `majority_assign` settles that per
chapter before grouping. `gate` then decides whether the result is a shelf the app may show.
"""
import re

_LABEL = re.compile(r"^-?\d+(?:\.\d+)?$")


def _to_num(raw):
    """Parse a chapter/volume label into a sortable key: (whole, sub_ordinal, sub_digits).

    The part after the dot is an ORDINAL, not a fraction: "315.9" < "315.10" < "315.11", because
    those are the 9th, 10th and 11th side chapters of 315. Read as floats, "315.10" == "315.1" --
    two different chapters collapsed into one and one of them was silently dropped from the DB.
    A whole chapter sorts before its side chapters (ordinal -1). The digits ride along so _fmt can
    hand back the exact label the source used ("110.30" must not come back as "110.3").
    """
    if raw is None:
        return None
    label = str(raw).strip()
    if not _LABEL.match(label):
        return None
    whole, _, sub = label.partition(".")
    return (int(whole), int(sub), sub) if sub else (int(whole), -1, "")


def _is_side_chapter(key):
    # "315.1" is a side chapter of 315; "315" is a whole chapter.
    return key[1] != -1


def _fmt(key):
    # the source's own label, byte for byte: "7", "110.5", "110.30", "25.02"
    whole, _ordinal, sub = key
    return f"{whole}.{sub}" if sub else str(whole)


def _fix_stray_tags(assign):
    """A volume is a contiguous run of chapters, so if the chapters either side of one chapter are
    both in the same volume, that chapter is in it too -- whatever a single row claims. Where a
    chapter disagrees with two neighbours that agree with each other, it takes theirs. Both real
    cases are one mis-tagged row against 4-12 agreeing ones: Naruto 459.3 tagged volume 50 between
    two volume-49 chapters, Berserk 106.5 tagged volume 13 between two volume-15 chapters.

    The chapter that moves is chosen POSITIONALLY -- the one in the middle -- not by vote weight.
    So a well-attested chapter flanked by two single-vote neighbours that happen to agree would be
    the one to move. That has never fired in this corpus (2 chapters moved in total, both the lone
    stray row), and the contiguous-run argument above holds regardless of who has more votes, but
    the code is not weighing evidence and should not be read as if it were.

    This also keeps the run monotonic, which matters because physical volumes are sequential -- a
    later chapter is never bound into an earlier book. (Capping each chapter by the lowest volume
    claimed after it is monotonic too, but resolves the wrong way: Berserk's single stray row would
    drag 16 well-attested chapters down into volume 13 with it. Measured 2026-07-29.)

    Nothing is invented: an UNASSIGNED chapter stays unassigned, so a real hole still reaches the
    gate. Anything this can't settle leaves the run non-monotonic, which shows up as overlapping
    spans -- and `gate` refuses those, so it can never reach the shelf.
    """
    keys = sorted(assign)
    settled = dict(assign)
    for prev_key, key, next_key in zip(keys, keys[1:], keys[2:]):
        before, after = settled[prev_key], assign[next_key]
        if before == after and settled[key] != before:
            settled[key] = before
    return settled


def _inherit_from_subchapters(assign, present_wholes):
    """A whole chapter N that is PRESENT in the source but WHOLLY UNASSIGNED inherits the volume
    its OWN sub-chapters (N.x) carry -- 356.1 IS chapter 356, so its tag is direct evidence about
    356, not a guess across a gap. Berserk: chapter 356 is present in every language's listing but
    untagged by every scanlator, while its two halves 356.1 and 356.2 both read vol 40, so 356
    inherits 40 and vol 40's span (351-357) becomes honestly complete.

    PRESENT-WHOLE GATE (the load-bearing qualifier). Inheritance fills a chapter that EXISTS in the
    source but is untagged; it must NEVER invent a chapter the source does not contain. A rowset
    with only 110.5 and 110.30 has no chapter 110 at all -- inventing one would claim a chapter
    WeebCentral does not list, breaking the app's join and drifting a volume's start. So only whole
    numbers in ``present_wholes`` (chapters that appear as a whole label in the input, tagged or
    not) are eligible. A whole implied only by its sub-chapters' existence stays absent.

    This is NOT interpolation and must not be read as such. Interpolation would invent a boundary
    the source does not state (e.g. "8 is untagged, 7 says vol 1 and 9 says vol 2, so split the
    difference"). Here the source STATES, via the halves it did tag, which book a chapter it DOES
    contain is in -- a half and its whole are the same chapter, just sub-divided. We are reading
    that statement, not manufacturing a chapter or a boundary.

    If the sub-chapters DISAGREE with each other (356.1 says vol 40, 356.2 says vol 41), that is
    genuinely ambiguous and we assign nothing -- ambiguous means refuse, exactly as a dead tie in
    the majority vote does. The hole then reaches the gate and the series falls back to a chapter
    list rather than a guessed shelf.

    Only WHOLLY UNASSIGNED whole chapters are filled: a whole chapter that already has a volume
    (from its own rows, or from _fix_stray_tags) is never overridden, so this pass can never
    reshape a run the rows already settled -- it only fills silence.
    """
    # whole_n -> set of distinct volumes its ASSIGNED sub-chapters carry
    whole_to_subvols = {}
    for (whole, sub, _digits), vnum in assign.items():
        if sub != -1:  # a side chapter (N.x)
            whole_to_subvols.setdefault(whole, set()).add(vnum)
    inherited = dict(assign)
    for whole, subvols in whole_to_subvols.items():
        if whole not in present_wholes:
            continue  # the whole chapter is not in the source at all -- do not invent it
        whole_key = (whole, -1, "")
        if whole_key in assign:
            continue  # the whole chapter already has a volume; never override
        if len(subvols) == 1:
            inherited[whole_key] = next(iter(subvols))  # sub-chapters unanimous -> inherit
        # len(subvols) != 1 (0 can't happen here; >=2 means disagreement) -> leave unassigned
    return inherited


def majority_assign(chapters):
    """{chapter_key: volume(int)} -- each chapter goes to the volume the most rows voted for,
    then lone stray tags are pulled back to their neighbours (see _fix_stray_tags), then a
    source-present but wholly unassigned whole chapter inherits its own sub-chapters' volume (see
    _inherit_from_subchapters).

    Rows missing chap or vol don't vote. A dead tie means the sources genuinely contradict each
    other, so the chapter is left UNASSIGNED rather than guessed -- the hole is then the gate's
    to judge.
    """
    votes = {}
    # whole chapter numbers that appear as a whole label in the input (tagged or not). An untagged
    # whole (Berserk 356) lands here; a whole implied only by sub-chapters (no "110" row, only
    # 110.5/110.30) does not -- _inherit_from_subchapters must not invent the latter.
    present_wholes = set()
    for ch in chapters:
        vol_key = _to_num(ch.get("vol"))
        chap_key = _to_num(ch.get("chap"))
        if chap_key is None:
            continue
        if not _is_side_chapter(chap_key):
            present_wholes.add(chap_key[0])
        if vol_key is None:
            continue
        per_volume = votes.setdefault(chap_key, {})
        per_volume[vol_key[0]] = per_volume.get(vol_key[0], 0) + 1

    assign = {}
    for chap_key, per_volume in votes.items():
        most = max(per_volume.values())
        winners = [vol for vol, count in per_volume.items() if count == most]
        if len(winners) == 1:
            assign[chap_key] = winners[0]
    return _inherit_from_subchapters(_fix_stray_tags(assign), present_wholes)


def group_volumes(chapters):
    assign = majority_assign(chapters)
    buckets = {}  # vol_number(int) -> set of chapter keys
    for chap_key, vnum in assign.items():
        buckets.setdefault(vnum, set()).add(chap_key)

    vols = []
    for vnum in sorted(buckets):
        chaps = sorted(buckets[vnum])
        vols.append({
            "number": vnum,
            "chapterStart": _fmt(chaps[0]),
            "chapterEnd": _fmt(chaps[-1]),
        })
    return vols


def numbering_is_oddball(chapters):
    """True when the earliest chapter number is fractional (e.g. Berserk's 0.01 prologue).
    A fractional START means Comick's numbering is offset from WeebCentral's integer chapters,
    so the ranges need Phase-1 normalization before the join lines up. Titles that start on a
    clean integer (Bleach=1, Death Note=0) join directly. Mid-series sub-chapters (27.2) are
    NOT flagged -- they bucket into their volume's range fine.
    (Data-grounded 2026-07-25: sampled fixtures are 95-100% integer; the only real join risk is
    a fractional start-offset, which this detects.)"""
    keys = [k for k in (_to_num(c.get("chap")) for c in chapters) if k is not None]
    if not keys:
        return True
    return _is_side_chapter(min(keys))


def gate(volumes, numbering_quirk, chapters):
    """(qualified, reason). Qualified = the mapped volumes are a complete, honest shelf, judged
    against the source rows they came from. Anything else -> the app shows the flat chapter list
    instead. NEVER soften this into estimation -- sparse anchors + interpolation invents book
    boundaries, which Hemanth explicitly rejected.

    Checks, in order:
      1. at least one volume;
      2. the first volume is 0 or 1;
      3. the volume numbers are one unbroken run;
      4. no volume's chapter span runs into the next one's;
      5. COVERAGE -- every whole chapter between the first volume's chapterStart and the last
         volume's chapterEnd is assigned to some volume.

    FRACTIONAL-ORIGIN SERIES (Berserk 0.001-0.03 prologue, Battle Angel Alita, Soul Eater) are
    NOT blanket-refused: a fractional chapter origin is a legitimate published numbering scheme,
    and the structural checks below (run, span-overlap, coverage) already catch genuinely broken
    data. ``numbering_is_oddball`` still DETECTS a fractional origin and the record still STORES
    it as ``numberingQuirk: True`` (useful metadata for the app), but the gate no longer treats
    that flag as a disqualifier. The blanket refuse was added before the structural checks existed;
    with them in place it is redundant AND wrong for legitimate fractional-origin series.

    NOTE: removing the blanket refuse is necessary but may not be SUFFICIENT for a given series to
    qualify -- the structural checks still apply. Berserk's fractional prologue (0.001-0.14 in vols
    1-5) is no longer refused on the flag alone. Berserk's CURRENT comick data also has a coverage
    gap (chapter 356 untagged by scanlators in every language), but that gap is now CLOSED at the
    assignment step, not the gate: ``majority_assign`` runs ``_inherit_from_subchapters``, and 356's
    own halves 356.1/356.2 both carry vol 40, so 356 inherits 40 and coverage sees a complete shelf.
    See the Task 13b commit (2026-07-30) for the inheritance rule and proof.
    (Hemanth ruling 2026-07-30 on the flag: greenlit; proof bar met = zero existing qualified
    records flip, verified by per-record before/after delta. The flag was already a no-op for every
    qualified record since they all carry numberingQuirk=False.)

    Coverage is one rule doing three jobs: it catches chapters stranded at the seam BETWEEN two
    volumes (Vinland Saga 210-218, untagged in every language, while the volume numbers 1..29 read
    perfectly), and chapters swallowed INSIDE a volume whose span was stretched across a hole by
    two distant anchors (volume 2 tagged on chapters 11 and 20 only, 12-19 tagged by nobody --
    which is the sparse-anchor interpolation this whole gate exists to refuse), and it removes the
    old pairwise loop's blind spot before the first volume by defining the range explicitly.

    Deliberately OUT of scope: chapters after the last volume's end -- the legitimate uncollected
    tail of an ongoing series, which the app surfaces as "Latest chapters" -- and chapters before
    the first volume's start, e.g. Bleach's untagged chapter 0 one-shot, which genuinely is in no
    book.

    Coverage needs to know which chapters are ASSIGNED, which the collapsed spans can't say, so it
    re-derives the assignment from `chapters` (the same row list group_volumes was given; the
    derivation is pure, so this is the same map, not a second opinion).

    Only WHOLE chapters are checked for coverage. An untagged SIDE chapter (168.5) between two
    volumes is assumed to be an extra that was never bound into either book -- e.g. Bleach volume
    19 ends at 168 and volume 20 starts at 169, back to back, with an untagged "168.5" between
    them. That assumption is an inference from today's corpus, NOT something this code verifies:
    all it actually checks is whether the label has a dot. Side chapters can be real volume
    content (Bleach volume 36 is 315.1-315.9), so a long untagged run of them would slip through.
    The longest run observed anywhere in the corpus is 2 (measured 2026-07-29), against the 9 it
    would take to matter. If that ever grows, revisit this with the evidence rather than a guess.
    """
    # numbering_quirk is NOT a disqualifier: see the FRACTIONAL-ORIGIN SERIES note above. The
    # record still stores the flag (via build_record's `oddball`), but the gate lets the
    # structural checks below decide qualification. A genuinely broken numbering scheme fails
    # one of them (coverage / span-overlap / run), so blanket-refusing on the flag alone is both
    # redundant and wrong for legitimate fractional-origin series like Berserk.
    if not volumes:
        return False, "no mapped volumes"

    ordered = sorted(volumes, key=lambda v: v["number"])
    nums = [v["number"] for v in ordered]
    if nums[0] not in (0, 1):
        return False, "first mapped volume is %d, not 0/1" % nums[0]
    for a, b in zip(nums, nums[1:]):
        if b != a + 1:
            return False, "gap after volume %d" % a

    spans = [(v["number"], _to_num(v["chapterStart"]), _to_num(v["chapterEnd"])) for v in ordered]
    spans = [s for s in spans if s[1] is not None and s[2] is not None]
    if not spans:
        return True, ""
    for (num_a, _, end_a), (num_b, start_b, _) in zip(spans, spans[1:]):
        if start_b <= end_a:
            return False, "volume %d span overlaps volume %d" % (num_a, num_b)

    first_chapter, last_chapter = spans[0][1], spans[-1][2]
    assigned = set(majority_assign(chapters))
    # a set, not a list: one chapter arrives on many rows (one per language), and the count in
    # the reason has to be chapters, not rows
    stranded = sorted({k for k in (_to_num(c.get("chap")) for c in chapters)
                       if k is not None and not _is_side_chapter(k)
                       and first_chapter <= k <= last_chapter and k not in assigned})
    if stranded:
        return False, "%d chapter(s) in no volume (first: %s)" % (len(stranded), _fmt(stranded[0]))
    return True, ""
