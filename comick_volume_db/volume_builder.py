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


def _to_num(raw):
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return None


def _fmt(n):
    # keep integers as "7", fractions as "110.5"
    return str(int(n)) if float(n).is_integer() else str(n)


def majority_assign(chapters):
    """{chapter_number(float): volume(int)} — each chapter goes to the volume the most
    rows voted for; ties break to the SMALLER volume (earlier book claims the boundary).
    Rows missing chap or vol don't vote."""
    votes = {}
    for ch in chapters:
        vnum = _to_num(ch.get("vol"))
        cnum = _to_num(ch.get("chap"))
        if vnum is None or cnum is None:
            continue
        per = votes.setdefault(cnum, {})
        per[int(vnum)] = per.get(int(vnum), 0) + 1
    return {c: min(v for v, n in per.items() if n == max(per.values()))
            for c, per in votes.items()}


def group_volumes(chapters):
    assign = majority_assign(chapters)
    buckets = {}  # vol_number(int) -> set of chap floats
    for cnum, vnum in assign.items():
        buckets.setdefault(vnum, set()).add(cnum)

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
    nums = [n for n in (_to_num(c.get("chap")) for c in chapters) if n is not None]
    if not nums:
        return True
    return not float(min(nums)).is_integer()


def gate(volumes, numbering_quirk):
    """(qualified, reason). Qualified = the mapped volumes are a complete, honest shelf:
    at least one volume, integer numbers in one unbroken run starting at 0 or 1, and no
    numbering quirk. Anything else -> the app shows the flat chapter list instead.
    NEVER soften this into estimation — sparse anchors + interpolation invents book
    boundaries, which Hemanth explicitly rejected."""
    if numbering_quirk:
        return False, "numbering quirk (fractional chapter origin)"
    if not volumes:
        return False, "no mapped volumes"
    nums = [v["number"] for v in volumes]
    if nums[0] not in (0, 1):
        return False, "first mapped volume is %d, not 0/1" % nums[0]
    for a, b in zip(nums, nums[1:]):
        if b != a + 1:
            return False, "gap after volume %d" % a
    return True, ""
