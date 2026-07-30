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
"""


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
