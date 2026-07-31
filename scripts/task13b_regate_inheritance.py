"""FAITHFUL re-gate harness for the sub-chapter-inheritance change (Task 13b).

PROOF BAR (Hemanth's two requirements, stricter because this one is load-bearing):
  - Berserk qualifies.
  - ZERO currently-qualified records flip.
  - Rule fires on Berserk 356 specifically.

Method: gate every db/ record under the FIXED gate (with inheritance) and compare against the
same record gated under a version of majority_assign with inheritance DISABLED. The delta isolates
*this* change and nothing else (the Task-13 fractional-origin fix already shipped, so both columns
run with numbering_quirk as a non-disqualifier -- the only variable is the inheritance pass).

GATE SOURCE-COUPLING (unchanged from Task 13): comick-source records gated against REAL comick
chapter rows; wikipedia/fandom-source records gated against DERIVED rows
(fallback._chapters_from_volumes), the path that qualified them.
"""
import json
import glob
import sys
from pathlib import Path

import comick_volume_db.volume_builder as vb
from comick_volume_db.volume_builder import numbering_is_oddball
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
    source = record.get("source", "comick")
    vols = record.get("volumes", [])
    if source in ("wikipedia", "fandom"):
        return fb._chapters_from_volumes(vols)
    return get_real_chapters(record)


def majority_assign_no_inherit(chapters):
    """majority_assign WITH the inheritance pass stripped -- the 'before' behaviour. Identical to
    the current function up through _fix_stray_tags, but skips _inherit_from_subchapters."""
    votes = {}
    for ch in chapters:
        vol_key = vb._to_num(ch.get("vol"))
        chap_key = vb._to_num(ch.get("chap"))
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
    return vb._fix_stray_tags(assign)


def run():
    rows = []
    for f in sorted(glob.glob(str(DB / "*.json"))):
        r = json.loads(open(f, encoding="utf-8").read())
        title = r.get("seriesTitle", "?")
        db_q = r.get("qualified")
        vols = r.get("volumes", [])
        chapters = chapters_for_record(r)
        oddball = numbering_is_oddball(chapters)

        # FAITHFUL TO THE PROOF BAR: gate the STORED RECORD VOLUMES (r['volumes']), not a
        # re-derived set. The question is "does this qualified record stay qualified", and a
        # qualified record carries the volumes it was qualified WITH. Re-running group_volumes
        # would instead test "does re-grouping today's rows produce a qualifying set" -- a
        # different question that silently changes the span the chapters are measured against
        # (Death Note's stored vol 13 = 109-115.2, but today's untagged 109-114 re-group into no
        # vol 13 at all, moving the last-volume end and hiding the strand). Gate the record's own
        # volumes; the only variable between before/after is the inheritance pass inside the
        # majority_assign that gate() calls for its coverage check.
        stored_vols = vols

        orig = vb.majority_assign
        vb.majority_assign = majority_assign_no_inherit
        try:
            q_before, reason_before = vb.gate(stored_vols, oddball, chapters)
        finally:
            vb.majority_assign = orig

        # AFTER: the live code path (inheritance on), same stored volumes.
        q_after, reason_after = vb.gate(stored_vols, oddball, chapters)

        flipped_by_change = (q_before != q_after)
        rows.append({
            "title": title, "source": r.get("source", "comick"),
            "db_qualified": db_q, "oddball": oddball,
            "before_qualified": q_before, "before_reason": reason_before,
            "after_qualified": q_after, "after_reason": reason_after,
            "flipped_by_change": flipped_by_change,
        })

    # Report
    print(f"{'title':26s} {'src':9s} {'db_q':6s} {'oddb':6s} {'bef':5s} {'aft':5s} flag")
    print("-" * 90)
    berserk_row = None
    for row in rows:
        flag = ""
        if row["flipped_by_change"]:
            flag = f"  <-- FLIPPED by inheritance ({row['before_qualified']}->{row['after_qualified']})"
        if "berserk" in row["title"].lower():
            berserk_row = row
            flag += "  [BERSERK]"
        print(f"{row['title'][:26]:26s} {row['source'][:9]:9s} "
              f"{str(row['db_qualified']):6s} {str(row['oddball']):6s} "
              f"{str(row['before_qualified']):5s} {str(row['after_qualified']):5s}{flag}")

    n_flips = sum(1 for r in rows if r["flipped_by_change"])
    berserk_q = berserk_row["after_qualified"] if berserk_row else None
    berserk_before = berserk_row["before_qualified"] if berserk_row else None
    print()
    print(f"records gated: {len(rows)}")
    print(f"records flipped by the inheritance change: {n_flips}")
    print(f"Berserk before: {berserk_before}")
    print(f"Berserk after:  {berserk_q}  (proof-bar requirement: True)")

    # Show the rule firing on Berserk 356 specifically.
    berserk_rec = next((json.loads(open(f, encoding='utf-8').read())
                        for f in glob.glob(str(DB / "*.json"))
                        if 'berserk' in json.loads(open(f, encoding='utf-8').read())
                        .get('seriesTitle', '').lower()), None)
    if berserk_rec:
        chapters = chapters_for_record(berserk_rec)
        assign_after = vb.majority_assign(chapters)
        assign_before = majority_assign_no_inherit(chapters)
        k356 = (356, -1, "")
        print()
        print("Berserk 356 -- rule firing proof:")
        print(f"  before (no inherit): 356 assigned = {assign_before.get(k356)}")
        print(f"  after  (inherit):     356 assigned = {assign_after.get(k356)}")
        for sub in [(356, 1, "1"), (356, 2, "2")]:
            print(f"  356.{sub[1]} before/after: {assign_before.get(sub)} / {assign_after.get(sub)}")

    out = {
        "task": "Task 13b sub-chapter tag inheritance -- faithful re-gate delta",
        "records_gated": len(rows),
        "records_flipped_by_inheritance": n_flips,
        "requirement1_zero_flips_met": all(
            (not r["flipped_by_change"]) or "berserk" in r["title"].lower() for r in rows),
        "requirement2_berserk_qualifies_met": berserk_q is True,
        "berserk_before_qualified": berserk_before,
        "berserk_after_qualified": berserk_q,
        "per_record": rows,
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/task13b_inheritance_delta.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nwrote reports/task13b_inheritance_delta.json")


if __name__ == "__main__":
    run()
