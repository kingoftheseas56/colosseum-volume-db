"""Unit + live tests for the Fandom volume-chain walker.

The format table is the contract from the plan's Trap 1 -- every observed `chapters` value
form must parse, and a page with no chapters field must return None (negative control), never
a guess. The live tests pin the two known-good anchors: Mushishi (10 vols, vol 3 = 11-15) and
One Piece (vol 3 = 18 - 26).
"""
import pytest

from comick_volume_db import fandom_source as fs


# --- parse_chapters_field: every form in the plan's format table ---------------------

def test_parse_en_dash_range():           # Mushishi: U+2013
    assert fs.parse_chapters_field("11\u201315") == ("11", "15")


def test_parse_hyphen_with_spaces():       # One Piece
    assert fs.parse_chapters_field("18 - 26") == ("18", "26")


def test_parse_bare_hyphen_range():        # JoJo
    assert fs.parse_chapters_field("1-8") == ("1", "8")


def test_parse_wikilink_br_list():         # Soul Eater (recon-confirmed)
    val = "[[Chapter 2]]<br>[[Chapter 3]]<br>[[Chapter 4]]<br>[[Chapter 5]]<br>"
    assert fs.parse_chapters_field(val) == ("2", "5")


def test_parse_wikilink_range():           # [[Chapter 17]]-[[Chapter 25]] (plan Trap 1)
    assert fs.parse_chapters_field("[[Chapter 17]]\u2013[[Chapter 25]]") == ("17", "25")


def test_parse_comma_list():               # plan Trap 1
    assert fs.parse_chapters_field("1, 2, 3, 4, 5") == ("1", "5")


def test_parse_single_number():            # plan Trap 1
    assert fs.parse_chapters_field("7") == ("7", "7")


def test_parse_preserves_fractional():     # volume_builder contract: fractional as strings
    assert fs.parse_chapters_field("25.02-25.10") == ("25.02", "25.10")


# --- NEGATIVE CONTROLS (a check that CAN fail must be shown to fail correctly) --------

def test_parse_none_returns_none():
    assert fs.parse_chapters_field(None) is None


def test_parse_empty_returns_none():
    assert fs.parse_chapters_field("") is None


def test_parse_text_only_returns_none():   # no numeric label anywhere -> true negative
    assert fs.parse_chapters_field("TBA") is None


# --- _split_fields: match by FIELD name, never template name (Trap 2) ----------------

def test_split_fields_finds_chapters_under_Volume_template():
    wt = ("{{Volume\n| image = x.jpg\n| chapters = 11\u201315\n"
          "| previous = [[Volume 2]]\n| next = [[Volume 4]]\n}}")
    fields = dict(fs._split_fields(wt))
    assert fields["chapters"] == "11\u201315"
    assert fields["next"] == "[[Volume 4]]"


def test_split_fields_finds_chapters_under_Volume_Box_template():
    # One Piece uses {{Volume Box}} with a different field order. Field-name match wins.
    wt = ("{{Volume Box\n|title = Things\n|chapters = 18 - 26\n|jname = x\n}}")
    fields = dict(fs._split_fields(wt))
    assert fields["chapters"] == "18 - 26"


def test_split_fields_matches_chapter_singular():
    # JoJo uses 'chapter' (singular). Must be found by the alias set.
    wt = "{{Volume\n| chapter = 1-8\n}}"
    parsed, _, _ = fs._parse_one_volume(wt)
    assert parsed == ("1", "8")


# --- _parse_one_volume + chain walk on synthetic wikitext ----------------------------

def test_parse_one_volume_returns_next_link():
    wt = ("{{Volume\n| chapters = 11\u201315\n"
          "| previous = [[Volume 2]]\n| next = [[Volume 4]]\n}}")
    parsed, nxt, has_nav = fs._parse_one_volume(wt)
    assert parsed == ("11", "15")
    # Link target normalised to the canonical underscore form (MediaWiki space == underscore).
    assert nxt == "Volume_4"
    assert has_nav is True


def test_parse_one_volume_no_next_returns_none_next():
    wt = "{{Volume\n| chapters = 1-5\n}}"  # final volume: no next field
    parsed, nxt, has_nav = fs._parse_one_volume(wt)
    assert parsed == ("1", "5")
    assert nxt is None
    # No next/previous field anywhere -> this wiki is NOT link-chained.
    assert has_nav is False


def test_parse_one_volume_no_chapters_field_returns_none_parsed():
    # A page that exists but carries no chapters field -> None, not a guess.
    wt = "{{Volume\n| image = x.jpg\n| pages = 200\n}}"
    parsed, _, _ = fs._parse_one_volume(wt)
    assert parsed is None


def test_fandom_volumes_walks_a_synthetic_chain(monkeypatch):
    """The chain terminates itself: Volume_1 -> Volume_2 -> stop (no next). We never assume
    the count; the walk position assigns volume numbers. The next-link is written with a space
    ('[[Volume 2]]') to exercise the space->underscore canonicalisation the walker does.

    The final volume keeps a 'previous' field (no 'next') -- matching real nav-equipped wikis
    like Mushishi, where every page carries previous/next and only the last drops 'next'. That
    'previous' field is what marks the wiki as link-chained (has_nav=True) throughout."""
    pages = {
        "Volume_1": "{{Volume\n| chapters = 1-5\n| next = [[Volume 2]]\n}}",
        "Volume_2": "{{Volume\n| chapters = 6-10\n| previous = [[Volume 1]]\n}}",  # no next -> ends
    }
    monkeypatch.setattr(fs, "_fetch_wikitext", lambda host, page: pages.get(page))
    monkeypatch.setattr(fs, "_host_for", lambda title: "x.fandom.com")

    vols, url = fs.fandom_volumes("Whatever")
    assert vols == [
        {"number": 1, "chapterStart": "1", "chapterEnd": "5"},
        {"number": 2, "chapterStart": "6", "chapterEnd": "10"},
    ]
    assert url == "https://x.fandom.com/wiki/Volume_1"


def test_fandom_volumes_returns_none_when_no_volume_1(monkeypatch):
    # Berserk class: the wiki exists but has no Volume_1 page -> None, not an error. We stub
    # the category fallback so this test exercises ONLY the next-link walk path (no network).
    monkeypatch.setattr(fs, "_fetch_wikitext", lambda host, page: None)
    monkeypatch.setattr(fs, "_host_for", lambda title: "berserk.fandom.com")
    monkeypatch.setattr(fs, "_enumerate_via_category", lambda *a, **k: None)
    assert fs.fandom_volumes("Berserk") is None


def test_fandom_volumes_hole_terminates_chain(monkeypatch):
    # A volume whose chapters field can't be parsed terminates the walk. We refuse to publish
    # a mapping with a hole, so the whole series returns None (no partial publish).
    pages = {
        "Volume_1": "{{Volume\n| chapters = 1-5\n| next = [[Volume 2]]\n}}",
        "Volume_2": "{{Volume\n| chapters = TBA\n| previous = [[Volume 1]]\n| next = [[Volume 3]]\n}}",  # hole
        "Volume_3": "{{Volume\n| chapters = 11-15\n| previous = [[Volume 2]]\n}}",
    }
    monkeypatch.setattr(fs, "_fetch_wikitext", lambda host, page: pages.get(page))
    monkeypatch.setattr(fs, "_host_for", lambda title: "x.fandom.com")
    monkeypatch.setattr(fs, "_enumerate_via_category", lambda *a, **k: None)
    assert fs.fandom_volumes("Whatever") is None


def test_fandom_volumes_cycle_guard_refuses_malformed_chain(monkeypatch):
    # Defensive: a next-link pointing back to an earlier page must not loop forever. A real
    # Fandom chain is acyclic and ends with an absent next-link; a cycle is malformed data, so
    # we refuse it (None) -- consistent with refusing a hole, per the plan's "no interpolation".
    pages = {
        "Volume_1": "{{Volume\n| chapters = 1-5\n| next = [[Volume 2]]\n}}",
        "Volume_2": "{{Volume\n| chapters = 6-10\n| previous = [[Volume 1]]\n| next = [[Volume 1]]\n}}",  # cycle
    }
    monkeypatch.setattr(fs, "_fetch_wikitext", lambda host, page: pages.get(page))
    monkeypatch.setattr(fs, "_host_for", lambda title: "x.fandom.com")
    monkeypatch.setattr(fs, "_enumerate_via_category", lambda *a, **k: None)
    assert fs.fandom_volumes("Whatever") is None


def test_fandom_volumes_falls_back_to_category_when_no_next_links(monkeypatch):
    """One Piece class: the infobox has no previous/next fields, so the next-link walk yields
    nothing and we enumerate via category. This proves strategy B is reachable from
    fandom_volumes and that the two strategies compose."""
    pages = {
        # Volume Box template, NO next/previous -- walk strategy gets vol 1 only (incomplete).
        "Volume_1": "{{Volume Box\n| chapters = 1 - 8\n}}",
        "Volume_2": "{{Volume Box\n| chapters = 9 - 17\n}}",
        "Volume_3": "{{Volume Box\n| chapters = 18 - 26\n}}",
    }
    monkeypatch.setattr(fs, "_fetch_wikitext", lambda host, page: pages.get(page))
    monkeypatch.setattr(fs, "_host_for", lambda title: "x.fandom.com")
    # category strategy returns the full mapping
    monkeypatch.setattr(fs, "_enumerate_via_category", lambda host, title, mx: [
        {"number": 1, "chapterStart": "1", "chapterEnd": "8"},
        {"number": 2, "chapterStart": "9", "chapterEnd": "17"},
        {"number": 3, "chapterStart": "18", "chapterEnd": "26"},
    ])
    vols, url = fs.fandom_volumes("Whatever")
    assert [v["number"] for v in vols] == [1, 2, 3]
    assert vols[2] == {"number": 3, "chapterStart": "18", "chapterEnd": "26"}


# --- _enumerate_via_category (strategy B) --------------------------------------------

class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_enumerate_via_category_filters_to_volume_pages_only(monkeypatch):
    # The category lists Volume N pages PLUS strays ("Chapters and Volumes", "Special Volumes").
    # Only "Volume N" titles are kept; strays are filtered, not fetched.
    pages_wt = {
        "Volume_1": "{{Volume Box\n| chapters = 1 - 8\n}}",
        "Volume_2": "{{Volume Box\n| chapters = 9 - 17\n}}",
    }
    cat_payload = {"query": {"categorymembers": [
        {"title": "Volume 2"}, {"title": "Chapters and Volumes"},
        {"title": "Volume 1"}, {"title": "Category:Special Volumes"},
    ]}}

    def fake_get(url, params=None, headers=None, timeout=None):
        if params and params.get("list") == "categorymembers":
            return _FakeResp(cat_payload)
        # page fetch
        page = params.get("page")
        return _FakeResp({"parse": {"wikitext": {"*": pages_wt.get(page)}}} if page in pages_wt else {"error": {"code": "missingtitle"}})

    monkeypatch.setattr(fs.requests, "get", fake_get)
    monkeypatch.setattr(fs, "_host_for", lambda title: "x.fandom.com")
    vols = fs._enumerate_via_category("x.fandom.com", "Whatever", 200)
    assert [v["number"] for v in vols] == [1, 2]
    assert vols[0]["chapterEnd"] == "8"


def test_enumerate_via_category_probes_both_category_spellings(monkeypatch):
    # First spelling ("Category:<Series> Volumes") returns nothing; the bare "Category:Volumes"
    # is tried and used. Order matters: series-prefixed first, bare second.
    calls = []
    pages_wt = {"Volume_1": "{{Volume\n| chapters = 1-5\n}}"}
    cat_series = {"error": {"code": "missingcategory"}}      # empty / nonexistent
    cat_bare = {"query": {"categorymembers": [{"title": "Volume 1"}]}}

    def fake_get(url, params=None, headers=None, timeout=None):
        if params and params.get("list") == "categorymembers":
            calls.append(params["cmtitle"])
            return _FakeResp(cat_bare if params["cmtitle"] == "Category:Volumes" else cat_series)
        page = params.get("page")
        return _FakeResp({"parse": {"wikitext": {"*": pages_wt[page]}}})

    monkeypatch.setattr(fs.requests, "get", fake_get)
    vols = fs._enumerate_via_category("x.fandom.com", "Whatever", 200)
    assert "Category:Whatever Volumes" in calls and "Category:Volumes" in calls
    assert vols and vols[0]["chapterEnd"] == "5"


def test_enumerate_via_category_refuses_a_hole(monkeypatch):
    # A listed Volume_2 with no chapters field -> refuse the whole mapping (None), no partial.
    pages_wt = {
        "Volume_1": "{{Volume\n| chapters = 1-5\n}}",
        "Volume_2": "{{Volume\n| image = x.jpg\n}}",  # no chapters field -> hole
    }
    cat_payload = {"query": {"categorymembers": [{"title": "Volume 1"}, {"title": "Volume 2"}]}}

    def fake_get(url, params=None, headers=None, timeout=None):
        if params and params.get("list") == "categorymembers":
            return _FakeResp(cat_payload)
        page = params.get("page")
        return _FakeResp({"parse": {"wikitext": {"*": pages_wt[page]}}})

    monkeypatch.setattr(fs.requests, "get", fake_get)
    assert fs._enumerate_via_category("x.fandom.com", "Whatever", 200) is None


# --- slugify --------------------------------------------------------------------------

def test_slugify_strips_punctuation_and_spaces():
    assert fs._slugify("Vinland Saga") == "vinlandsaga"
    assert fs._slugify("One Piece") == "onepiece"
    assert fs._slugify("20th Century Boys") == "20thcenturyboys"
    assert fs._slugify("JoJo's Bizarre Adventure") == "jojosbizarreadventure"


# --- LIVE: the two known-good anchors ------------------------------------------------

@pytest.mark.live
def test_live_mushishi_ten_volumes_vol3_11_to_15():
    vols, url = fs.fandom_volumes("Mushishi")
    assert vols is not None, "Mushishi fandom wiki should exist and parse"
    assert len(vols) == 10
    v3 = next(v for v in vols if v["number"] == 3)
    assert (v3["chapterStart"], v3["chapterEnd"]) == ("11", "15")
    assert url == "https://mushishi.fandom.com/wiki/Volume_1"


@pytest.mark.live
def test_live_one_piece_vol3_18_to_26():
    vols, url = fs.fandom_volumes("One Piece")
    assert vols is not None
    v3 = next(v for v in vols if v["number"] == 3)
    assert (v3["chapterStart"], v3["chapterEnd"]) == ("18", "26")
    assert url == "https://onepiece.fandom.com/wiki/Volume_1"
