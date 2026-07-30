"""Shared HTTP retry + unreachable-distinction layer for source fetches.

A network failure must NEVER be recorded as 'no data' (None). It must surface as a DISTINCT
outcome so an unattended batch can list it separately from a genuine refusal and re-run it.

WHY THIS EXISTS (Task 5b, 2026-07-30):
  Both source modules used to catch ``requests.RequestException`` and return ``None`` --
  identical to 'this series has no volume data.' No retry, no backoff. That made a transient
  hiccup (the Vinland Saga mid-batch blip: 'no GNL' one minute, 29 volumes the next)
  indistinguishable from a real absence, and baked false refusals permanently into a harvest.
  Over hundreds of unattended series that is silent, unrecoverable corruption.

WHAT THIS MODULE PROVIDES:
  - ``SourceUnreachable``: exception raised after retries are exhausted. Distinct from ``None``
    ('no data'). Callers MUST carry it through to the report as its own bucket.
  - ``fetch_with_retry``: a retrying GET with growing backoff. Returns the ``Response`` on
    success (INCLUDING 404 -- a 404 means we reached the server; the page just isn't there).
    Raises ``SourceUnreachable`` only after ``max_retries`` transport failures.

THE 404 LINE IS THE KEY DISCIPLINE:
  A 404 / ``missingtitle`` is a REAL HTTP RESPONSE. It means 'reachable + no page' -- the
  legitimate ``None`` path for 'no data'. A ``RequestException`` (connection refused, timeout,
  DNS, TLS, reset) means 'could not reach the server at all' -- the ``SourceUnreachable`` path.
  These two must never collapse to the same return value, because they mean opposite things
  for a batch run: 'no data' is a settled fact (don't re-run); 'unreachable' is a transient
  failure (DO re-run).
"""
import time

import requests


class SourceUnreachable(Exception):
    """The source could not be reached after retries. Distinct from 'no data' (None).

    Raised by ``fetch_with_retry`` after ``max_retries`` consecutive transport failures.
    Callers must NOT catch it as ``None`` -- they must propagate it (or catch it explicitly
    and return a distinct outcome), so an unattended batch can list unreachable series in their
    own bucket and re-run them.
    """


def fetch_with_retry(url, params=None, headers=None, timeout=30, max_retries=3,
                     backoff_base=1.0):
    """GET with retry + growing backoff. Returns Response (any status). Raises SourceUnreachable.

    - Returns the ``requests.Response`` for ANY status code the server sends (200, 404, 500,
      etc.). Reaching the server is success at THIS layer -- the caller decides what the status
      means. In particular a 404 is RETURNED, not raised: 'reached the server, no page' is the
      caller's legitimate 'no data' path, NOT an unreachable source.
    - Raises ``SourceUnreachable`` only when the transport itself fails (``requests.RequestException``:
      connection refused, timeout, DNS failure, TLS error, connection reset) on every attempt.

    Backoff grows: wait ``backoff_base * 2**attempt`` seconds between tries. With defaults
    (3 retries, base 1.0s) the inter-retry waits are 1s then 2s -- ~3s of backoff on top of
    the per-request timeouts, bounded. The growth avoids hammering a recovering server; the
    small fixed retry count bounds the worst case so one unreachable host cannot stall a batch.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(backoff_base * (2 ** attempt))
    # All retries exhausted on transport errors -> distinct failure, never None.
    raise SourceUnreachable(
        f"{url} unreachable after {max_retries} retries: {last_exc}") from last_exc
