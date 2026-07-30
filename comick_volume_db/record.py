"""Record shape for db/<weebcentral-id>.json.

The same record is written for every series, regardless of which source produced it. Provenance
lives in two ADDITIVE fields, ``source`` and ``sourceUrl`` (added 2026-07-30 alongside the
Wikipedia/Fandom fallback work):

  - ``source``: one of "comick" | "wikipedia" | "fandom". Defaults to "comick" so every record
    written before this field existed -- and every existing call site -- remains valid and reads
    as Comick-sourced, which is the truth for them.
  - ``sourceUrl``: where the volume data came from. Comick records carry None (the data is the
    aggregated Comick API response, not one URL); fallback records carry the wiki chapters page
    or the Volume_1 page they were read from.

PROVENANCE EXISTS BECAUSE THE GATE VERIFIES SHAPE, NOT TRUTH. ``volume_builder.gate`` checks that
a volume set is structurally complete (unbroken run, no span overlaps, full coverage of the
in-range chapters) -- it cannot tell whether the numbers are *correct*. Comick is the aggregated
API of a manga reader; Wikipedia's ``{{Graphic novel list}}`` is publisher-cited bibliographic
data; Fandom is fan-maintained. A consumer that trusts a fandom-sourced shelf as if it were
publisher-cited is making a stronger claim than the data supports, so every record carries its
source so that choice is visible at read time. The structural gate is identical across all three
sources (no looser fallback gate); only the input ``chapters`` differ -- see ``fallback.py``.

These fields are additive: a record without them (every record in db/ today) is still a valid
record. ``build_record`` keywords them with defaults so no existing caller needs to change.

PER-VOLUME SYNOPSES live in a SIBLING file, not the record (added 2026-07-30 per Hemanth
Correction 3). A publisher's blurb is 500-1500 chars; One Piece has 117 volumes. Inlining all
blurbs into the record would bloat the shelf payload the app fetches in one shot just to draw the
shelf. So synopses are written to ``db/<weebcentral-id>.synopsis.json`` and the app lazy-loads a
volume's blurb only when that volume is opened. See ``write_synopsis_sibling`` /
``synopsis_sibling_path`` below.
"""

import json
import pathlib

HERE = pathlib.Path(__file__).parent
DB_DIR = HERE.parent / "db"


def synopsis_sibling_path(weebcentral_id):
    """The sibling-file path for a series' per-volume synopses: ``db/<id>.synopsis.json``.

    Sits next to the record ``db/<id>.json`` so a reader fetching one can find the other by a
    fixed name transform. The sibling ONLY exists when at least one volume carried a synopsis;
    a series with no blurbs (the common case) has no sibling file at all.
    """
    return DB_DIR / f"{weebcentral_id}.synopsis.json"


def write_synopsis_sibling(weebcentral_id, synopses, source="fandom", source_url=None):
    """Write the per-volume synopsis sibling file for a series.

    ``synopses`` is a {volume_number (int): blurb (str)} dict. The sibling is written ONLY when
    it is non-empty -- a series with no blurbs gets no file, so absence of the file is a reliable
    "no blurbs" signal and the app never wastes a fetch.

    PROVENANCE IS OWN, NOT MIRRORED (Task 6). The blurbs come from Fandom INDEPENDENTLY of which
    source won the chapter ranges -- a Wikipedia-ranged series (Mushishi) still gets Fandom
    blurbs, and those blurbs carry their own ``source`` / ``sourceUrl`` here. Mirroring the
    record's source would mis-label Wikipedia-sourced blurbs as "wikipedia" when in fact no
    synopsis text ever comes from Wikipedia. The default ``source="fandom"`` reflects that all
    synopses in scope today are Fandom-sourced; a caller with a different blurb source passes it
    explicitly. ``source_url`` is the Fandom URL the blurbs were read from (optional: pass None
    when the specific page is unknown).

    The sibling does NOT re-state per-volume chapters or names (those live in the record); it is
    blurbs-only.

    Returns the path written, or None when nothing was written (empty synopses). ``db/`` is NOT
    touched by this function in the current proof-and-report phase -- the caller decides whether
    to actually persist (see fallback.build_fallback_record).
    """
    if not synopses:
        return None
    sibling = {
        "weebcentralId": weebcentral_id,
        "source": source,
        "synopses": {str(vol): text for vol, text in synopses.items()},
    }
    if source_url is not None:
        sibling["sourceUrl"] = source_url
    DB_DIR.mkdir(parents=True, exist_ok=True)
    path = synopsis_sibling_path(weebcentral_id)
    path.write_text(json.dumps(sibling, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def build_record(series_title, weebcentral_id, comick_hid, comick_slug,
                 volumes, oddball, scraped_at, complete, qualified, gate_reason,
                 source="comick", source_url=None):
    # `qualified` is the app's switch: True -> show the volume shelf, False -> show the
    # flat chapter list. `volumes` is recorded either way so failing data stays inspectable.
    #
    # `source` / `source_url` (additive, defaulted) carry provenance so a reader can tell
    # whether a shelf is Comick (aggregated reader API), Wikipedia (publisher-cited), or
    # Fandom (fan-maintained). See module docstring for why this matters.
    return {
        "seriesTitle": series_title,
        "comickHid": comick_hid,
        "comickSlug": comick_slug,
        "weebCentral": {"seriesId": weebcentral_id},
        "volumes": volumes,
        "numberingQuirk": oddball,
        "complete": complete,
        "qualified": qualified,
        "gateReason": gate_reason,
        "scrapedAt": scraped_at,
        "source": source,
        "sourceUrl": source_url,
    }
