"""Collector commits that change published rows must advance feed_updated_at to the generate clock."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gpu_calculator import _finalize_feed_updated_at  # noqa: E402


def _base(**extra):
    row = {"advertiser": "Vast.ai", "gpu": "A100 SXM", "price_usd": 1.1304, **extra}
    return {
        "rates": [row],
        "held_stale": [],
        "vendors": [{"vendor": "Vast.ai"}],
        "unpriced": [],
        "feed_updated_at": "2026-11-16T07:15:31Z",
        "prices_verified_through": "2026-11-16T07:15:31Z",
    }


def test_row_change_advances_feed_updated_at_to_generate_clock():
    """Lium 2026-11-16: prices already stamped 07:15:31Z, generate at 07:16:26Z flipped
    Vast A100 availability stale. The stamp must move to the generate clock, not stay
    at the newest verified_at, so pages-match (pin LW_AVAIL_NOW to feed_updated_at)
    reproduces the committed rows.
    """
    prev = _base(availability_status="in_stock")
    payload = _base(availability_status=None)
    _finalize_feed_updated_at(payload, prev, "2026-11-16T07:16:26Z")
    assert payload["feed_updated_at"] == "2026-11-16T07:16:26Z"
    assert payload["prices_verified_through"] == "2026-11-16T07:15:31Z"


def test_unchanged_rows_keep_previous_feed_updated_at():
    """Availability-only collected_at with no published row change must not bump the stamp."""
    prev = _base(availability_status="in_stock")
    payload = _base(availability_status="in_stock")
    payload["feed_updated_at"] = "2026-11-16T07:20:00Z"
    _finalize_feed_updated_at(
        payload, prev, "2026-11-16T07:20:00Z",
        rows_at=lambda stamp: _base(availability_status="in_stock"),
    )
    assert payload["feed_updated_at"] == "2026-11-16T07:15:31Z"
    assert payload["prices_verified_through"] == "2026-11-16T07:15:31Z"


def test_inconsistent_kept_stamp_is_advanced():
    """If the file already has the new rows but an old stamp that would not reproduce
    them, advance to the generate clock rather than keeping the inconsistent stamp.
    """
    prev = _base(availability_status=None)  # already stale on disk, stamp still 07:15:31Z
    payload = _base(availability_status=None)
    payload["feed_updated_at"] = "2026-11-16T07:15:31Z"

    def rows_at(stamp):
        if stamp == "2026-11-16T07:15:31Z":
            return _base(availability_status="in_stock")
        return payload

    _finalize_feed_updated_at(payload, prev, "2026-11-16T20:45:00Z", rows_at=rows_at)
    assert payload["feed_updated_at"] == "2026-11-16T20:45:00Z"
