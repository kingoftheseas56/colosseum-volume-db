import pathlib

from comick_volume_db.weebcentral_client import parse_series_id

FIX = pathlib.Path(__file__).parent / "fixtures"


def test_parse_first_series_ulid():
    html = (FIX / "weebcentral_search_one_piece.html").read_text(encoding="utf-8")
    sid, slug = parse_series_id(html)
    assert sid == "01J76XY7E9FNDZ1DBBM6PBJPFK"
    assert slug == "One-Piece"


def test_parse_returns_none_on_no_match():
    assert parse_series_id("<html>no results</html>") == (None, None)
