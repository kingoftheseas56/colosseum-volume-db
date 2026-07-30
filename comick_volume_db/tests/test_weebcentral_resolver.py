"""Tests for weebcentral_client: the similarity-verified resolver + chapter-list helpers.

Fixtures are RECORDED from real WeebCentral /search/simple responses (captured 2026-07-30) so the
tests run offline and deterministically. They lock down the wrong-series-match regression the
"Beet the Vandel Buster" -> "Buster-Keel" bug established: a title WeebCentral does not carry
must return (None, None), never a different series that shares a word.

The similarity threshold (MATCH_THRESHOLD = 0.8) is itself tested: every known-good seed
resolves above it, every known-bad wrong-series match falls below it.
"""
import json
import pathlib

import pytest

from comick_volume_db import weebcentral_client as wc

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "weebcentral_search.json"


def _load_fixtures():
    """Recorded search results: {query: [{id, slug}, ...]}. Captured live 2026-07-30."""
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _fixture_html(matches):
    """Reconstruct a minimal /search/simple HTML body from recorded (id, slug) pairs, so the
    SERIES_RE parser in resolve() is exercised against real-markup-shaped input."""
    links = "".join(f'<a href="https://weebcentral.com/series/{m["id"]}/{m["slug"]}">{m["slug"]}</a>'
                    for m in matches)
    return f"<div>{links}</div>"


# --- _verify_match: the similarity rule ------------------------------------------------

def test_verify_match_exact_slug_is_1():
    assert wc._verify_match("Vinland Saga", "Vinland-Saga") == 1.0


def test_verify_match_suffix_slug_passes_threshold():
    # "my-hero-academia-color" is a legitimate series page (the color edition). It MUST clear
    # the threshold -- this is the lowest-scoring known-good seed (0.848), and the threshold was
    # set to pass it.
    assert wc._verify_match("My Hero Academia", "my-hero-academia-color") >= wc.MATCH_THRESHOLD


def test_verify_match_wrong_series_below_threshold():
    # The four known wrong-series traps must ALL fall below the threshold.
    assert wc._verify_match("Beet the Vandel Buster", "Buster-Keel") < wc.MATCH_THRESHOLD
    assert wc._verify_match("Vinland Saga", "Sand-Land") < wc.MATCH_THRESHOLD
    assert wc._verify_match("Naruto", "Boruto") < wc.MATCH_THRESHOLD
    assert wc._verify_match("Bleach", "Bleach-Black") < wc.MATCH_THRESHOLD


def test_verify_match_empty_returns_zero():
    assert wc._verify_match("", "Anything") == 0.0
    assert wc._verify_match("Anything", "") == 0.0


# --- parse_all_series_ids: extracts ALL hits from search HTML --------------------------

def test_parse_all_extracts_every_hit():
    html = ('<a href="https://weebcentral.com/series/01J76XY7FQY59WRK2YWX5T4E5N/Vinland-Saga">x</a>'
            '<a href="https://weebcentral.com/series/01J76XYAVN78JCN1M2BAZ2FFM6/Sand-Land">y</a>')
    hits = wc.parse_all_series_ids(html)
    assert hits == [("01J76XY7FQY59WRK2YWX5T4E5N", "Vinland-Saga"),
                    ("01J76XYAVN78JCN1M2BAZ2FFM6", "Sand-Land")]


def test_parse_all_returns_empty_when_no_hits():
    assert wc.parse_all_series_ids("<div>no results</div>") == []


# --- resolve (monkeypatched to the recorded fixtures): the regression table -------------

@pytest.mark.parametrize("query", [
    "Vinland Saga", "Bleach", "Toriko", "Claymore", "Angel Heart", "My Hero Academia",
])
def test_resolve_known_good_titles_return_correct_series(monkeypatch, query):
    """The five+ known-good titles resolve to their CORRECT series, not a fuzzy wrong-series hit.
    Uses recorded search fixtures (no network)."""
    fixtures = _load_fixtures()
    monkeypatch.setattr(wc.requests, "post", lambda url, **kw: _FakeResp(_fixture_html(fixtures[query])))

    sid, slug = wc.resolve(query)
    assert sid is not None, f"{query!r} should resolve"
    # The returned slug must be the requested series, verified -- not a noise hit from the list.
    assert wc._verify_match(query, slug) >= wc.MATCH_THRESHOLD
    # Spot-check two well-known ids against the db records (the ids the app keys on):
    if query == "Vinland Saga":
        assert sid == "01J76XY7FQY59WRK2YWX5T4E5N" and slug == "Vinland-Saga"
    if query == "Bleach":
        assert sid == "01J76XY7E4JCPK14V53BVQWD9Y" and slug == "Bleach"


def test_resolve_nonsense_returns_none(monkeypatch):
    """A title WeebCentral has zero results for -> (None, None)."""
    fixtures = _load_fixtures()
    monkeypatch.setattr(wc.requests, "post", lambda url, **kw: _FakeResp(_fixture_html(fixtures["zzz nonsense zzz"])))
    assert wc.resolve("zzz nonsense zzz") == (None, None)


def test_resolve_carried_only_as_wrong_series_returns_none(monkeypatch):
    """THE REGRESSION: 'Beet the Vandel Buster' is NOT carried by WeebCentral -- its only search
    hit is 'Buster-Keel', a different manga sharing one word. resolve MUST return (None, None),
    NOT Buster-Keel's id. Records are keyed by WeebCentral id; returning Buster-Keel would write
    Beet's volumes into Buster-Keel's record -- wrong data on the wrong series, passing every
    structural gate because the numbers are self-consistent. This is the bug the fix refuses."""
    fixtures = _load_fixtures()
    monkeypatch.setattr(wc.requests, "post", lambda url, **kw: _FakeResp(_fixture_html(fixtures["Beet the Vandel Buster"])))
    assert wc.resolve("Beet the Vandel Buster") == (None, None)


def test_resolve_picks_best_above_threshold_among_noise(monkeypatch):
    """When the search returns the correct series alongside noise, resolve picks the correct one.
    'Vinland Saga' returns [Vinland-Saga, Sand-Land]; resolve returns Vinland-Saga, not Sand-Land."""
    fixtures = _load_fixtures()
    monkeypatch.setattr(wc.requests, "post", lambda url, **kw: _FakeResp(_fixture_html(fixtures["Vinland Saga"])))
    sid, slug = wc.resolve("Vinland Saga")
    assert slug == "Vinland-Saga"  # not Sand-Land (the noise hit)


# --- chapter-list helpers (pure-logic shape; live tests cover the endpoint) -------------

def test_max_chapter_served_none_on_404_page(monkeypatch):
    # WeebCentral serves its 404 page at HTTP 200; detect by content markers.
    monkeypatch.setattr(wc, "fetch_chapter_list", lambda sid: '<html><link rel="canonical" href="https://weebcentral.com/404">')
    assert wc.max_chapter_served("anysid") is None


def test_max_chapter_served_extracts_whole_max(monkeypatch):
    html = ('<a href="/chapters/abc">Chapter 220</a>'
            '<a href="/chapters/def">Chapter 221</a>'
            '<a href="/chapters/ghi">Chapter 219.5</a>')  # side chapter ignored
    monkeypatch.setattr(wc, "fetch_chapter_list", lambda sid: html)
    assert wc.max_chapter_served("anysid") == 221


def test_max_chapter_served_none_when_markup_has_no_chapter_numbers(monkeypatch):
    # Toriko-class markup: chapter links present but no 'Chapter N' text extractable. The series
    # is UNTESTABLE by this function -> None. A caller must NOT substitute a link count.
    html = '<a href="/chapters/01abc" class="flex">x</a><a href="/chapters/01def" class="flex">y</a>'
    monkeypatch.setattr(wc, "fetch_chapter_list", lambda sid: html)
    assert wc.max_chapter_served("anysid") is None


class _FakeResp:
    """Minimal stand-in for requests.Response for the search endpoint."""
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        pass
