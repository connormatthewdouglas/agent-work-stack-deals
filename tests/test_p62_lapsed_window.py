"""P62 (fieldnotes_ai, Brain #945): keep last check and last rate visible when the 7d window lapses."""
import html
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import availability_rate as A
from core.deals import compare_gpu_prices
from core.ids import content_build_id

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gpu_pages as GP  # noqa: E402

NOW = datetime(2026, 11, 20, 9, tzinfo=timezone.utc)
FRESH_LAST = (NOW - timedelta(hours=2)).isoformat()
LAPSED_LAST = (NOW - timedelta(days=8, hours=4)).isoformat()  # 196h


def _window(known=10, stocked=4, unknown=2, last=None, first=None, source="git_history"):
    first = first or (NOW - timedelta(days=6)).isoformat()
    last = last or FRESH_LAST
    monkey_end = last
    return known, stocked, unknown, first, last, source, monkey_end


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch):
    monkeypatch.setenv("LW_AVAIL_NOW", NOW.isoformat())
    monkeypatch.setattr(A, "_SCOUT", {})
    monkeypatch.setattr(A, "_SCOUT_AT", None)
    yield


def test_lapsed_row_keeps_last_check_value_and_age(monkeypatch):
    k = ("V", "H100 SXM", 80, "On-demand")
    first = (NOW - timedelta(days=14)).isoformat()
    monkeypatch.setattr(A, "_CACHE", {
        "window_start": (NOW - timedelta(days=15)).isoformat(),
        "window_end": LAPSED_LAST,
        "rows": {k: {"checks": 12, "in_stock_checks": 3, "unknown_checks": 1,
                     "first_check_at": first, "last_check_at": LAPSED_LAST}},
    })
    # Source still describes the old window; the current rate is not rewritten here.
    raw = A.fields(*k, 2)["availability_rate_7d"]
    assert raw["rate"] == 0.25 and raw["last_check_at"] == LAPSED_LAST
    r = A.lapsed_rate(raw)
    assert r["rate"] is None  # current rate is unknown; do not present 0.25 as current
    assert r["last_check_at"] == LAPSED_LAST
    assert r["last_observed_rate"] == 0.25
    assert r["window_status"] == "lapsed"
    assert r["stale_age_hours"] == 196.0  # 8d 4h
    assert r["window_stale"] is True
    assert r["first_check_at"] == first
    assert A.rate_phrase(r) is None
    assert A.lapsed_phrase(r) == "lapsed · last checked 8.2d ago"
    assert A.lapsed_rate(raw)["last_observed_rate"] == 0.25


def test_fresh_row_is_unchanged(monkeypatch):
    k = ("V", "H100 SXM", 80, "On-demand")
    first = (NOW - timedelta(days=6)).isoformat()
    monkeypatch.setattr(A, "_CACHE", {
        "window_start": (NOW - timedelta(days=7)).isoformat(),
        "window_end": FRESH_LAST,
        "rows": {k: {"checks": 10, "in_stock_checks": 5, "unknown_checks": 2,
                     "first_check_at": first, "last_check_at": FRESH_LAST}},
    })
    r = A.fields(*k, 2)["availability_rate_7d"]
    assert r["rate"] == 0.5
    assert r["checks"] == 10 and r["known_checks"] == 10 and r["in_stock_checks"] == 5
    assert r["last_check_at"] == FRESH_LAST
    assert r.get("window_status") is None
    assert "last_observed_rate" not in r
    assert "stale_age_hours" not in r
    assert r["window_stale"] is False
    assert A.lapsed_phrase(r) is None
    assert A.rate_phrase(r).startswith("observed in stock in 5 of 10 checks")
    assert "last_observed_rate" not in r and r.get("window_status") is None


def test_overlay_relabels_published_rate_once_window_lapses(tmp_path):
    old = {
        "rate": 0.75, "checks": 8, "known_checks": 8, "in_stock_checks": 6,
        "first_check_at": (NOW - timedelta(days=13)).isoformat(),
        "last_check_at": LAPSED_LAST, "source": "scout_t112", "window_days": 7,
    }
    published = tmp_path / "gpu-prices.json"
    published.write_text(__import__("json").dumps({"rates": [
        {"advertiser": "V", "gpu": "H100", "vram_gb": 80, "tier": "On-demand",
         "availability_rate_7d": old},
    ]}), encoding="utf-8")
    rows = [{"advertiser": "V", "gpu": "H100", "vram_gb": 80, "tier": "On-demand",
             "availability_rate_7d": None}]
    out = A.overlay_published_rates(rows, published)[0]["availability_rate_7d"]
    assert out["rate"] is None
    assert out["last_check_at"] == LAPSED_LAST
    assert out["last_observed_rate"] == 0.75
    assert out["window_status"] == "lapsed"
    assert out["stale_age_hours"] == 196.0
    # A later pass that already has the lapsed object still refreshes age and keeps the value.
    rows2 = [{"advertiser": "V", "gpu": "H100", "vram_gb": 80, "tier": "On-demand",
              "availability_rate_7d": out}]
    published.write_text(__import__("json").dumps({"rates": [
        {"advertiser": "V", "gpu": "H100", "vram_gb": 80, "tier": "On-demand",
         "availability_rate_7d": out},
    ]}), encoding="utf-8")
    again = A.overlay_published_rates(rows2, published)[0]["availability_rate_7d"]
    assert again["last_observed_rate"] == 0.75 and again["window_status"] == "lapsed"


def test_overlay_keeps_fresh_scout_series_as_current(tmp_path):
    old = {
        "rate": 1.0, "checks": 16, "known_checks": 16, "in_stock_checks": 16,
        "first_check_at": (NOW - timedelta(days=2)).isoformat(),
        "last_check_at": FRESH_LAST, "source": "scout_t112",
    }
    published = tmp_path / "gpu-prices.json"
    published.write_text(__import__("json").dumps({"rates": [
        {"advertiser": "V", "gpu": "H100", "vram_gb": 80, "tier": "On-demand",
         "availability_rate_7d": old},
    ]}), encoding="utf-8")
    rows = [{"advertiser": "V", "gpu": "H100", "vram_gb": 80, "tier": "On-demand",
             "availability_rate_7d": {"rate": 0.5, "source": "git_history",
                                      "last_check_at": FRESH_LAST, "checks": 2}}]
    out = A.overlay_published_rates(rows, published)[0]["availability_rate_7d"]
    assert out["source"] == "scout_t112" and out.get("window_status") is None and out["rate"] == 1.0
    assert out["last_check_at"] == FRESH_LAST and "last_observed_rate" not in out


def test_window_summary_skips_lapsed_for_earliest_current_window():
    lapsed = {"availability_rate_7d": {
        "rate": None, "last_check_at": LAPSED_LAST, "first_check_at": "2026-11-01T00:00:00Z",
        "last_observed_rate": 0.5, "window_status": "lapsed", "stale_age_hours": 196.0,
    }}
    current = {"availability_rate_7d": {
        "rate": 1.0, "checks": 4, "first_check_at": "2026-11-18T00:00:00Z",
        "last_check_at": FRESH_LAST,
    }}
    s = A.window_summary([lapsed, current, {"availability": {"in_stock": None}}])
    assert s["earliest_first_check_at"] == "2026-11-18T00:00:00Z"
    assert s["no_window_count"] == 1
    # Lapsed still counts as a window object, not a no-window row.
    assert s["no_stock_source"] + s["read_no_usable_signal"] + s["signal_no_window_yet"] == 1


def test_compare_gpu_prices_and_avail_cell_carry_lapsed_fields():
    ar = {
        "rate": None, "checks": 0, "known_checks": 0, "in_stock_checks": 0,
        "last_check_at": LAPSED_LAST, "last_observed_rate": 0.4,
        "window_status": "lapsed", "stale_age_hours": 196.0, "window_days": 7,
    }
    data = {"rates": [{
        "advertiser": "V", "gpu": "H100", "vram_gb": 80, "tier": "On-demand",
        "hourly_equiv_usd": 2.0, "price_usd": 2.0, "unit": "hour", "verified_at": NOW.isoformat(),
        "availability": {"status": "unknown", "in_stock": None},
        "availability_rate_7d": ar,
    }]}
    out = compare_gpu_prices(data, "H100", limit=5, now=NOW)
    got = out["results"][0]["availability_rate_7d"]
    assert got["window_status"] == "lapsed"
    assert got["last_check_at"] == LAPSED_LAST
    assert got["last_observed_rate"] == 0.4
    assert got["stale_age_hours"] == 196.0
    assert got["rate"] is None
    cell = GP._avail_cell(type("G", (), {"esc": staticmethod(html.escape)}), data["rates"][0])
    assert cell == "lapsed · last checked 8.2d ago"
    # stale_age_hours is time-derived and must not change content_build_id on a restamp.
    a = [{"availability_rate_7d": dict(ar)}]
    b = [{"availability_rate_7d": {**ar, "stale_age_hours": 200.0, "last_check_at": "2099-01-01T00:00:00Z"}}]
    assert content_build_id(a) == content_build_id(b)
