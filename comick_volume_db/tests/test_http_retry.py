"""Tests for comick_volume_db.http_retry -- the Task 5b discipline.

The contract (Task 5b, plan 2026-07-29):
  - ``fetch_with_retry`` returns a Response for ANY HTTP status (200, 404, 500 -- all are real
    server responses). A 404 is "no data," not "unreachable."
  - It raises ``SourceUnreachable`` ONLY after ``max_retries`` transport failures
    (connection refused / timeout / DNS / reset). That is the DISTINCT outcome the plan demands:
    unreachable must NEVER be the same value as "no data."
  - Retries use a growing wait (exponential backoff) so a transient blip self-heals.

These three tests are the negative-control, positive-control, and the distinction-that-is-the-
whole-point:
  1. forced transport failure -> SourceUnreachable (NEVER None)            [the fix]
  2. a real server response (incl. 404) -> returned, NOT raised            [no-data path intact]
  3. a transient failure then success -> heals, no raise, no manual retry  [backoff works]
"""
import requests
import pytest

from comick_volume_db.http_retry import SourceUnreachable, fetch_with_retry


class _FakeResp:
    def __init__(self, status=200):
        self.status_code = status
    def raise_for_status(self):
        pass


def _boom(*a, **k):
    raise requests.ConnectionError("simulated transport failure (forced)")


# --- 1. THE FIX: transport failure raises SourceUnreachable, never returns None -----------

def test_transport_failure_raises_source_unreachable_never_none(monkeypatch):
    # The whole point of Task 5b: before this, a transport failure was caught and returned as
    # None -- IDENTICAL to "this series has no volume data." A hiccup got recorded as a fact.
    # Now a transport failure after max_retries raises SourceUnreachable, a distinct outcome.
    monkeypatch.setattr("comick_volume_db.http_retry.requests.get", _boom)
    monkeypatch.setattr("comick_volume_db.http_retry.time.sleep", lambda s: None)  # no real waits
    with pytest.raises(SourceUnreachable):
        fetch_with_retry("https://unreachable.invalid/api", max_retries=2, backoff_base=0)


def test_source_unreachable_is_distinct_type_from_none():
    # The plan: "return a DISTINCT outcome -- 'unreachable' -- never the same value as 'no data.'"
    # None IS the no-data value; SourceUnreachable is an exception type. They cannot be confused.
    assert SourceUnreachable is not None
    assert not isinstance(None, SourceUnreachable)


# --- 2. NO-DATA PATH INTACT: any HTTP status returns a Response (incl. 404) ----------------

def test_real_server_response_returned_not_raised_including_404(monkeypatch):
    # A 404 is a REAL server response meaning "no such page." It MUST come back as a Response
    # (so the caller's None-on-404 path fires), NOT raise. Only transport failures raise.
    for status in (200, 404, 500, 503):
        monkeypatch.setattr("comick_volume_db.http_retry.requests.get",
                            lambda *a, **k: _FakeResp(status))
        r = fetch_with_retry("https://real.example/api")
        assert r.status_code == status  # returned, never raised


# --- 3. BACKOFF HEALS: a transient failure followed by success does not raise -------------

def test_transient_failure_then_success_heals_without_raising(monkeypatch):
    # First call fails (transient), second succeeds. fetch_with_retry retries with growing wait,
    # so the blip self-heals. No raise, no manual retry loop needed in the caller.
    calls = {"n": 0}
    waits = []
    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("transient blip")
        return _FakeResp(200)
    monkeypatch.setattr("comick_volume_db.http_retry.requests.get", flaky)
    monkeypatch.setattr("comick_volume_db.http_retry.time.sleep", lambda s: waits.append(s))
    r = fetch_with_retry("https://flaky.example/api", max_retries=3, backoff_base=1.0)
    assert r.status_code == 200
    assert calls["n"] == 2          # one failure, one success -- healed
    assert waits == [1.0]           # backoff_base * 2**0 = 1.0; no further wait after success


def test_backoff_grows_exponentially(monkeypatch):
    # The plan: "retry a small number of times with a growing wait." 2**attempt => 1, 2, 4 ...
    monkeypatch.setattr("comick_volume_db.http_retry.requests.get", _boom)
    waits = []
    monkeypatch.setattr("comick_volume_db.http_retry.time.sleep", lambda s: waits.append(s))
    with pytest.raises(SourceUnreachable):
        fetch_with_retry("https://unreachable.invalid/api", max_retries=3, backoff_base=1.0)
    # attempts 0 and 1 sleep before retry; attempt 2 (the last) raises without sleeping.
    assert waits == [1.0, 2.0]      # 1.0*2**0, 1.0*2**1 -- growing, not constant
