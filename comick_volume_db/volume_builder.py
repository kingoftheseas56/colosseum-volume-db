"""Pure logic: Comick chapter list -> ordered volume records with chapter ranges.

Input chapters: [{ "chap": "7", "vol": "1", ... }]  (vol/chap are strings, may be empty/fractional)
Output: [{ "number": 1, "chapterStart": "1", "chapterEnd": "7" }, ...] ascending by number.
Chapters with no `vol` are ignored here (they become the app's "Latest chapters" shelf, derived live
from WeebCentral -- never from this DB). Covers are assigned app-side in Phase 1 (first chapter's
thumbnail), never stored here.
"""


def _to_num(raw):
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return None


def _fmt(n):
    # keep integers as "7", fractions as "110.5"
    return str(int(n)) if float(n).is_integer() else str(n)


def group_volumes(chapters):
    buckets = {}  # vol_number(int) -> set of chap floats
    for ch in chapters:
        vnum = _to_num(ch.get("vol"))
        cnum = _to_num(ch.get("chap"))
        if vnum is None or cnum is None:
            continue
        buckets.setdefault(int(vnum), set()).add(cnum)

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
