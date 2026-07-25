from comick_volume_db.record import build_record


def test_build_record_shape():
    volumes = [{"number": 1, "chapterStart": "1", "chapterEnd": "7"}]
    rec = build_record(series_title="Death Note", weebcentral_id="01J76XY7FYW2T2SDXP32NEFY8H",
                       comick_hid="CKlytjyb", comick_slug="death-note",
                       volumes=volumes, oddball=False, scraped_at="2026-07-25T00:00:00Z",
                       complete=True)
    assert rec["weebCentral"]["seriesId"] == "01J76XY7FYW2T2SDXP32NEFY8H"
    assert rec["comickHid"] == "CKlytjyb"
    assert rec["volumes"][0]["chapterEnd"] == "7"
    assert rec["numberingQuirk"] is False and rec["complete"] is True
