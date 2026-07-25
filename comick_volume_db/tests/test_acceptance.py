import json
import pathlib

DB = pathlib.Path(__file__).parent.parent.parent / "db"


def _load_all():
    return [json.loads(p.read_text(encoding="utf-8")) for p in DB.glob("*.json")]


def _by_title(t):
    return next(r for r in _load_all() if r["seriesTitle"].lower() == t.lower())


def test_bleach_74_volumes():
    r = _by_title("Bleach")
    assert [v["number"] for v in r["volumes"]] == list(range(1, 75))


def test_death_note_vol1_is_1_to_7():
    r = _by_title("Death Note")
    v1 = next(v for v in r["volumes"] if v["number"] == 1)
    assert (v1["chapterStart"], v1["chapterEnd"]) == ("1", "7")


def test_chainsmoker_cat_present_and_8_volumes():
    r = _by_title("Chainsmoker Cat")
    assert len(r["volumes"]) == 8


def test_all_records_key_by_ulid_and_have_ranges():
    for r in _load_all():
        assert len(r["weebCentral"]["seriesId"]) == 26
        assert all(v["chapterStart"] and v["chapterEnd"] for v in r["volumes"])
