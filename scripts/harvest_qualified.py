"""Task 8 — THE HARVEST: write the 4 qualified fallback records to db/.

Approved by Hemanth 2026-07-30. This is the FIRST real touch of db/ by the fallback arc.

Four records, all qualified:true (shelf flips to volume view):
  - Demon Slayer   (Kimetsu-No-Yaiba, sid 01J76XYBPP2A7D38XGF4PSQVPD) -- ID confirmed by
                    chapter-count match (serves 205 whole chapters = the manga's total), NOT by
                    string similarity (the resolver scores "Demon Slayer" vs "Kimetsu-No-Yaiba"
                    at 0.240, below the 0.8 floor). Hemanth ruled: use it, justified by the count.
  - One-Punch Man  (sid 01J76XY7KT7J224EBK6J816Y1Q, slug Onepunch-Man) -- resolved normally.
  - Sakamoto Days  (sid 01J76XYE3130E1W5HKTJ7VD912, slug Sakamoto-Days) -- resolved normally.
  - Vinland Saga   (sid 01J76XY7FQY59WRK2YWX5T4E5N) -- EXISTING unqualified seed record. The
                    fence permits the update: existing qualified:false + numberingQuirk:false.

Rules (Hemanth):
  - Every record carries source + sourceUrl.
  - NO synopses this pass. (fetch_fandom_synopses stubbed to a no-op.)
  - Qualified records ONLY -- no unqualified writes this pass.
  - Validate each result is fallback_qualified BEFORE writing; abort on any non-qualified.
  - Written by explicit pathspec in ONE commit (the caller does the git add of exactly these 4).

THE FENCE (re-read before write, confirmed here): build_fallback_record skips when
existing_record["qualified"] is True or existing_record["numberingQuirk"] is True.
  - Demon Slayer / One-Punch Man / Sakamoto Days: existing_record=None -> fence is a no-op.
  - Vinland Saga: existing_record loaded from db/, qualified=False, numberingQuirk=False ->
    fence PERMITS. Verified live below.
"""
import json
import pathlib

from comick_volume_db import fallback as fb
import comick_volume_db.fandom_source as fs
from comick_volume_db import comick_client

# No synopses this pass. Synopses never affect the gate; this stub keeps the write lean and
# exactly matches the approved scope (shelves only).
fs.fetch_fandom_synopses = lambda t, max_volumes=200: ({}, None)

DB = pathlib.Path("db")

# (series_title, weebcentral_id, comick_hid, comick_slug, is_update_of_existing_seed)
HARVEST = [
    ("Demon Slayer",   "01J76XYBPP2A7D38XGF4PSQVPD", "cX8XMcdd", "Kimetsu-No-Yaiba", False),
    ("One-Punch Man",  "01J76XY7KT7J224EBK6J816Y1Q", "WfaSlMP9", "Onepunch-Man",     False),
    ("Sakamoto Days",  "01J76XYE3130E1W5HKTJ7VD912", "U7pnGzCh", "Sakamoto-Days",    False),
    ("Vinland Saga",   "01J76XY7FQY59WRK2YWX5T4E5N", "xui1JrAT", "Vinland-Saga",     True),
]


def main():
    written = []
    scraped_at = "2026-07-30T00:00:00Z"
    for title, wid, hid, slug, is_update in HARVEST:
        existing = None
        before = None
        if is_update:
            p = DB / f"{wid}.json"
            if not p.exists():
                raise SystemExit(f"FENCE ABORT: {title} expected an existing record at {p}, "
                                 f"found none.")
            existing = json.loads(p.read_text(encoding="utf-8"))
            before = {
                "qualified": existing.get("qualified"),
                "numberingQuirk": existing.get("numberingQuirk", False),
                "source": existing.get("source", "comick"),
                "vol_count": len(existing.get("volumes", [])),
            }
            # Confirm the fence permits this update.
            if before["qualified"] is True:
                raise SystemExit(f"FENCE ABORT: {title} existing record is qualified:true -- "
                                 f"the fence forbids overwriting it.")
            if before["numberingQuirk"] is True:
                raise SystemExit(f"FENCE ABORT: {title} existing record is numberingQuirk:true "
                                 f"-- fence refuses.")

        rec, action, _syn = fb.build_fallback_record(
            series_title=title, existing_record=existing,
            comick_hid=hid, comick_slug=slug, weebcentral_id=wid, scraped_at=scraped_at)

        # QUALIFIED-ONLY gate. Abort the whole harvest if any series did not qualify -- do not
        # write a partial set. (Hemanth: qualified records ONLY this pass.)
        if action != "fallback_qualified" or rec is None or not rec["qualified"]:
            q = rec.get("qualified") if rec else None
            gr = rec.get("gateReason") if rec else None
            raise SystemExit(
                f"QUALIFY ABORT: {title} action={action!r} qualified={q!r} "
                f"gateReason={gr!r}. Nothing written.")

        out_path = DB / f"{wid}.json"
        out_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        vols = rec["volumes"]
        v1, vN = vols[0], vols[-1]
        written.append({
            "series": title,
            "weebcentralId": wid,
            "source": rec["source"],
            "sourceUrl": rec["sourceUrl"],
            "volCount": len(vols),
            "firstRange": f"v{v1['number']}: {v1['chapterStart']}-{v1['chapterEnd']}",
            "lastRange": f"v{vN['number']}: {vN['chapterStart']}-{vN['chapterEnd']}",
            "beforeQualified": before["qualified"] if before else "(new record)",
            "afterQualified": rec["qualified"],
            "path": str(out_path),
        })
        print(f"OK   {title:16s} -> {wid}  ({len(vols)} vols, source={rec['source']})")

    print("\n=== HARVEST SUMMARY ===")
    print(json.dumps(written, indent=2, ensure_ascii=False))
    print(f"\n{len(written)} records written to db/. Stage these exact paths for the commit:")
    for w in written:
        print(f"  {w['path']}")


if __name__ == "__main__":
    main()
