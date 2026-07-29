"""Batch: seeds.json -> db/<weebcentral-id>.json. Run online.
Usage (from repo root): python -m comick_volume_db.build_db"""
import json
import pathlib
import time
from datetime import datetime, timezone

from comick_volume_db import comick_client, record, weebcentral_client
from comick_volume_db.volume_builder import gate, group_volumes, numbering_is_oddball

HERE = pathlib.Path(__file__).parent
DB = HERE.parent / "db"          # repo-root db/  (becomes the GitHub DB repo contents)
SEEDS = HERE / "seeds.json"


def build_one(title):
    hid = comick_client.search(title)
    if not hid:
        return None, f"no comick match for {title!r}"
    chapters = comick_client.fetch_chapters(hid)
    volumes = group_volumes(chapters)
    if not volumes:
        return None, f"no volume tagging for {title!r}"
    sid, slug = weebcentral_client.resolve(title)
    if not sid:
        return None, f"no weebcentral id for {title!r}"
    oddball = numbering_is_oddball(chapters)
    qualified, gate_reason = gate(volumes, oddball, chapters)
    rec = record.build_record(
        series_title=title, weebcentral_id=sid, comick_hid=hid, comick_slug=slug or "",
        volumes=volumes, oddball=oddball,
        scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), complete=True,
        qualified=qualified, gate_reason=gate_reason)
    return rec, sid


def main():
    DB.mkdir(exist_ok=True)
    for t in json.loads(SEEDS.read_text(encoding="utf-8")):
        rec, key = build_one(t)
        if rec is None:
            print("SKIP", t, "-", key)
            continue
        (DB / f"{key}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        print("OK  ", t, "->", key, f"({len(rec['volumes'])} vols)")
        time.sleep(1.0)  # be polite


if __name__ == "__main__":
    main()
