import json
import pathlib

from comick_volume_db.volume_builder import group_volumes, numbering_is_oddball

FIX = pathlib.Path(__file__).parent / "fixtures"


def _chapters(slug):
    return json.loads((FIX / f"comick_chapters_{slug}.json").read_text(encoding="utf-8"))["chapters"]


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
