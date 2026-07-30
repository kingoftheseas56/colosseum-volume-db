"""Tests for fallback.py: precedence, gating, never-overwrite, source-row derivation.

Live tests (hit Wikipedia/Fandom) are marked ``live`` and deselected in the default run.
Everything else is pure-logic with the source readers monkeypatched.
"""
import json

import pytest

from comick_volume_db import fallback as fb
from comick_volume_db import record

VINLAND_WIKI = [
    {"number": 1, "chapterStart": "1", "chapterEnd": "5"},
    {"number": 2, "chapterStart": "6", "chapterEnd": "10"},
]
VINLAND_FANDOM = [
    {"number": 1, "chapterStart": "1", "chapterEnd": "5"},
    {"number": 2, "chapterStart": "6", "chapterEnd": "10"},
]


# --- _chapters_from_volumes -----------------------------------------------------------

def test_chapters_from_volumes_tags_each_whole_chapter():
    vols = [{"number": 1, "chapterStart": "1", "chapterEnd": "3"},
            {"number": 2, "chapterStart": "4", "chapterEnd": "5"}]
    ch = fb._chapters_from_volumes(vols)
    # 5 whole chapters, each tagged with its volume number
    assert {c["chap"] for c in ch} == {"1", "2", "3", "4", "5"}
    assert {c["vol"] for c in ch if c["chap"] in ("1", "2", "3")} == {"1"}
    assert {c["vol"] for c in ch if c["chap"] in ("4", "5")} == {"2"}


def test_chapters_from_volumes_respects_fractional_endpoint():
    # chapterEnd '16.5' -> whole chapters up to 16 only. The .5 is a side chapter; we do not
    # invent chapter 17. (Mirrors the existing Vinland record's vol 2: 5-16.5.)
    vols = [{"number": 2, "chapterStart": "5", "chapterEnd": "16.5"}]
    ch = fb._chapters_from_volumes(vols)
    assert {c["chap"] for c in ch} == {str(n) for n in range(5, 17)}  # 5..16 inclusive
    assert "17" not in {c["chap"] for c in ch}


def test_chapters_from_volumes_does_not_invent_chapters_in_a_gap():
    # If a fallback volume set had an internal hole (vol1=1-3, vol2=8-10 with 4-7 unnamed),
    # _chapters_from_volumes only emits what the source stated. It does NOT fill the hole --
    # that is the gate's job to catch, not ours to paper over.
    vols = [{"number": 1, "chapterStart": "1", "chapterEnd": "3"},
            {"number": 2, "chapterStart": "8", "chapterEnd": "10"}]
    ch = fb._chapters_from_volumes(vols)
    assert {c["chap"] for c in ch} == {"1", "2", "3", "8", "9", "10"}
    assert "5" not in {c["chap"] for c in ch}  # the gap stays a gap


# --- resolve_fallback: precedence ----------------------------------------------------

def test_resolve_prefers_wikipedia_over_fandom(monkeypatch):
    # Wikipedia returns data -> Fandom is never consulted.
    fandom_called = []
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: (list(VINLAND_WIKI), "https://en.wikipedia.org/wiki/X"))
    monkeypatch.setattr(fb, "_try_fandom",
                        lambda t: fandom_called.append(t) or (list(VINLAND_FANDOM), "https://x.fandom.com/wiki/Volume_1"))
    res = fb.resolve_fallback("Whatever")
    assert res["source"] == "wikipedia"
    assert res["source_url"] == "https://en.wikipedia.org/wiki/X"
    assert fandom_called == []  # precedence: fandom never called


def test_resolve_falls_through_to_fandom_when_wikipedia_empty(monkeypatch):
    monkeypatch.setattr(fb, "_try_wikipedia", lambda t: None)
    monkeypatch.setattr(fb, "_try_fandom",
                        lambda t: (list(VINLAND_FANDOM), "https://x.fandom.com/wiki/Volume_1"))
    res = fb.resolve_fallback("Whatever")
    assert res["source"] == "fandom"
    assert res["source_url"] == "https://x.fandom.com/wiki/Volume_1"


def test_resolve_returns_none_when_no_source_has_data(monkeypatch):
    monkeypatch.setattr(fb, "_try_wikipedia", lambda t: None)
    monkeypatch.setattr(fb, "_try_fandom", lambda t: None)
    assert fb.resolve_fallback("Whatever") is None


# --- resolve_fallback: gating --------------------------------------------------------

def test_resolve_gates_fallback_against_own_source_rows(monkeypatch):
    # A structurally-valid Wikipedia set passes the gate (Experiment A in the docstring).
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: (list(VINLAND_WIKI), "https://en.wikipedia.org/wiki/X"))
    res = fb.resolve_fallback("Whatever")
    assert res["qualified"] is True
    assert res["gate_reason"] == ""


def test_resolve_gate_failure_does_not_fall_through_to_next_source(monkeypatch):
    # If Wikipedia returns a structurally-broken set (overlapping spans), the gate refuses and
    # resolve returns that refusal -- it does NOT then try Fandom for a better answer. A broken
    # Wikipedia mapping is not improved by also consulting Fandom; mixing sources would be
    # interpolation.
    broken = [
        {"number": 1, "chapterStart": "1", "chapterEnd": "5"},
        {"number": 2, "chapterStart": "4", "chapterEnd": "7"},  # overlaps vol 1
    ]
    fandom_called = []
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: (broken, "https://en.wikipedia.org/wiki/X"))
    monkeypatch.setattr(fb, "_try_fandom",
                        lambda t: fandom_called.append(t) or (VINLAND_FANDOM, "https://x.fandom.com/wiki/Volume_1"))
    res = fb.resolve_fallback("Whatever")
    assert res["source"] == "wikipedia"
    assert res["qualified"] is False
    assert "overlap" in res["gate_reason"]
    assert fandom_called == []  # gate failure is terminal, not a fall-through trigger


def test_resolve_refuses_inter_volume_gap_via_contiguity_guard(monkeypatch):
    # A fallback with an inter-volume gap in chapter space is refused. Vol1=1-3, vol2=8-10 leaves
    # chapters 4-7 unnamed -- a real published volume set tiles without such a gap. The gate's
    # coverage check CANNOT catch this on derived rows (the source never named 4-7, so they are
    # absent, not "stranded"). This is the documented residual (see fallback.py docstring), and
    # _volumes_are_contiguous closes it -- a fallback-specific shape guard, NOT a change to
    # Agent 1's gate.
    gapped = [
        {"number": 1, "chapterStart": "1", "chapterEnd": "3"},
        {"number": 2, "chapterStart": "8", "chapterEnd": "10"},
    ]
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: (gapped, "https://en.wikipedia.org/wiki/X"))
    res = fb.resolve_fallback("Whatever")
    assert res["qualified"] is False
    assert "not contiguous" in res["gate_reason"]


def test_contiguity_guard_accepts_fractional_endpoint():
    # vol1 ending at '16.5' followed by vol2 starting at '17' is contiguous (the .5 is a side
    # chapter of 16). Mirrors the real Vinland record's vol 2 (5-16.5) -> vol 3 (17-21.5).
    vols = [
        {"number": 1, "chapterStart": "1", "chapterEnd": "16.5"},
        {"number": 2, "chapterStart": "17", "chapterEnd": "21.5"},
    ]
    assert fb._volumes_are_contiguous(vols) is True


def test_contiguity_guard_refuses_overlap_too():
    # The gate's own span-overlap check (check 5) catches vol2 starting before vol1 ends, but
    # _volumes_are_contiguous is stricter on the gap side; verify it also flags the overlap case
    # as non-contiguous (start must == prev_end + 1, exactly).
    vols = [
        {"number": 1, "chapterStart": "1", "chapterEnd": "5"},
        {"number": 2, "chapterStart": "4", "chapterEnd": "7"},  # overlaps + non-contiguous
    ]
    assert fb._volumes_are_contiguous(vols) is False


def test_contiguity_guard_passes_single_volume():
    # One volume -> trivially contiguous (no adjacent pair to check).
    assert fb._volumes_are_contiguous([{"number": 1, "chapterStart": "1", "chapterEnd": "5"}]) is True


# --- record provenance threading ------------------------------------------------------

def test_build_record_threads_fallback_source_through():
    res = {"source": "wikipedia", "source_url": "https://en.wikipedia.org/wiki/X",
           "volumes": VINLAND_WIKI, "qualified": True, "gate_reason": ""}
    rec = record.build_record(
        "Vinland Saga", "01J76XY7FQY59WRK2YWX5T4E5N", "xui1JrAT", "Vinland-Saga",
        res["volumes"], False, "2026-07-30T00:00:00Z", True, res["qualified"], res["gate_reason"],
        source=res["source"], source_url=res["source_url"])
    assert rec["source"] == "wikipedia"
    assert rec["sourceUrl"] == "https://en.wikipedia.org/wiki/X"
    assert rec["qualified"] is True


def test_build_record_default_source_is_comick():
    # An existing call site (no source args) -> comick/None. Every pre-fallback record reads this way.
    rec = record.build_record("X", "id", "hid", "slug", [], False, "t", True, True, "")
    assert rec["source"] == "comick"
    assert rec["sourceUrl"] is None


# --- build_fallback_record: the HARD SCOPE FENCE (never overwrite qualified:true) ----

def test_fence_never_overwrites_qualified_record(monkeypatch):
    # The contract's HARD SCOPE FENCE: a record with qualified:true is NEVER touched, regardless
    # of what the fallback finds. Precedence comick > wikipedia > fandom is absolute here.
    existing = {"seriesTitle": "Bleach", "qualified": True, "volumes": [{"number": 1}]}
    # Wikipedia WOULD resolve if asked -- but the fence must short-circuit before that.
    wiki_called = []
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: wiki_called.append(t) or (VINLAND_WIKI, "https://en.wikipedia.org/wiki/X"))
    rec, action, _ = fb.build_fallback_record(
        "Bleach", existing, "hid", "slug", "wid", "2026-07-30T00:00:00Z")
    assert action == "skipped_qualified"
    assert rec is None
    assert wiki_called == []  # fence short-circuits; fallback never even consulted


def test_fence_refuses_numbering_quirk_series(monkeypatch):
    # NUMBERING-QUIRK BLINDNESS (Task 4): a series whose existing record carries
    # numberingQuirk:true is refused at the fence, BEFORE any fetch. The fallback gate feeds the
    # numbering-quirk check its own derived rows, which are always clean integers -- so it cannot
    # see the real series' fractional chapter origin. A fallback for such a series would publish
    # ranges that are internally consistent but mismatched to WeebCentral's actual numbering.
    # Refusing is the honest call; Battle Angel Alita / Soul Eater are the two real cases.
    existing = {"seriesTitle": "Battle Angel Alita", "qualified": False,
                "numberingQuirk": True,
                "gateReason": "numbering quirk (fractional chapter origin)"}
    # Wikipedia WOULD resolve and the fallback gate WOULD pass (derived rows are clean) -- but the
    # fence must short-circuit before that happens.
    wiki_called = []
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: wiki_called.append(t) or (VINLAND_WIKI, "https://en.wikipedia.org/wiki/X"))
    rec, action, _ = fb.build_fallback_record(
        "Battle Angel Alita", existing, "hid", "slug", "wid", "2026-07-30T00:00:00Z")
    assert action == "skipped_numbering_quirk"
    assert rec is None
    assert wiki_called == []  # fence short-circuits; no fetch attempted


def test_fence_applies_to_unqualified_record(monkeypatch):
    # An unqualified record (Comick left a gap) -> fallback is attempted and, if it gates clean,
    # a qualified fallback record is written with provenance.
    existing = {"seriesTitle": "Vinland Saga", "qualified": False,
                "gateReason": "9 chapter(s) in no volume (first: 210)"}
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: (list(VINLAND_WIKI), "https://en.wikipedia.org/wiki/List_of_Vinland_Saga_chapters"))
    rec, action, _ = fb.build_fallback_record(
        "Vinland Saga", existing, "xui1JrAT", "Vinland-Saga",
        "01J76XY7FQY59WRK2YWX5T4E5N", "2026-07-30T00:00:00Z")
    assert action == "fallback_qualified"
    assert rec["qualified"] is True
    assert rec["source"] == "wikipedia"
    assert "List_of_Vinland_Saga_chapters" in rec["sourceUrl"]


def test_fence_applies_when_no_existing_record(monkeypatch):
    # A series with no prior record at all (first-seen via fallback) -> None existing is eligible.
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: (list(VINLAND_WIKI), "https://en.wikipedia.org/wiki/X"))
    rec, action, _ = fb.build_fallback_record(
        "New Series", None, "hid", "slug", "wid", "2026-07-30T00:00:00Z")
    assert action == "fallback_qualified"
    assert rec["source"] == "wikipedia"


def test_no_fallback_data_returns_none_action(monkeypatch):
    monkeypatch.setattr(fb, "_try_wikipedia", lambda t: None)
    monkeypatch.setattr(fb, "_try_fandom", lambda t: None)
    rec, action, _ = fb.build_fallback_record(
        "Obscure", None, "hid", "slug", "wid", "2026-07-30T00:00:00Z")
    assert action == "no_fallback_data"
    assert rec is None


def test_gate_refusal_writes_unqualified_record_with_provenance(monkeypatch):
    # A fallback that the gate refuses is still written (unqualified), with the fallback volumes
    # + provenance, exactly as Comick's path writes unqualified records. The data stays
    # inspectable; the app shows the flat list.
    broken = [
        {"number": 1, "chapterStart": "1", "chapterEnd": "5"},
        {"number": 2, "chapterStart": "4", "chapterEnd": "7"},  # overlap -> gate refuses
    ]
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: (broken, "https://en.wikipedia.org/wiki/X"))
    rec, action, _ = fb.build_fallback_record(
        "X", {"qualified": False}, "hid", "slug", "wid", "2026-07-30T00:00:00Z")
    assert action == "fallback_unqualified"
    assert rec["qualified"] is False
    assert rec["source"] == "wikipedia"  # provenance preserved even on refusal
    assert "overlap" in rec["gateReason"]


# --- per-volume synopses: separated out, never inlined into the record ---------------

def test_synopses_not_inlined_into_record_volumes(monkeypatch):
    # The HARD rule (Hemanth Correction 3): synopses must NOT ride along in the record's volumes
    # list -- a blurb is 500-1500 chars and One Piece has 117 volumes; inlining would bloat the
    # shelf payload. build_fallback_record returns synopses SEPARATELY; the record's volumes carry
    # only number/chapterStart/chapterEnd (+ optional name).
    fandom_vols_with_synopsis = [
        {"number": 1, "chapterStart": "1", "chapterEnd": "5", "name": "First",
         "synopsis": "A long publisher's blurb about volume one." * 20},
        {"number": 2, "chapterStart": "6", "chapterEnd": "10", "name": "Second",
         "synopsis": "Another long blurb about volume two." * 20},
    ]
    monkeypatch.setattr(fb, "_try_wikipedia", lambda t: None)
    monkeypatch.setattr(fb, "_try_fandom",
                        lambda t: (fandom_vols_with_synopsis, "https://x.fandom.com/wiki/Volume_1"))
    rec, action, synopses = fb.build_fallback_record(
        "Mushishi", {"qualified": False}, "hid", "slug", "wid", "2026-07-30T00:00:00Z")
    assert action == "fallback_qualified"
    # The record's volumes must NOT carry a synopsis key on ANY entry.
    assert all("synopsis" not in v for v in rec["volumes"]), \
        "synopsis leaked into the record volumes -- it must be split out"
    # name + chapter fields survive the split.
    assert rec["volumes"][0] == {"number": 1, "chapterStart": "1", "chapterEnd": "5", "name": "First"}
    # Synopses returned separately, keyed by volume number, for sibling-file writing.
    assert set(synopses.keys()) == {1, 2}
    assert "volume one" in synopses[1]


def test_synopses_empty_for_wikipedia_source(monkeypatch):
    # Wikipedia volume dicts carry no synopsis key (Wikipedia pages have no summary section).
    # split_synopses is a no-op: synopses is empty, record volumes are unchanged.
    wiki_vols = [{"number": 1, "chapterStart": "1", "chapterEnd": "5"}]
    monkeypatch.setattr(fb, "_try_wikipedia",
                        lambda t: (list(wiki_vols), "https://en.wikipedia.org/wiki/X"))
    rec, action, synopses = fb.build_fallback_record(
        "Vinland Saga", {"qualified": False}, "hid", "slug", "wid", "2026-07-30T00:00:00Z")
    assert action == "fallback_qualified"
    assert synopses == {}
    assert rec["volumes"] == wiki_vols


def test_write_synopsis_sibling_only_writes_when_non_empty(tmp_path, monkeypatch):
    # The sibling file is written ONLY when at least one volume has a blurb. A series with no
    # blurbs gets no file -- absence of the file is a reliable "no blurbs" signal.
    import comick_volume_db.record as rec_mod
    monkeypatch.setattr(rec_mod, "DB_DIR", tmp_path)
    # Empty -> no file written, returns None.
    assert rec_mod.write_synopsis_sibling("WID1", {}) is None
    assert not (tmp_path / "WID1.synopsis.json").exists()
    # Non-empty -> file written at db/<id>.synopsis.json.
    path = rec_mod.write_synopsis_sibling("WID2", {1: "blurb one", 3: "blurb three"})
    assert path == tmp_path / "WID2.synopsis.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["weebcentralId"] == "WID2"
    assert data["synopses"] == {"1": "blurb one", "3": "blurb three"}  # keys stringified for JSON




@pytest.mark.live
def test_live_vinland_saga_resolves_via_wikipedia_and_passes_gate():
    """The contract's proof case. Vinland Saga: 29 volumes, vol 29 = chapters 210-220, via
    Wikipedia {{Graphic novel list}}. The gate must accept it (the 210-218 hole that defeated
    Comick is filled by Wikipedia's vol 29 range)."""
    res = fb.resolve_fallback("Vinland Saga")
    assert res is not None, "Vinland Saga should resolve via Wikipedia"
    assert res["source"] == "wikipedia"
    assert res["qualified"] is True, f"gate refused: {res['gate_reason']!r}"
    assert len(res["volumes"]) == 29
    vol29 = [v for v in res["volumes"] if v["number"] == 29][0]
    assert vol29 == {"number": 29, "chapterStart": "210", "chapterEnd": "220"}
    assert "List_of_Vinland_Saga_chapters" in res["source_url"]
