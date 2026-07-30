"""Fallback volume sourcing: when Comick has no usable volume data, fill the gap from Wikipedia
or Fandom. Precedence: comick > wikipedia > fandom.

This module is the bridge between the two fallback readers (``wikipedia_source``,
``fandom_source``) and Agent 1's existing ``volume_builder`` gate. It does THREE things and only
three:

  1. PRECEDENCE -- try Wikipedia before Fandom. A series present in both takes the
     publisher-cited (Wikipedia) answer over the fan-maintained (Fandom) one.
  2. GATING -- every fallback volume set passes through the SAME ``volume_builder.gate`` that
     Comick results do. There is no second, looser gate for fallbacks. If the fallback data is
     structurally incomplete, the record stays unqualified and the app shows the flat chapter
     list. That is the correct outcome, not a failure.
  3. SOURCE-ROW GATING -- see ``_chapters_from_volumes`` and the GATE SOURCE-COUPLING note below.

A ``qualified: true`` record is NEVER overwritten, re-scraped, or touched by this code path
(HARD SCOPE FENCE from the plan). Fallback is only ever attempted for records that Comick left
unqualified -- the gap this whole module exists to close.

GATE SOURCE-COUPLING (verified empirically 2026-07-30, do not rediscover):
  ``volume_builder.gate``'s coverage check (check 6) re-derives chapter assignment via
  ``majority_assign(chapters)`` from the RAW chapter rows -- specifically from the ``vol`` tag on
  each row. A fallback source produces a *volume set* but no raw chapter-row tags. So the question
  is: what ``chapters`` do we feed the gate for a fallback?

  Experiment B (Vinland Saga, real data):
      gate(wikipedia_volumes, chapters=COMICK_RAW_ROWS) -> False
      reason: '9 chapter(s) in no volume (first: 210)'
  The refusal is structural and correct UNDER THAT INPUT: Comick leaves 210-218 untagged, so
  majority_assign cannot place them, so coverage flags them stranded. But that is the very gap
  Wikipedia fills (vol 29 = 210-220). Gating a fallback against the sparse rows of the source it
  is replacing is self-defeating by construction.

  Experiment A (Vinland Saga, real data):
      gate(wikipedia_volumes, chapters=DERIVED_FROM_VOLUMES) -> True
  Here ``chapters`` is synthesised from the fallback's own stated ranges: every whole chapter in
  [chapterStart, chapterEnd] is a row tagged with that volume. Coverage then becomes a
  self-consistency check over the fallback's published ranges.

  This is NOT a looser gate -- it is the same function, same six checks, honestly-sourced input.
  Coverage (check 6) was designed to catch Comick's specific failure mode: sparse anchors that
  interpolation would stretch across a hole. That failure mode CANNOT occur in a source that reads
  *already-published complete ranges*. The check still runs and still catches a fallback that
  contradicts itself (e.g. a Wikipedia vol29 of 210-220 alongside a vol28 of 215-217 would fail
  the span-overlap check 5, and a fallback with an internal hole in its own ranges would fail
  coverage). What it no longer catches is a fallback that AGREES WITH ITSELF but DISAGREES WITH
  COMICK -- and it should not, because Comick is precisely the source we are overriding.

  PROVENANCE is the safety net for that residual: every fallback record carries ``source`` and
  ``sourceUrl`` so a consumer knows it is trusting publisher-cited (Wikipedia) or fan-maintained
  (Fandom) data, not the aggregated reader API. The structural gate verifies shape; provenance
  tells you whose shape it is.

TAIL / ONGOING SERIES (verified 2026-07-30):
  The gate's coverage check (line 200 of volume_builder.py) reads ``first_chapter <= k <=
  last_chapter``. A chapter with ``k > last_chapter`` -- the uncollected tail of an ongoing series
  (Vinland 221+ when it continues) -- is EXCLUDED from the stranded set. It never counts as
  uncovered, so it flows to the app's "Latest chapters" shelf, not a gate failure. No special-case
  handling is needed here; the gate already does the right thing.
"""
from comick_volume_db import fandom_source, record, wikipedia_source
from comick_volume_db.volume_builder import gate


def _chapters_from_volumes(volumes):
    """Synthesise the ``chapters`` input the gate expects, FROM a fallback's own volume set.

    The gate's signature is ``gate(volumes, numbering_quirk, chapters)`` and its coverage check
    re-derives assignment via ``majority_assign(chapters)`` -- so for a fallback source (which has
    volumes but no raw chapter rows) we rebuild the rows the gate would have seen had the fallback
    source been a chapter-tagger: every whole chapter in [chapterStart, chapterEnd] becomes a row
    tagged with that volume number. See the GATE SOURCE-COUPLING note in this module's docstring
    for why this is the only coherent input and why it is not a loosening.

    Fractional endpoints are respected: a volume with chapterEnd '16.5' contributes whole chapters
    up to 16 (the .5 is a side chapter, handled by the gate's side-chapter exclusion). We never
    invent a chapter the source did not name.
    """
    chapters = []
    for v in volumes:
        start = int(v["chapterStart"].split(".")[0])
        end = int(v["chapterEnd"].split(".")[0])
        for n in range(start, end + 1):
            chapters.append({"chap": str(n), "vol": str(v["number"])})
    return chapters


def _try_wikipedia(series_title):
    """(volumes, source_url) or None. Wikipedia is publisher-cited (preferred fallback)."""
    result = wikipedia_source.wikipedia_volumes(series_title)
    if result is None:
        return None
    volumes, source_url = result
    if not volumes:
        return None
    return volumes, source_url


def _try_fandom(series_title):
    """(volumes, source_url) or None. Fandom is fan-maintained (fallback of last resort)."""
    result = fandom_source.fandom_volumes(series_title)
    if result is None:
        return None
    volumes, source_url = result
    if not volumes:
        return None
    return volumes, source_url


def _volumes_are_contiguous(volumes):
    """Fallback-specific shape check: consecutive volumes must tile in chapter space.

    For a real published volume set, volume N's last chapter is immediately followed by volume
    N+1's first chapter (vol1 ends at 5 -> vol2 starts at 6). A gap between them (vol1=1-3,
    vol2=8-10, leaving 4-7 unnamed) means the source did not actually publish a contiguous
    mapping, so we refuse it rather than ship a shelf with a hidden hole.

    This is NOT part of Agent 1's ``volume_builder.gate`` -- that gate stays byte-for-byte
    unchanged. The Comick path gets contiguity for free (Comick's raw rows fill the inter-volume
    gaps, so coverage catches a stray). Fallbacks are gated against DERIVED rows (see module
    docstring, GATE SOURCE-COUPLING), and a derived row set only contains chapters the source
    explicitly named -- so an inter-volume gap is invisible to the gate's coverage check. This
    guard closes exactly that residual. It is a SHAPE check (do the volumes tile?), not a truth
    check; provenance remains the safety net for correctness.

    Fractional endpoints are respected on the boundary: vol1 ending at '16.5' followed by vol2
    starting at '17' is contiguous (the .5 is a side chapter of 16). A side chapter STARTING a
    volume ('16.5' as chapterStart) is also accepted, matching how volume_builder treats them.
    """
    ordered = sorted(volumes, key=lambda v: v["number"])
    for prev, cur in zip(ordered, ordered[1:]):
        prev_end = int(prev["chapterEnd"].split(".")[0])
        cur_start = int(cur["chapterStart"].split(".")[0])
        if cur_start != prev_end + 1:
            return False
    return True


def _attempt(source_name, series_title):
    """Try one fallback source, gate its result, and return the resolution dict or None.

    Factored out so ``resolve_fallback`` reads as plain precedence (call _attempt for each source
    in order) rather than a loop over a pre-bound callable tuple -- a pre-bound tuple would
    capture the original functions and silently ignore test monkeypatching of the module
    attributes. Calling the module-level ``_try_*`` functions by name here resolves them fresh on
    each call, so a patched attribute is honoured.
    """
    fetcher = globals()[f"_try_{source_name}"]
    got = fetcher(series_title)
    if got is None:
        return None
    volumes, source_url = got
    chapters = _chapters_from_volumes(volumes)
    qualified, gate_reason = gate(volumes, False, chapters)
    # Fallback-specific contiguity guard (see _volumes_are_contiguous): closes the residual that
    # derived-row gating leaves open. Agent 1's gate stays unchanged.
    if qualified and not _volumes_are_contiguous(volumes):
        qualified = False
        gate_reason = "fallback volumes not contiguous in chapter space (inter-volume gap)"
    return {
        "source": source_name,
        "source_url": source_url,
        "volumes": volumes,
        "qualified": qualified,
        "gate_reason": gate_reason,
    }


def resolve_fallback(series_title):
    """Resolve a series' volumes from fallback sources, gated exactly like Comick.

    Returns a dict suitable for ``record.build_record``:
        {source, source_url, volumes, qualified, gate_reason}
    or None if NO fallback source had data for this series.

    Precedence wikipedia > fandom. The first source that returns volumes wins; later sources are
    not consulted (we do not merge across sources -- that would be interpolation).

    The returned volume set is ALWAYS gated through ``volume_builder.gate`` against the fallback's
    own derived source rows (see module docstring). A gate failure does NOT fall through to the
    next source -- a structurally-broken Wikipedia answer is not improved by also trying Fandom;
    it stays unqualified and the app shows the flat list.
    """
    return _attempt("wikipedia", series_title) or _attempt("fandom", series_title)


def build_fallback_record(series_title, existing_record, comick_hid, comick_slug,
                          weebcentral_id, scraped_at):
    """Apply fallback sourcing to ONE series, respecting the HARD SCOPE FENCE.

    Returns (new_record_or_None, action, synopses) where action is one of:
      - "skipped_qualified" : existing record is qualified:true -> NEVER touched (the fence).
                              new_record_or_None is None; the existing record stands.
      - "skipped_numbering_quirk" : existing record carries numberingQuirk:true -> refused before
                              any fetch. The fallback gate is STRUCTURALLY BLIND to a fractional
                              chapter origin (see NUMBERING-QUIRK BLINDNESS note below), so a
                              fallback for such a series can publish ranges that are internally
                              consistent but mismatched to WeebCentral's real chapter numbers.
                              Refusing is the conservative, honest call. new_record_or_None is
                              None; the existing record stands.
      - "no_fallback_data"  : no fallback source had data for this series -> None, nothing written.
      - "fallback_unqualified" : a fallback was found but the gate refused it -> a record IS
                              written (unqualified, with the fallback volumes + provenance so the
                              data stays inspectable), exactly as the Comick path writes unqualified
                              records. qualified is False; the app shows the flat list.
      - "fallback_qualified"   : a fallback was found AND the gate accepted it -> a qualified
                              record is written with source/sourceUrl provenance. This is the win.

    ``synopses`` is a {volume_number: blurb} dict for per-volume publisher/fan blurbs (Fandom
    only -- Wikipedia pages carry no synopsis section). It is returned SEPARATELY from the record
    so the caller can write the SIBLING file ``db/<id>.synopsis.json`` (see record.write_synopsis_sibling)
    and keep blurbs OUT of the shelf record the app loads in one shot. Empty dict when the source
    carried no blurbs (the common case -- Wikipedia, and Fandom wikis with no blurb section like
    One Piece). Synopses are NEVER inlined into the record's volumes list: split_synopses strips
    them before build_record, so the gate and the app see the same pre-synopsis volume shape.

    The fence: ``existing_record["qualified"] is True`` means Comick already provides a usable
    volume shelf for this series. Fallback NEVER overwrites, re-scrapes, or touches such a record
    (plan's HARD SCOPE FENCE: precedence comick > wikipedia > fandom). Only records Comick left
    unqualified -- the gap this module exists to close -- are eligible.

    NUMBERING-QUIRK BLINDNESS (discovered Task 4, 2026-07-30, on Battle Angel Alita / Soul Eater):
      ``volume_builder.gate``'s numbering-quirk check (check 1) runs ``numbering_is_oddball(chapters)``
      on the EARLIEST chapter number in the provided rows. The fallback path feeds it
      ``_chapters_from_volumes`` rows, which are synthesised from the fallback's whole-number
      volume ranges -- so they are ALWAYS clean integers and the check ALWAYS passes, even when
      the real series (per Comick) starts at a fractional chapter like 0.01 or 1.5. A fallback
      record for a numbering-quirk series would therefore claim "volume 1 = chapters 1-6" against
      a WeebCentral shelf whose chapter 1 is actually served at a different number -- internally
      consistent but wrong at the join. The fallback gate cannot see this because it never sees
      Comick's raw rows. So a series Comick flagged numberingQuirk:true is refused at the fence,
      before any fetch, rather than allowed to publish a gate-passing-but-mismatched record.
    """
    if existing_record is not None and existing_record.get("qualified") is True:
        return None, "skipped_qualified", {}
    if existing_record is not None and existing_record.get("numberingQuirk") is True:
        return None, "skipped_numbering_quirk", {}

    res = resolve_fallback(series_title)
    if res is None:
        return None, "no_fallback_data", {}

    # Strip per-volume synopses out BEFORE build_record so they never inline into the record.
    # The record the app fetches to draw a shelf stays lean; blurbs go to a sibling file the app
    # lazy-loads per volume. Only Fandom volume entries carry a synopsis key (Wikipedia yields
    # plain volume dicts), so split_synopses is a no-op for Wikipedia sources.
    clean_volumes, synopses = fandom_source.split_synopses(res["volumes"])

    rec = record.build_record(
        series_title=series_title,
        weebcentral_id=weebcentral_id,
        comick_hid=comick_hid,
        comick_slug=comick_slug,
        volumes=clean_volumes,
        oddball=False,
        scraped_at=scraped_at,
        complete=True,
        qualified=res["qualified"],
        gate_reason=res["gate_reason"],
        source=res["source"],
        source_url=res["source_url"],
    )
    action = "fallback_qualified" if res["qualified"] else "fallback_unqualified"
    return rec, action, synopses
