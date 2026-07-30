"""Unit + live tests for the Wikipedia Graphic novel list ChapterList reader.

The proof case is Vinland Saga: 29 volumes, vol 29 = chapters 210-220, via
{{Graphic novel list}} ChapterList (publisher-cited). The plan specified *210. bullets; recon
showed the real form is zero-padded *001. bullets with non-numeric entries mixed in
(*Bonus Material.) -- the parser handles both, and a block/page with no numeric ChapterList
yields None (negative control), never a guess.
"""
import textwrap

import pytest

from comick_volume_db import wikipedia_source as ws


def _dedent(s):
    """Strip Python-docstring leading indentation so the wikitext matches what the live API
    returns (MediaWiki wikitext is NOT indented under the template opener)."""
    return textwrap.dedent(s).strip()


# A realistic {{Graphic novel list}} block, recon-shaped (zero-padded bullets, a non-numeric
# entry, refs/ISBN on other fields that must NOT be mistaken for chapter numbers).
_VINLAND_V1 = _dedent("""\
{{Graphic novel list
|VolumeNumber    = 1
|OriginalRelDate = July 15, 2005<ref>{{Cite web|url=http://kc.kodansha.co.jp|publisher=[[Kodansha]]}}</ref>
|OriginalISBN = 978-4-06-363559-1
|LicensedRelDate = October 13, 2013
|LicensedISBN = 978-1-61262-420-4
|ChapterList     =
*001. {{Nihongo|"Normanni"|北人|Norumanni}}
*002. {{Nihongo|"Somewhere Not Here"|ここではないどこか|Koko de wa Nai Dokoka}}
*003. {{Nihongo|"Beyond the Edge of the Sea"|海の果ての果て|Umi no Hate no Hate}}
*004. {{Nihongo|"Unbreakable Chains"|解かれ得ぬ鎖|Tokare Enu Kusari}}
*005. {{Nihongo|"Troll"|戦鬼|Tororu}}
*Bonus Material. "Heroic Exploits of Viking Girl Ylva"
|Summary = In 1013 AD, the
}}""")

# Vol 29 -- the proof case. Bullets are bare (no zero-pad) here to exercise both forms.
_VINLAND_V29 = _dedent("""\
{{Graphic novel list
|VolumeNumber = 29
|ChapterList =
*210. "Chapter 210"
*211. "Chapter 211"
*220. "Chapter 220"
}}""")


# --- parse_volumes_from_wikitext -----------------------------------------------------

def test_parse_zero_padded_bullets():
    vols = ws.parse_volumes_from_wikitext(_VINLAND_V1)
    assert vols == [{"number": 1, "chapterStart": "1", "chapterEnd": "5"}]


def test_parse_bare_bullets_and_high_numbers():
    vols = ws.parse_volumes_from_wikitext(_VINLAND_V29)
    assert vols == [{"number": 29, "chapterStart": "210", "chapterEnd": "220"}]


def test_parse_multiple_blocks_sorted_by_number():
    wt = _VINLAND_V1 + "\n" + _VINLAND_V29
    vols = ws.parse_volumes_from_wikitext(wt)
    assert [v["number"] for v in vols] == [1, 29]


def test_parse_strips_leading_zeros_but_keeps_value():
    # *007. -> "7", not "007". volume_builder treats these as strings; we hand back the clean
    # integer label because the leading zeros are Wikipedia formatting, not part of the number.
    wt = """{{Graphic novel list
|VolumeNumber = 1
|ChapterList =
*007. "x"
*008. "y"
}}"""
    vols = ws.parse_volumes_from_wikitext(wt)
    assert vols[0] == {"number": 1, "chapterStart": "7", "chapterEnd": "8"}


def test_parse_skips_non_numeric_bullets():
    # "*Bonus Material." has no digit-after-dot, so it is skipped. If ONLY non-numeric bullets
    # exist, the block is a hole and skipped.
    wt = """{{Graphic novel list
|VolumeNumber = 1
|ChapterList =
*Bonus Material. "extra"
*Special. "extra2"
}}"""
    assert ws.parse_volumes_from_wikitext(wt) is None


def test_parse_isbn_refs_not_mistaken_for_chapters():
    # ISBNs and ref URLs contain digits; only ChapterList BULLETS count. The ISBN field on vol 1
    # (978-4-06-363559-1) must NOT become a chapter number.
    vols = ws.parse_volumes_from_wikitext(_VINLAND_V1)
    assert vols[0]["chapterStart"] == "1"   # not "978"
    assert vols[0]["chapterEnd"] == "5"     # not "1"


# --- word-prefix bullets and two-column split (Task 4 parser extensions) -------------

# Sakamoto Days: '*Days N:' -- word prefix, colon terminator. The number is WRITTEN as a token;
# we read it, we do not derive it from list position.
_SAKAMOTO_V1 = _dedent("""\
{{Graphic novel list
|VolumeNumber = 1
|ChapterList =
*Days 1: {{Nihongo|"The Legendary Hit Man"|伝説の殺し屋|Densetsu no Koroshiya}}
*Days 2: {{Nihongo|"Sakamoto Family Rules"|坂本家家訓|Sakamoto Kekakun}}
*Days 7: {{Nihongo|"Hard-Boiled"|ハードボイルド|Hado Boirudo}}
}}""")


def test_parse_word_prefix_bullets_colon_terminator():
    # '*Days N:' -- the number follows a word prefix and a colon terminator. Range is first..last.
    vols = ws.parse_volumes_from_wikitext(_SAKAMOTO_V1)
    assert vols == [{"number": 1, "chapterStart": "1", "chapterEnd": "7"}]


# Battle Angel Alita: two-column split ChapterListCol1 / ChapterListCol2 with '*Fight N ' word
# prefix and a SPACE terminator (no dot/colon). Col1 holds the first half of the run, col2 the
# second; bullets concatenate in source order.
_ALITA_V1 = _dedent("""\
{{Graphic novel list
|VolumeNumber=1
|ChapterListCol1=
*Fight 1 {{nihongo|"Rusty Angel"|x|y}}
*Fight 2 {{nihongo|"Fight on Instinct"|x|y}}
*Fight 3 {{nihongo|"Only Value"|x|y}}
|ChapterListCol2=
*Fight 4 {{nihongo|"Resurgents"|x|y}}
*Fight 5 {{nihongo|"Sanctuary"|x|y}}
*Fight 6 {{nihongo|"Battle Angel"|x|y}}
|Summary=
}}""")


def test_parse_two_column_split_concatenates_in_order():
    # Col1 = ch 1-3, Col2 = ch 4-6; the volume's range is 1..6 spanning both columns.
    vols = ws.parse_volumes_from_wikitext(_ALITA_V1)
    assert vols == [{"number": 1, "chapterStart": "1", "chapterEnd": "6"}]


def test_parse_word_prefix_space_terminator():
    # '*Fight 1 {{...}}' -- number followed by a space (no punctuation). The space terminator
    # branch of _BULLET must catch this or Alita silently yields None.
    vols = ws.parse_volumes_from_wikitext(_ALITA_V1)
    assert vols is not None and vols[0]["chapterStart"] == "1"


def test_parse_refuses_numbered_list_template():
    # {{Numbered list|start=N}} and MediaWiki '#' ordered lists are DERIVATION schemas: the
    # chapter number is list-position + offset, never written as a token. Reading them would
    # interpolate, which the plan forbids. Such a block must yield None (volume skipped).
    wt = """{{Graphic novel list
|VolumeNumber = 1
|ChapterList =
{{Numbered list|start=1
| {{Nihongo|"One"|x|y}}
| {{Nihongo|"Two"|x|y}}
}}
}}"""
    assert ws.parse_volumes_from_wikitext(wt) is None


def test_parse_refuses_hash_ordered_list():
    # '#' markers: implicit numbering by position. No number is written as a token.
    wt = """{{Graphic novel list
|VolumeNumber = 1
|ChapterList =
#{{Nihongo4|"First"|x|y}}
#{{Nihongo4|"Second"|x|y}}
}}"""
    assert ws.parse_volumes_from_wikitext(wt) is None


# --- NEGATIVE CONTROLS (a check that CAN fail must be shown to fail correctly) --------

def test_parse_no_gnl_blocks_returns_none():
    # One Piece / Naruto / Bleach: the page exists but uses a different format (Wikitable).
    # Zero {{Graphic novel list}} blocks -> None.
    wt = "{{Short description|none}}\nSome prose about chapters.\n{| class=wikitable\n| vol || isbn\n|}"
    assert ws.parse_volumes_from_wikitext(wt) is None


def test_parse_blocks_without_chapterlist_return_none():
    # A page whose GNL blocks carry VolumeNumber + ISBN + dates but NO ChapterList (common --
    # most volumes are listed for their bibliographic data only). -> None.
    wt = """{{Graphic novel list
|VolumeNumber = 1
|OriginalRelDate = 2005
|OriginalISBN = 978-4-06-363559-1
}}
{{Graphic novel list
|VolumeNumber = 2
|OriginalISBN = 978-4-06-363559-2
}}"""
    assert ws.parse_volumes_from_wikitext(wt) is None


def test_parse_empty_returns_none():
    assert ws.parse_volumes_from_wikitext("") is None


# --- _match_page ---------------------------------------------------------------------

def test_match_exact_title_preferred():
    titles = ["Vinland Saga", "List of Vinland Saga chapters", "Other"]
    assert ws._match_page("Vinland Saga", titles) == "Vinland Saga"


def test_match_list_of_chapters_when_no_exact():
    # The real case: the transclusion set has "List of Vinland Saga chapters", not "Vinland Saga".
    titles = ["List of Vinland Saga chapters", "Vinland Saga (film)", "Other"]
    assert ws._match_page("Vinland Saga", titles) == "List of Vinland Saga chapters"


def test_match_normalised_when_neither_exact_nor_list():
    titles = ["List of 20th Century Boys chapters"]
    assert ws._match_page("20th Century Boys", titles) == "List of 20th Century Boys chapters"


def test_match_returns_none_when_nothing_matches():
    assert ws._match_page("Totally Unknown Series", ["One Piece", "Naruto"]) is None


def test_match_containment_fallback_for_subtitle():
    # Demon Slayer: page is 'List of Demon Slayer: Kimetsu no Yaiba chapters' -- the want is a
    # strict substring of the candidate, and the candidate ends in 'chapters'. No exact/norm
    # equality holds, so the containment tier (added Task 4) must reach it.
    titles = ["List of Demon Slayer: Kimetsu no Yaiba chapters",
              "List of Welcome to Demon School! Iruma-kun chapters"]
    assert ws._match_page("Demon Slayer", titles) == "List of Demon Slayer: Kimetsu no Yaiba chapters"


def test_match_containment_requires_chapters_or_volumes_suffix():
    # Without a '...chapters'/'...volumes' suffix, a substring match is rejected -- 'Hunter'
    # must not resolve to 'Marine Hunter' (a different series).
    assert ws._match_page("Hunter", ["Marine Hunter", "The Fire Hunter"]) is None


def test_match_containment_prefers_chapters_over_volumes():
    # When both a '...chapters' and a '...volumes' page contain the want, the chapters page wins
    # (it carries per-volume ChapterList data; a volumes page often does not, e.g. JoJo).
    titles = ["List of Foo chapters", "List of Foo volumes"]
    assert ws._match_page("Foo", titles) == "List of Foo chapters"


# --- _normalize_title ----------------------------------------------------------------

def test_normalize_is_ascii_alphanumerics_only():
    assert ws._normalize_title("Vinland Saga!") == "vinlandsaga"
    assert ws._normalize_title("20th Century Boys") == "20thcenturyboys"
    assert ws._normalize_title("JoJo's Bizarre Adventure") == "jojosbizarreadventure"


def test_normalize_folds_multiplication_sign_to_x():
    # Wikipedia uses the typographic U+00D7 in 'Hunter × Hunter'; our request spells it 'x'.
    # Without the fold they compare unequal (page -> 'hunterhunter', want -> 'hunterxhunter').
    assert ws._normalize_title("Hunter \u00d7 Hunter") == "hunterxhunter"
    assert ws._normalize_title("Hunter \u00d7 Hunter") == ws._normalize_title("Hunter x Hunter")


# --- LIVE: the proof case ------------------------------------------------------------

@pytest.mark.live
def test_live_vinland_saga_29_volumes_vol29_210_to_220():
    vols, url = ws.wikipedia_volumes("Vinland Saga")
    assert vols is not None, "Vinland Saga should resolve via List of Vinland Saga chapters"
    assert [v["number"] for v in vols] == list(range(1, 30)), "expected 29 volumes, 1..29"
    v29 = next(v for v in vols if v["number"] == 29)
    assert (v29["chapterStart"], v29["chapterEnd"]) == ("210", "220")
    assert url == "https://en.wikipedia.org/wiki/List_of_Vinland_Saga_chapters"


@pytest.mark.live
def test_live_one_piece_yields_none_no_gnl_template():
    # One Piece's chapter list does NOT use {{Graphic novel list}} -> None. This is the plan's
    # negative case: a famous series whose Wikipedia page carries no usable ChapterList.
    assert ws.wikipedia_volumes("One Piece") is None
