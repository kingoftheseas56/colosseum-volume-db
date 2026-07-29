import json
import pathlib

from comick_volume_db.volume_builder import (
    gate, group_volumes, majority_assign, numbering_is_oddball)

FIX = pathlib.Path(__file__).parent / "fixtures"


def _chapters(slug):
    return json.loads((FIX / f"comick_chapters_{slug}.json").read_text(encoding="utf-8"))["chapters"]


def _mha_chapters():
    return json.loads((FIX / "mha_all_lang_pairs.json").read_text(encoding="utf-8"))["chapters"]


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


def test_majority_assign_resolves_stray_tags():
    # ch 7: two rows say vol 1, one stray row says vol 2 -> majority wins
    chapters = [
        {"chap": "7", "vol": "1"}, {"chap": "7", "vol": "1"}, {"chap": "7", "vol": "2"},
        {"chap": "8", "vol": "2"},
    ]
    assign = majority_assign(chapters)
    assert assign[7.0] == 1
    assert assign[8.0] == 2


def test_majority_assign_tie_takes_smaller_volume():
    chapters = [{"chap": "7", "vol": "1"}, {"chap": "7", "vol": "2"}]
    assert majority_assign(chapters)[7.0] == 1


def test_group_from_majority_mha_all_language_is_complete():
    chapters = _mha_chapters()
    vols = group_volumes(chapters)
    numbers = [v["number"] for v in vols]
    assert numbers == list(range(1, 43))          # 1..42, unbroken
    assert vols[0]["chapterStart"] == "1"          # vol 1 starts at ch 1


def test_gate_accepts_contiguous_run_from_1():
    vols = [{"number": n, "chapterStart": "1", "chapterEnd": "9"} for n in range(1, 43)]
    ok, reason = gate(vols, numbering_quirk=False)
    assert ok, reason


def test_gate_accepts_volume_zero_start():
    vols = [{"number": n, "chapterStart": "1", "chapterEnd": "9"} for n in range(0, 13)]
    ok, _ = gate(vols, numbering_quirk=False)
    assert ok                                       # Death Note: vol 0..12


def test_gate_rejects_mid_run_gap():
    vols = [{"number": n, "chapterStart": "1", "chapterEnd": "9"} for n in (1, 19, 38)]
    ok, reason = gate(vols, numbering_quirk=False)
    assert not ok and "gap" in reason               # en-only MHA shape


def test_gate_rejects_late_start():
    vols = [{"number": n, "chapterStart": "1", "chapterEnd": "9"} for n in range(25, 39)]
    ok, reason = gate(vols, numbering_quirk=False)
    assert not ok                                   # Vagabond record shape (starts at 25)


def test_gate_rejects_quirk_and_empty():
    assert not gate([{"number": 1, "chapterStart": "1", "chapterEnd": "9"}],
                    numbering_quirk=True)[0]        # Berserk-class
    assert not gate([], numbering_quirk=False)[0]
