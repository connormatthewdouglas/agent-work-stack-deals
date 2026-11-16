"""P61 (fieldnotes_ai, #760): file-level availability_window_summary and content_build_id."""
import copy
import json
from pathlib import Path

from core import availability_rate as A
from core.deals import compare_gpu_prices
from core.ids import content_build_id

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "api/v1/gpu-prices.json"

NO_SOURCE = {"availability": {"status": "unknown", "in_stock": None, "checked_at": None, "note": "No availability signal from this vendor for this offer; unknown, not sold out."}}
READ_NO_SIGNAL = {"availability": {"status": "unknown", "in_stock": None, "checked_at": "2026-11-09T00:00:00Z", "source": "https://example.test/pricing", "note": "The public pricing page publishes no stock signal"}}
SIGNAL_NO_WINDOW = {"availability": {"status": "available when checked", "in_stock": True, "checked_at": "2026-11-16T00:00:00Z", "origin": "record", "source": "https://example.test/api"}}
WINDOW = {"availability_rate_7d": {"rate": 1.0, "checks": 2, "known_checks": 2, "first_check_at": "2026-11-10T12:00:00Z", "last_check_at": "2026-11-11T12:00:00Z", "window_days": 7, "observed_hours": 24.0, "coverage_note": "Covers 24.0h of the planned 7-day window."}, "availability": {"status": "available when checked", "in_stock": True}}
EARLIER_WINDOW = {"availability_rate_7d": {"rate": 0.5, "checks": 4, "first_check_at": "2026-11-09T06:44:58Z", "last_check_at": "2026-11-16T00:00:00Z"}}


def test_window_summary_splits_no_window_rows_and_names_when_windows_began():
    rows = [
        {"advertiser": "A", "gpu": "H100", "hourly_equiv_usd": 1, **NO_SOURCE},
        {"advertiser": "B", "gpu": "H100", "hourly_equiv_usd": 2, **NO_SOURCE},
        {"advertiser": "C", "gpu": "H100", "hourly_equiv_usd": 3, **READ_NO_SIGNAL},
        {"advertiser": "D", "gpu": "H100", "hourly_equiv_usd": 4, **SIGNAL_NO_WINDOW},
        {"advertiser": "E", "gpu": "H100", "hourly_equiv_usd": 5, **WINDOW},
        {"advertiser": "F", "gpu": "H100", "hourly_equiv_usd": 6, **EARLIER_WINDOW},
    ]
    s = A.window_summary(rows)
    assert s["no_stock_source"] == 2
    assert s["read_no_usable_signal"] == 1
    assert s["signal_no_window_yet"] == 1
    assert s["no_window_count"] == 4
    assert s["earliest_first_check_at"] == "2026-11-09T06:44:58Z"
    # A P38 null-rate object still counts as a window (checks exist).
    null_rate = {"availability_rate_7d": {"rate": None, "checks": 0, "known_checks": 0, "no_source_checks": 4, "first_check_at": "2026-11-15T22:17:44Z"}}
    s2 = A.window_summary([{**NO_SOURCE}, null_rate])
    assert s2["no_window_count"] == 1 and s2["earliest_first_check_at"] == "2026-11-15T22:17:44Z"
    assert A.window_summary([]) == {"no_window_count": 0, "no_stock_source": 0, "read_no_usable_signal": 0, "signal_no_window_yet": 0, "earliest_first_check_at": None}


def test_committed_feed_summary_matches_row_data():
    api = json.loads(FEED.read_text())
    s = api["availability_window_summary"]
    assert s == A.window_summary(api["rates"])
    assert s["no_window_count"] == s["no_stock_source"] + s["read_no_usable_signal"] + s["signal_no_window_yet"]
    assert s["no_window_count"] + sum(1 for r in api["rates"] if isinstance(r.get("availability_rate_7d"), dict)) == len(api["rates"])
    firsts = [r["availability_rate_7d"]["first_check_at"] for r in api["rates"]
              if isinstance(r.get("availability_rate_7d"), dict) and r["availability_rate_7d"].get("first_check_at")]
    assert s["earliest_first_check_at"] == min(firsts)
    # Pass-through on compare_gpu_prices (file-level, not the compare subset).
    out = compare_gpu_prices(api, "H100", limit=5, now=__import__("datetime").datetime(2026, 11, 16, 12, tzinfo=__import__("datetime").timezone.utc))
    assert out["availability_window_summary"] == s
    assert out["content_build_id"] == api["content_build_id"] == content_build_id(api["rates"])


def test_content_build_id_changes_when_only_prices_change():
    api = json.loads(FEED.read_text())
    rates = copy.deepcopy(api["rates"])
    baseline = content_build_id(rates)
    assert isinstance(baseline, str) and len(baseline) == 16 and baseline == baseline.lower()
    assert api["generation_id"]  # compatibility: feed still carries Scout's generation_id
    # Timestamp-only restamp must not change the digest.
    restamped = copy.deepcopy(rates)
    for r in restamped:
        r["checked_at"] = "2099-01-01T00:00:00Z"
        r["verified_at"] = "2099-01-01T00:00:00Z"
        if isinstance(r.get("evidence"), dict):
            r["evidence"]["checked_at"] = "2099-01-01T00:00:00Z"
        ar = r.get("availability_rate_7d")
        if isinstance(ar, dict):
            ar["first_check_at"] = "2099-01-01T00:00:00Z"
            ar["last_check_at"] = "2099-01-02T00:00:00Z"
            ar["window_start"] = "2099-01-01T00:00:00Z"
            ar["window_end"] = "2099-01-02T00:00:00Z"
            ar["observed_hours"] = 24.0
            ar["coverage_note"] = "Covers 24.0h of the planned 7-day window."
    assert content_build_id(restamped) == baseline
    # A price-only change must produce a new id.
    repriced = copy.deepcopy(rates)
    target = next(r for r in repriced if isinstance(r.get("hourly_equiv_usd"), (int, float)))
    target["hourly_equiv_usd"] = round(float(target["hourly_equiv_usd"]) + 0.01, 4)
    if isinstance(target.get("price_usd"), (int, float)):
        target["price_usd"] = round(float(target["price_usd"]) + 0.01, 4)
    changed = content_build_id(repriced)
    assert changed != baseline and len(changed) == 16
    # Gauge: price_effective_at / effective_at are content (when the vendor's price takes effect), not restamps.
    dated = copy.deepcopy(rates)
    target = dated[0]
    target["price_effective_at"] = "2026-12-01T00:00:00Z"
    target["effective_at"] = "2026-12-01T00:00:00Z"
    assert content_build_id(dated) != baseline
