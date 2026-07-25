import pytest

from comick_volume_db import comick_client


def test_pick_best_match_prefers_exact_title():
    results = [{"hid": "x", "title": "One Piece: Party"}, {"hid": "y", "title": "One Piece"}]
    assert comick_client.pick_best(results, "one piece")["hid"] == "y"


def test_pick_best_falls_back_to_first_when_no_exact():
    results = [{"hid": "a", "title": "Berserk of Gluttony"}, {"hid": "b", "title": "Berserk (Extra)"}]
    assert comick_client.pick_best(results, "berserk")["hid"] == "a"


@pytest.mark.live
def test_live_search_and_chapters():
    hid = comick_client.search("death note")
    assert hid
    chapters = comick_client.fetch_chapters(hid)
    assert any(c.get("vol") for c in chapters)
