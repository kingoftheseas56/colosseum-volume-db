from comick_volume_db.record import build_record


def test_build_record_shape():
    volumes = [{"number": 1, "chapterStart": "1", "chapterEnd": "7"}]
    rec = build_record(series_title="Death Note", weebcentral_id="01J76XY7FYW2T2SDXP32NEFY8H",
                       comick_hid="CKlytjyb", comick_slug="death-note",
                       volumes=volumes, oddball=False, scraped_at="2026-07-25T00:00:00Z",
                       complete=True, qualified=True, gate_reason="")
    assert rec["weebCentral"]["seriesId"] == "01J76XY7FYW2T2SDXP32NEFY8H"
    assert rec["comickHid"] == "CKlytjyb"
    assert rec["volumes"][0]["chapterEnd"] == "7"
    assert rec["numberingQuirk"] is False and rec["complete"] is True
    assert rec["qualified"] is True and rec["gateReason"] == ""


def test_build_record_carries_gate_rejection():
    rec = build_record(series_title="Vinland Saga", weebcentral_id="01J76XY7FQY59WRK2YWX5T4E5N",
                       comick_hid="x", comick_slug="vinland-saga",
                       volumes=[{"number": 28, "chapterStart": "202", "chapterEnd": "209"},
                                {"number": 29, "chapterStart": "219", "chapterEnd": "220"}],
                       oddball=False, scraped_at="2026-07-29T00:00:00Z", complete=True,
                       qualified=False, gate_reason="unmapped chapters between volume 28 and 29")
    assert rec["qualified"] is False and "unmapped" in rec["gateReason"]
    assert rec["volumes"]  # failing data stays inspectable
