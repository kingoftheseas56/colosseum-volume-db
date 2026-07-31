import json
import pathlib

from comick_volume_db.volume_builder import (
    _fmt, gate, group_volumes, majority_assign, numbering_is_oddball)

FIX = pathlib.Path(__file__).parent / "fixtures"


def _chapters(slug):
    return json.loads((FIX / f"comick_chapters_{slug}.json").read_text(encoding="utf-8"))["chapters"]


def _mha_chapters():
    return json.loads((FIX / "mha_all_lang_pairs.json").read_text(encoding="utf-8"))["chapters"]


def _labels(assign):
    """majority_assign keys are sort keys, not labels -- read them back as the source wrote them."""
    return {_fmt(k): v for k, v in assign.items()}


def _span_volumes(numbers, per=10):
    """Volumes each holding `per` consecutive chapters, spans ascending and non-overlapping."""
    return [{"number": n, "chapterStart": str(n * per), "chapterEnd": str(n * per + per - 1)}
            for n in numbers]


def _rows_for(volumes):
    """Source rows that exactly fill the given spans -- nothing unmapped, nothing missing."""
    return [{"chap": str(c), "vol": str(v["number"])}
            for v in volumes
            for c in range(int(v["chapterStart"]), int(v["chapterEnd"]) + 1)]


def test_death_note_volume_ranges():
    vols = group_volumes(_chapters("death-note"))
    by_num = {v["number"]: v for v in vols}
    assert by_num[1]["chapterStart"] == "1" and by_num[1]["chapterEnd"] == "7"
    assert by_num[2]["chapterStart"] == "8" and by_num[2]["chapterEnd"] == "16"
    assert [v["number"] for v in vols] == sorted(v["number"] for v in vols)


def test_bleach_complete_74_volumes():
    vols = group_volumes(_chapters("bleach"))
    numbers = [v["number"] for v in vols]
    assert numbers == list(range(1, 75))  # 1..74, no gaps
    assert vols[0]["chapterStart"] == "1"


def test_fractional_chapter_tail_preserved():
    chapters = [{"vol": "1", "chap": "1"}, {"vol": "1", "chap": "2"},
                {"vol": "2", "chap": "2.5"}, {"vol": "2", "chap": "3"}]
    vols = group_volumes(chapters)
    v2 = next(v for v in vols if v["number"] == 2)
    assert v2["chapterStart"] == "2.5" and v2["chapterEnd"] == "3"


def test_duplicate_scanlation_rows_deduped():
    chapters = [{"vol": "1", "chap": "1"}, {"vol": "1", "chap": "1"}, {"vol": "1", "chap": "2"}]
    vols = group_volumes(chapters)
    assert vols == [{"number": 1, "chapterStart": "1", "chapterEnd": "2"}]


def test_oddball_numbering_detection():
    assert numbering_is_oddball(_chapters("berserk")) is True      # chapters 0.01, 0.02...
    assert numbering_is_oddball(_chapters("death-note")) is False  # clean integers 1,2,3...


def test_subchapter_labels_are_ordinals_not_fractions():
    # Real Bleach rows: 315.1-315.9 are volume 36, 315.10-315.12 are volume 37. Read as floats,
    # "315.10" == "315.1" -- the two pooled into one vote and chapter 315.10 vanished.
    vols = group_volumes(_chapters("bleach"))
    by_num = {v["number"]: v for v in vols}
    assert (by_num[36]["chapterStart"], by_num[36]["chapterEnd"]) == ("315.1", "315.9")
    assert (by_num[37]["chapterStart"], by_num[37]["chapterEnd"]) == ("315.10", "322")


def test_no_source_chapter_is_dropped_by_key_collision():
    rows = _chapters("bleach")
    tagged = {str(c["chap"]) for c in rows if c.get("chap") and c.get("vol")}
    assert "315.10" in tagged and "315.1" in tagged            # both really are in the source
    assert set(_labels(majority_assign(rows))) == tagged       # and both survive the vote


def test_fmt_round_trips_padded_subchapter_label():
    # "110.30" is the 30th sub-chapter of 110, not 110.3 -- the app joins these labels
    # against WeebCentral's, so a drifted label is a broken join.
    vols = group_volumes([{"vol": "9", "chap": "110.30"}, {"vol": "9", "chap": "110.5"}])
    assert (vols[0]["chapterStart"], vols[0]["chapterEnd"]) == ("110.5", "110.30")
    assert group_volumes([{"vol": "3", "chap": "25.02"}])[0]["chapterStart"] == "25.02"


def test_majority_assign_resolves_stray_tags():
    # ch 7: two rows say vol 1, one stray row says vol 2 -> majority wins
    chapters = [
        {"chap": "7", "vol": "1"}, {"chap": "7", "vol": "1"}, {"chap": "7", "vol": "2"},
        {"chap": "8", "vol": "2"},
    ]
    assign = _labels(majority_assign(chapters))
    assert assign["7"] == 1
    assert assign["8"] == 2


def test_majority_assign_tie_leaves_chapter_unassigned():
    # A dead tie means the sources contradict each other. Guessing a winner would invent a
    # boundary; dropping the chapter leaves a hole the gate can see.
    chapters = [{"chap": "7", "vol": "1"}, {"chap": "7", "vol": "2"}, {"chap": "8", "vol": "2"}]
    assign = _labels(majority_assign(chapters))
    assert "7" not in assign
    assert assign["8"] == 2


def test_majority_assign_is_monotonic_over_chapters():
    # Naruto shape: one uploader put 459.3 in volume 50 while its neighbours are all volume 49.
    # Physical volumes are sequential, so a later chapter is never in an earlier book.
    chapters = [{"chap": str(c), "vol": "49"} for c in range(454, 464) for _ in range(4)]
    chapters += [{"chap": "459.3", "vol": "50"}]
    chapters += [{"chap": str(c), "vol": "50"} for c in range(464, 474) for _ in range(4)]
    assign = _labels(majority_assign(chapters))
    assert assign["459.3"] == 49
    assert assign["463"] == 49 and assign["464"] == 50


def test_stray_tag_moves_but_the_consensus_never_does():
    # Berserk shape, the mirror image of Naruto's: chapter 106.5 carries ONE row tagging it
    # volume 13 while 106 and 107 carry eleven rows each for volume 15. The stray chapter joins
    # its neighbours -- the sixteen well-attested chapters around it must not budge.
    chapters = [{"chap": str(c), "vol": "15"} for c in range(100, 111) for _ in range(11)]
    chapters += [{"chap": "106.5", "vol": "13"}]
    assign = _labels(majority_assign(chapters))
    assert assign["106.5"] == 15
    assert {v for k, v in assign.items() if k != "106.5"} == {15}


def test_a_run_that_stays_out_of_order_never_reaches_the_shelf():
    # Two adjacent mis-tags are not a lone stray, so nothing corrects them. The volumes then
    # overlap, and the gate refuses -- the series falls back to a chapter list rather than
    # having its well-attested chapters silently reshaped to force an order.
    chapters = [{"chap": str(c), "vol": "1"} for c in (1, 2, 3)]
    chapters += [{"chap": str(c), "vol": "3"} for c in (4, 5)]      # both mis-tagged
    chapters += [{"chap": str(c), "vol": "2"} for c in (6, 7)]
    vols = group_volumes(chapters)
    assert {v["number"] for v in vols} == {1, 2, 3}                 # nothing dropped or invented
    ok, reason = gate(vols, False, chapters)
    assert not ok and "overlap" in reason and "2" in reason


def test_monotonic_correction_never_invents_an_assignment():
    # 8 is untagged by every source; correcting 9's stray tag must not conjure a volume for 8.
    chapters = [{"chap": "7", "vol": "1"}, {"chap": "8", "vol": None}, {"chap": "9", "vol": "2"},
                {"chap": "10", "vol": "1"}, {"chap": "10", "vol": "1"}]
    assign = _labels(majority_assign(chapters))
    assert "8" not in assign
    assert assign["9"] == 1                                    # pulled back to its neighbours


def test_group_from_majority_mha_all_language_is_complete():
    chapters = _mha_chapters()
    vols = group_volumes(chapters)
    numbers = [v["number"] for v in vols]
    assert numbers == list(range(1, 43))          # 1..42, unbroken
    assert vols[0]["chapterStart"] == "1"          # vol 1 starts at ch 1


def test_gate_accepts_contiguous_run_from_1():
    vols = _span_volumes(range(1, 43))
    ok, reason = gate(vols, False, _rows_for(vols))
    assert ok, reason


def test_gate_accepts_volume_zero_start():
    vols = _span_volumes(range(0, 13))
    ok, _ = gate(vols, False, _rows_for(vols))
    assert ok                                       # Death Note: vol 0..12


def test_gate_rejects_mid_run_gap():
    vols = _span_volumes((1, 19, 38))
    ok, reason = gate(vols, False, _rows_for(vols))
    assert not ok and "gap" in reason               # en-only MHA shape


def test_gate_rejects_late_start():
    vols = _span_volumes(range(25, 39))
    ok, reason = gate(vols, False, _rows_for(vols))
    assert not ok and "25" in reason                # a shelf that opens at volume 25 is not a shelf


def test_gate_rejects_overlapping_spans():
    # Naruto shape: a stray row dragged volume 50's start back inside volume 49's span. The
    # volume numbers still read 1..50, so only a span check can catch it.
    clean = _span_volumes(range(1, 49))
    vols = clean + [{"number": 49, "chapterStart": "490", "chapterEnd": "499"},
                    {"number": 50, "chapterStart": "495", "chapterEnd": "509"}]
    rows = _rows_for(clean) + [{"chap": str(c), "vol": "49"} for c in range(490, 510)]
    ok, reason = gate(vols, False, rows)
    assert not ok and "overlap" in reason and "49" in reason


def test_gate_rejects_chapters_stranded_between_volumes():
    # Vinland Saga shape: nine whole chapters carry no volume tag in ANY language, so the volume
    # after them starts past the hole -- inside an otherwise perfect 1..29. The chapter run here
    # is unbroken from end to end, so the stranding is the only thing under test.
    clean = _span_volumes(range(1, 28), per=7)                     # volumes 1..27, chapters 7..195
    vols = clean + [{"number": 28, "chapterStart": "196", "chapterEnd": "203"},
                    {"number": 29, "chapterStart": "213", "chapterEnd": "214"}]
    rows = _rows_for(clean)
    rows += [{"chap": str(c), "vol": "28"} for c in range(196, 204)]
    rows += [{"chap": str(c), "vol": None} for c in range(204, 213) for _ in range(4)]  # untagged
    rows += [{"chap": str(c), "vol": "29"} for c in (213, 214)]
    ok, reason = gate(vols, False, rows)
    assert not ok and "no volume" in reason
    assert "9 chapter" in reason and "204" in reason


def test_gate_rejects_chapters_swallowed_inside_a_volume():
    # The sparse-anchor case: volume 2 is tagged on chapters 11 and 20 ONLY, so its span stretches
    # across 12-19 -- eight whole chapters nobody tagged, silently absorbed. The volume numbers and
    # the seams between spans both look perfect, so only a coverage check can see it.
    rows = [{"chap": str(c), "vol": "1"} for c in range(1, 11)]
    rows += [{"chap": "11", "vol": "2"}]
    # each untagged chapter arrives on several rows, one per language -- the count in the reason
    # is chapters, not rows
    rows += [{"chap": str(c), "vol": None} for c in range(12, 20) for _ in range(5)]
    rows += [{"chap": "20", "vol": "2"}]
    rows += [{"chap": str(c), "vol": "3"} for c in range(21, 31)]

    vols = group_volumes(rows)
    assert [(v["number"], v["chapterStart"], v["chapterEnd"]) for v in vols] == [
        (1, "1", "10"), (2, "11", "20"), (3, "21", "30")]              # spans look flawless
    ok, reason = gate(vols, False, rows)
    assert not ok and "no volume" in reason
    assert "8 chapter" in reason and "12" in reason


def test_gate_ignores_chapters_outside_the_shelf():
    # Below the first volume: Bleach's untagged chapter 0 one-shot, genuinely in no book.
    # Above the last volume: the uncollected tail of an ongoing series, which the app shows as
    # "Latest chapters". Neither is a hole in the shelf.
    vols = _span_volumes(range(1, 6))
    rows = _rows_for(vols)
    rows += [{"chap": "0", "vol": None}, {"chap": "5", "vol": None}]   # before volume 1 starts
    rows += [{"chap": str(c), "vol": None} for c in range(60, 70)]     # after volume 5 ends
    ok, reason = gate(vols, False, rows)
    assert ok, reason


def test_gate_allows_an_untagged_extra_between_back_to_back_volumes():
    # Real Bleach: volume 19 is 159-168 and volume 20 is 169-178 -- back to back, every whole
    # chapter in a book. The only thing "between" them is one untagged 168.5 extra, which was
    # never bound into either volume. That is not a hole in the shelf.
    clean = _span_volumes(range(1, 19), per=8)                     # a clean run up to volume 18
    vols = clean + [{"number": 19, "chapterStart": "159", "chapterEnd": "168"},
                    {"number": 20, "chapterStart": "169", "chapterEnd": "178"}]
    rows = _rows_for(clean) + [{"chap": str(c), "vol": "19"} for c in range(159, 169)]
    rows += [{"chap": "168.5", "vol": None}]                       # exists, untagged, an extra
    rows += [{"chap": str(c), "vol": "20"} for c in range(169, 179)]
    ok, reason = gate(vols, False, rows)
    assert ok, reason


def test_gate_allows_a_subchapter_between_volumes():
    # 432.5 sits after one volume ends and IS the next volume's first chapter -- a real Bleach
    # shape, and not a hole.
    clean = _span_volumes(range(1, 49))
    vols = clean + [{"number": 49, "chapterStart": "490", "chapterEnd": "499"},
                    {"number": 50, "chapterStart": "499.5", "chapterEnd": "509"}]
    rows = _rows_for(clean) + [{"chap": str(c), "vol": "49"} for c in range(490, 500)]
    rows += [{"chap": "499.5", "vol": "50"}]
    rows += [{"chap": str(c), "vol": "50"} for c in range(500, 510)]
    ok, reason = gate(vols, False, rows)
    assert ok, reason


def test_gate_rejects_empty():
    # No volumes -> not a shelf, regardless of the numbering flag.
    assert not gate([], False, [])[0]
    assert not gate([], True, [])[0]


def test_gate_accepts_fractional_origin_when_structurally_sound():
    # FRACTIONAL-ORIGIN FIX (2026-07-30): a numbering_quirk=True series is no longer
    # blanket-refused. Berserk's prologue (0.001-0.14 bound into vols 1-5) is a legitimate
    # published numbering scheme. The structural checks (run / span-overlap / coverage) are the
    # guard; the flag alone is not a disqualifier. This series has a clean fractional start but
    # tiles correctly and covers its whole chapters -> it qualifies.
    vols = [{"number": 1, "chapterStart": "0.01", "chapterEnd": "5"},
            {"number": 2, "chapterStart": "6", "chapterEnd": "10"}]
    rows = [{"chap": "0.01", "vol": "1"}]
    rows += [{"chap": str(c), "vol": "1"} for c in range(1, 6)]
    rows += [{"chap": str(c), "vol": "2"} for c in range(6, 11)]
    ok, reason = gate(vols, True, rows)
    assert ok, f"fractional-origin series should qualify when structurally sound: {reason}"


def test_gate_flag_ignored_for_refusal_but_still_passed_through():
    # The gate no longer refuses on numbering_quirk=True, but it still ACCEPTS the parameter
    # (callers pass it; records store it as metadata). Same volumes + rows qualify whether the
    # flag is True or False -- the structural checks decide, not the flag.
    vols = [{"number": 1, "chapterStart": "1", "chapterEnd": "5"}]
    rows = [{"chap": str(c), "vol": "1"} for c in range(1, 6)]
    assert gate(vols, True, rows)[0] is True
    assert gate(vols, False, rows)[0] is True
