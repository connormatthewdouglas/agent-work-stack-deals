"""T116: stock checks describe observations, never prices, budgets, or predicted bills."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from core import availability_rate as A

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 6, 7, tzinfo=timezone.utc)


def setup_window(monkeypatch, known, stocked, unknown, age=1):
    end = (NOW - timedelta(hours=age)).isoformat()
    k = ("V", "H100 SXM", 80, "On-demand")
    monkeypatch.setenv("LW_AVAIL_NOW", NOW.isoformat())
    monkeypatch.setattr(A, "_SCOUT", {})
    monkeypatch.setattr(A, "_CACHE", {"window_start": (NOW - timedelta(days=7)).isoformat(),
        "window_end": end, "rows": {k: {"checks": known, "in_stock_checks": stocked,
        "unknown_checks": unknown, "last_check_at": end}}})
    return k


@pytest.mark.parametrize("known,stocked,unknown,rate,status", [
    (10, 5, 2, .5, "observed"), (100, 0, 5, 0, "observed"),
    (100, 1, 0, .01, "observed"), (2, 1, 8, .5, "insufficient_sample"),
    (0, 0, 10, None, "all_unknown")])
def test_zero_low_sparse_unknown_never_become_dollars(monkeypatch, known, stocked, unknown, rate, status):
    k = setup_window(monkeypatch, known, stocked, unknown)
    for hourly in (0, 2, 200, None):
        f = A.fields(*k, hourly)
        assert f["expected_cost_usd"] is None and "deprecated" in f["expected_cost_label"]
        r = f["availability_rate_7d"]
        assert r["rate"] == rate and r["sample_status"] == status
        assert r["known_checks"] == known and r["unknown_checks"] == unknown
        assert r["total_checks"] == known + unknown and r["window_days"] == 7
        assert r["window_start"] and r["window_end"] and not r["window_stale"]


def test_old_window_remains_explicitly_historical(monkeypatch):
    k = setup_window(monkeypatch, 10, 1, 4, age=72)
    f = A.fields(*k, 2)
    assert f["expected_cost_usd"] is None
    assert f["availability_rate_7d"]["window_stale"]
    assert f["availability_rate_7d"]["rate"] == .1


def test_unknown_counts_not_invented_for_old_capture(monkeypatch):
    k = setup_window(monkeypatch, 10, 5, None)
    r = A.fields(*k, 2)["availability_rate_7d"]
    assert r["unknown_checks"] is None and r["total_checks"] is None
    assert A.fields("missing", "L4", 24, "On-demand", 1)["availability_rate_7d"] is None


def test_scout_all_unknown_and_sparse_counts_preserved(monkeypatch):
    monkeypatch.setenv("LW_AVAIL_NOW", NOW.isoformat())
    for known, stocked in [(0, 0), (2, 1)]:
        sr = {"checks_7d": 10, "known_checks_7d": known, "in_stock_checks_7d": stocked,
              "sufficient_sample": False, "first_check_at": (NOW-timedelta(days=6)).isoformat(),
              "last_check_at": NOW.isoformat()}
        monkeypatch.setattr(A, "_SCOUT", {("v", "H100", 80, "On-demand"): (sr, NOW.isoformat())})
        f = A.fields("V", "H100", 80, "On-demand", 2)
        assert f["expected_cost_usd"] is None
        assert f["availability_rate_7d"]["unknown_checks"] == 10-known
        assert not f["availability_rate_7d"]["sufficient_sample"]


def test_compute_budget_ignores_legacy_availability_dollars():
    from core.cost_per_job import estimate_job_cost
    r = {"advertiser": "V", "gpu": "H100", "vram_gb": 80, "price_usd": 2,
         "unit": "hour", "tier": "On-demand", "tier_class": "on-demand",
         "verified_at": datetime.now(timezone.utc).isoformat(), "expected_cost_usd": 2000}
    a = estimate_job_cost({"rates": [r]}, "H100", 1, job_hours=10)
    s = copy.deepcopy(r); s["expected_cost_usd"] = None
    b = estimate_job_cost({"rates": [s]}, "H100", 1, job_hours=10)
    assert a["results"] == b["results"] and a["budget_verdict"] == b["budget_verdict"]


def test_feed_legacy_field_is_explicitly_deprecated():
    rates = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]
    assert all(r["expected_cost_usd"] is None and "deprecated" in r["expected_cost_label"] for r in rates)
