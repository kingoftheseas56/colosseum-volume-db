"""The no-demotion guard on the seed rebuild.

A rebuild may UPDATE a qualified record and may PROMOTE an unqualified one, but it may
never DEMOTE. A demotion is always a regression: the shelf a reader already has turns
silently back into a flat chapter list, with no error anywhere. This is not the fallback
path's blanket "never overwrite qualified" fence, which would freeze the DB and stop an
ongoing series ever gaining volumes.

Concrete case (2026-07-31): Berserk is published qualified after Hemanth's ruling, but a
rebuild re-gates it from Comick's rows, still finds chapter 383 untagged, and without
this guard writes qualified:false straight back over it.
"""
import json

from comick_volume_db.build_db import would_downgrade


def _write(path, qualified):
    path.write_text(json.dumps({"seriesTitle": "Berserk", "qualified": qualified,
                                "volumes": [{"number": 1, "chapterStart": "0.001",
                                             "chapterEnd": "0.03"}]}),
                    encoding="utf-8")
    return path


def test_absent_record_is_never_a_downgrade(tmp_path):
    assert would_downgrade(tmp_path / "missing.json", {"qualified": False}) is False


def test_qualified_over_qualified_is_an_update_not_a_downgrade(tmp_path):
    path = _write(tmp_path / "r.json", True)
    assert would_downgrade(path, {"qualified": True}) is False


def test_qualified_over_unqualified_is_a_promotion(tmp_path):
    path = _write(tmp_path / "r.json", False)
    assert would_downgrade(path, {"qualified": True}) is False


def test_unqualified_over_unqualified_is_not_a_downgrade(tmp_path):
    path = _write(tmp_path / "r.json", False)
    assert would_downgrade(path, {"qualified": False}) is False


def test_unqualified_over_qualified_IS_a_downgrade(tmp_path):
    """The Berserk case — the one this guard exists for."""
    path = _write(tmp_path / "r.json", True)
    assert would_downgrade(path, {"qualified": False}) is True


def test_malformed_existing_record_is_treated_as_absent(tmp_path):
    """A rebuild is exactly how you would want to repair a corrupt record, so a file we
    cannot read must not block the write."""
    path = tmp_path / "r.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert would_downgrade(path, {"qualified": False}) is False


def test_record_missing_the_qualified_key_is_treated_as_unqualified(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"seriesTitle": "Berserk"}), encoding="utf-8")
    assert would_downgrade(path, {"qualified": False}) is False
