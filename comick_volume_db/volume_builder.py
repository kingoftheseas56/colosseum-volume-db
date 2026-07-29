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
    """Physical volumes are sequential -- a later chapter is never bound into an earlier book --
    so walking chapters in order the volume must never go down. Where one chapter breaks that and
    the chapters on BOTH sides of it agree with each other, that one chapter is a stray tag and
    joins its neighbours. Real cases, both a single mis-tagged row against 4-12 agreeing rows:
    Naruto 459.3 tagged volume 50 between two volume-49 chapters, Berserk 106.5 tagged volume 13
    between two volume-15 chapters.

    The outlier moves, never the consensus. (Capping each chapter by the lowest volume claimed
    after it also produces a monotonic run, but it resolves the wrong way: Berserk's single stray
    row would drag 16 well-attested chapters down into volume 13 with it. Measured 2026-07-29.)

    Nothing is invented: an UNASSIGNED chapter stays unassigned, so a real hole still reaches the
    gate. Anything a stray-tag fix can't settle leaves the run non-monotonic, which shows up as
    overlapping spans -- and `gate` refuses those, so it can never reach the shelf.
    """
    keys = sorted(assign)
    settled = dict(assign)
    for prev_key, key, next_key in zip(keys, keys[1:], keys[2:]):
        before, after = settled[prev_key], assign[next_key]
        if before == after and settled[key] != before:
            settled[key] = before
    return settled


def majority_assign(chapters):
    """{chapter_key: volume(int)} -- each chapter goes to the volume the most rows voted for,
    then lone stray tags are pulled back to their neighbours (see _fix_stray_tags).

    Rows missing chap or vol don't vote. A dead tie means the sources genuinely contradict each
    other, so the chapter is left UNASSIGNED rather than guessed -- the hole is then the gate's
    to judge.
    """
    votes = {}
    for ch in chapters:
        vol_key = _to_num(ch.get("vol"))
        chap_key = _to_num(ch.get("chap"))
        if vol_key is None or chap_key is None:
            continue
        per_volume = votes.setdefault(chap_key, {})
        per_volume[vol_key[0]] = per_volume.get(vol_key[0], 0) + 1

    assign = {}
    for chap_key, per_volume in votes.items():
        most = max(per_volume.values())
        winners = [vol for vol, count in per_volume.items() if count == most]
        if len(winners) == 1:
            assign[chap_key] = winners[0]
    return _fix_stray_tags(assign)


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
    against the source rows they came from: at least one volume, integer numbers in one unbroken
    run starting at 0 or 1, no numbering quirk, spans that don't overlap, and no chapter stranded
    between two volumes. Anything else -> the app shows the flat chapter list instead.
    NEVER soften this into estimation -- sparse anchors + interpolation invents book boundaries,
    which Hemanth explicitly rejected.

    The chapter-axis checks need the source, not just the collapsed spans: a run no uploader ever
    tagged (Vinland Saga 210-218) leaves the volume numbers looking perfect while nine chapters
    belong to no book. `chapters` is the same row list majority_assign consumes.

    Only WHOLE chapters count as stranded. An untagged side chapter between two volumes that are
    already back to back is an extra that was never bound into either book, not a hole in the
    shelf -- measured 2026-07-29, the only thing sitting between Bleach volumes 19 (159-168) and
    20 (169-178) is one untagged "168.5", and One Piece 101/102 and Vinland Saga 19/20 are the
    same shape. Vinland's REAL hole is nine whole chapters, and it still fails on those.
    """
    if numbering_quirk:
        return False, "numbering quirk (fractional chapter origin)"
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
    for (num_a, _, end_a), (num_b, start_b, _) in zip(spans, spans[1:]):
        if start_b <= end_a:
            return False, "volume %d span overlaps volume %d" % (num_a, num_b)

    known_whole = {k for k in (_to_num(c.get("chap")) for c in chapters)
                   if k is not None and not _is_side_chapter(k)}
    for (num_a, _, end_a), (num_b, start_b, _) in zip(spans, spans[1:]):
        if any(end_a < k < start_b for k in known_whole):
            return False, "unmapped chapters between volume %d and volume %d" % (num_a, num_b)
    return True, ""
