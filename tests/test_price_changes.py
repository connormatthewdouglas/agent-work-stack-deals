from datetime import datetime, timezone

import pytest

from core import DealError
from core.deals import freshness, latest_checked_at, next_refresh_utc, price_changes

LATEST = {"date": "2026-10-28", "previous_date": "2026-10-27", "changes": [
    {"vendor": "A", "gpu": "H100", "tier": "t", "change": "up", "old_hourly_usd": 2.0, "new_hourly_usd": 2.2, "pct": 10.0,
     "source_url": "https://a.example/p", "verified_at": "2026-10-28T10:30:00+00:00"},
    {"vendor": "B", "gpu": "A100", "tier": "t", "change": "new", "old_hourly_usd": None, "new_hourly_usd": 1.0, "pct": None,
     "source_url": "https://b.example/p", "verified_at": "2026-10-28T10:31:00+00:00"},
    {"vendor": "C", "gpu": "H100 SXM", "tier": "t", "change": "down", "old_hourly_usd": 3.0, "new_hourly_usd": 2.7, "pct": -10.0,
     "source_url": "https://c.example/p", "verified_at": "2026-10-28T10:32:00+00:00"}]}
HIST = {"first_snapshot": "2026-10-20", "last_snapshot": "2026-10-28", "snapshot_count": 9, "changes": [
    {"date": "2026-10-28", "vendor": "A", "gpu": "H100", "tier": "t", "from_hourly_usd": 2.0, "to_hourly_usd": 2.2, "change_pct": 10.0, "source_url": "https://a"},
    {"date": "2026-10-24", "vendor": "A", "gpu": "H100", "tier": "t", "from_hourly_usd": 2.5, "to_hourly_usd": 2.0, "change_pct": -20.0, "source_url": "https://a"},
    {"date": "2026-10-21", "vendor": "D", "gpu": "L40S", "tier": "t", "from_hourly_usd": 1.0, "to_hourly_usd": 0.9, "change_pct": -10.0, "source_url": "https://d"}]}


def test_next_refresh_is_1023_utc_today_or_tomorrow():
    assert next_refresh_utc(datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)) == "2026-10-28T10:23:00Z"
    assert next_refresh_utc(datetime(2026, 10, 28, 10, 23, tzinfo=timezone.utc)) == "2026-10-29T10:23:00Z"
    assert next_refresh_utc(datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc)) == "2027-01-01T10:23:00Z"


def test_latest_checked_at_and_hint():
    assert latest_checked_at(["2026-10-27T02:21:00-04:00", "2026-10-28T16:43:09+00:00", None, "bad"]) == "2026-10-28T16:43:09Z"
    f = freshness("2026-10-28T16:43:09Z", datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc))
    assert f == {"data_checked_at": "2026-10-28T16:43:09Z", "next_refresh_utc": "2026-10-29T10:23:00Z",
                 "refresh_hint": "Prices refresh daily; call get_price_changes(since='2026-10-28') to see what moved."}
    assert freshness(None)["refresh_hint"] == "Prices refresh daily; call get_price_changes() to see what moved."


def test_latest_day_orders_drops_first_and_labels_new():
    r = price_changes(LATEST, None)
    assert [c["direction"] for c in r["changes"]] == ["down", "up", "new"]
    assert (r["price_drops"], r["price_rises"], r["newly_tracked"]) == (1, 1, 1)
    assert r["window"] == {"from": "2026-10-27", "to": "2026-10-28"} and r["data_checked_at"] == "2026-10-28T10:32:00Z"
    assert "refresh_hint" not in r


def test_since_filters_history_and_gpu():
    r = price_changes(None, HIST, since="2026-10-24")
    assert [c["date"] for c in r["changes"]] == ["2026-10-28", "2026-10-24"]
    assert price_changes(None, HIST, since="2026-10-01", gpu="l40s")["total"] == 1
    assert "History starts 2026-10-20" in price_changes(None, HIST, since="2026-10-01")["note"]
    assert price_changes(None, HIST, since="2026-10-01", limit=1)["count"] == 1


def test_bad_since_rejected():
    with pytest.raises(DealError):
        price_changes(None, HIST, since="last week")
