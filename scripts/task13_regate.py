"""FAITHFUL re-gate harness: gate every db/ record the SAME WAY IT WAS GATED WHEN IT QUALIFIED.

The proof bar for the fractional-origin fix: the 13 qualified records stay qualified, Berserk
flips False->True, and nothing else flips.

The key subtlety (GATE SOURCE-COUPLING, fallback.py docstring): comick-source records were gated
against REAL comick chapter rows; wikipedia-source records were gated against DERIVED rows
(synthesised from the wikipedia volumes themselves, because gating a fallback against the sparse
comick rows of the source it is replacing is self-defeating). Mixing the two would produce false
flips (gating Vinland Saga's wikipedia volumes against comick's untagged 210-218 rows fails
coverage -- exactly the gap wikipedia was brought in to fill).

So per record:
  - source == 'comick'  -> gate against REAL comick chapters (cached fixtures / live fetch).
  - source == 'wikipedia' / 'fandom' -> gate against DERIVED chapters (fallback._chapters_from_
    volumes). This is the path that qualified them; it is the path that must keep qualifying them.

numbering_quirk: computed from the chapters the record was ACTUALLY gated against.
  - comick source: oddball = numbering_is_oddball(real_comick_rows). Berserk = True (0.001-0.03).
  - wikipedia source: oddball = numbering_is_oddball(derived_rows). Derived rows are always clean
    integers, so oddball = False -- the fallback gate never sees a fractional origin (this is the
    NUMBERING-QUIRK BLINDNESS the fence guards against, and it is why the fence refuses a record
    whose STORED numberingQuirk is True before attempting a fallback).
"""
import json
import glob
import os
import sys
from pathlib import Path

from comick_volume_db.volume_builder import gate, numbering_is_oddball
from comick_volume_db import comick_client
from comick_volume_db import fallback as fb

DB = Path("db")
FIX = Path("comick_volume_db/tests/fixtures")
CACHE = Path("cache/regate")
CACHE.mkdir(parents=True, exist_ok=True)

FIXTURE_MAP = {
    "Berserk": "comick_chapters_berserk.json",
    "bleach": "comick_chapters_bleach.json",
    "death-note": "comick_chapters_death-note.json",
    "yani-neko": "comick_chapters_yani-neko.json",
}


def get_real_chapters(record):
    hid = record.get("comickHid")
    slug = record.get("comickSlug", "").lower()
    for key, fname in FIXTURE_MAP.items():
        if key.lower() in slug:
            fpath = FIX / fname
            if fpath.exists():
                return json.loads(fpath.read_text(encoding="utf-8"))["chapters"]
    cpath = CACHE / f"{hid}.json"
    if cpath.exists():
        return json.loads(cpath.read_text(encoding="utf-8"))["chapters"]
    print(f"  [fetch] {record.get('seriesTitle')} hid={hid} ...", file=sys.stderr)
    chapters = comick_client.fetch_chapters(hid)
    cpath.write_text(json.dumps({"chapters": chapters}, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return chapters


def chapters_for_record(record):
    """The chapter rows this record was gated against when it qualified -- faithful to its path."""
    source = record.get("source", "comick")
    vols = record.get("volumes", [])
    if source in ("wikipedia", "fandom"):
        return fb._chapters_from_volumes(vols), "derived"
    return get_real_chapters(record), "real-comick"


def run(label, gate_mode):
    """gate_mode: 'before' = current gate (oddball refuses); 'after' = fixed gate."""
    print(f"\n=== {label} ===")
    print(f"{'title':25s} {'db_q':6s} {'src':9s} {'oddball':7s} {'gate_q':7s} reason")
    print("-" * 100)
    flips = 0
    berserk_q = None
    for f in sorted(glob.glob(str(DB / "*.json"))):
        r = json.loads(open(f, encoding="utf-8").read())
        title = r.get("seriesTitle", "?")
        db_q = r.get("qualified")
        vols = r.get("volumes", [])
        chapters, ch_src = chapters_for_record(r)
        oddball = numbering_is_oddball(chapters)
        if gate_mode == "before":
            q, reason = gate(vols, oddball, chapters)
        else:  # after: the fixed gate (passed oddball=False to exercise the fix)
            q, reason = gate(vols, False, chapters)
        match = "" if q == db_q else f"  <-- FLIP ({db_q}->{q})"
        if q != db_q:
            flips += 1
        if "berserk" in title.lower():
            berserk_q = q
        print(f"{title[:25]:25s} {str(db_q):6s} {r.get('source','comick')[:9]:9s} "
              f"{str(oddball):7s} {str(q):7s} {reason[:40]:40s}{match}")
    print(f"\n  flips (non-Berserk): {flips - (1 if berserk_q is True else 0)}")
    print(f"  Berserk qualified: {berserk_q}")
    return flips, berserk_q


if __name__ == "__main__":
    run("BEFORE (current gate: numbering_quirk=True refuses unconditionally)",
        "before")
