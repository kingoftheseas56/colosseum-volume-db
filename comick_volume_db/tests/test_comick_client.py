import pytest

from comick_volume_db import comick_client


def test_pick_best_match_prefers_exact_title():
    results = [{"hid": "x", "title": "One Piece: Party"}, {"hid": "y", "title": "One Piece"}]
    assert comick_client.pick_best(results, "one piece")["hid"] == "y"


def test_pick_best_falls_back_to_first_when_no_exact():
    results = [{"hid": "a", "title": "Berserk of Gluttony"}, {"hid": "b", "title": "Berserk (Extra)"}]
    assert comick_client.pick_best(results, "berserk")["hid"] == "a"


# The half ported from the C++ client (see the SHARED RULE note in comick_client.py):
# a candidate whose own `title` is a different spelling still wins if any of its
# md_titles is an exact normalised hit.
def test_pick_best_matches_on_md_titles_when_title_differs():
    results = [
        {"hid": "a", "title": "Vinland Saga: Side Story"},
        {"hid": "b", "title": "03-vinland-saga",
         "md_titles": [{"title": "ヴィンランド・サガ"}, {"title": "Vinland Saga"}]},
    ]
    assert comick_client.pick_best(results, "Vinland Saga")["hid"] == "b"


def test_pick_best_prefers_earlier_candidate_when_both_match():
    # Result order still decides between two exact hits — the window is a ranking.
    results = [
        {"hid": "a", "title": "Bleach"},
        {"hid": "b", "title": "Bleach (Digital Colored)", "md_titles": [{"title": "Bleach"}]},
    ]
    assert comick_client.pick_best(results, "bleach")["hid"] == "a"


def test_pick_best_ignores_a_candidate_with_no_title():
    # str(None) used to normalise to "none", so a titleless result matched a series
    # actually called "None". `if name` in _names() drops it instead.
    results = [{"hid": "a"}, {"hid": "b", "title": "None"}]
    assert comick_client.pick_best(results, "None")["hid"] == "b"


def test_norm_is_ascii_only_like_the_cpp_matchkey():
    # NOT str.isalnum(): the C++ matchKey() keeps a-z0-9 and nothing else, and "the
    # same normalisation" has to mean byte-for-byte the same or the two sides can
    # resolve a title to two different comics.
    assert comick_client._norm("Vinland Saga!") == "vinlandsaga"
    assert comick_client._norm("ヴィンランド・サガ") == ""
    assert comick_client._norm("Ao no Flag") == "aonoflag"
    assert comick_client._norm("20th Century Boys") == "20thcenturyboys"


def test_search_limit_matches_the_cpp_window():
    assert comick_client.SEARCH_LIMIT == 8


@pytest.mark.live
def test_live_search_and_chapters():
    hid = comick_client.search("death note")
    assert hid
    chapters = comick_client.fetch_chapters(hid)
    assert any(c.get("vol") for c in chapters)
