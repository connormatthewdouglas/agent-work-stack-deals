"""T112: availability-adjusted expected cost is additive and never replaces the raw rate."""
import json
from pathlib import Path

from core import availability_rate as A

ROOT = Path(__file__).resolve().parents[1]


def test_fields_math_floor_and_min_checks(monkeypatch):
    k = ("V", "H100 SXM", 80, "On-demand")
    monkeypatch.setattr(A, "_CACHE", {"window_end": "2026-11-04T00:00:00+00:00", "rows": {
        k: {"rate": 0.5, "checks": 10, "in_stock_checks": 5},
        ("V", "A100", 80, "On-demand"): {"rate": 0.0, "checks": 10, "in_stock_checks": 0},
        ("V", "L4", 24, "On-demand"): {"rate": 1.0, "checks": 2, "in_stock_checks": 2}}})
    f = A.fields(*k, 2.0)
    assert f["expected_cost_usd"] == 4.0 and f["availability_rate_7d"]["rate"] == 0.5 and "estimate" in f["expected_cost_label"]
    assert A.fields("V", "A100", 80, "On-demand", 1.0)["expected_cost_usd"] == 10.0  # floor 0.1
    assert A.fields("V", "L4", 24, "On-demand", 1.0) == {"availability_rate_7d": None, "expected_cost_usd": None}
    assert A.fields("X", "L4", 24, "On-demand", 1.0)["expected_cost_usd"] is None


def test_feed_rows_keep_raw_rate():
    rates = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]
    assert all("expected_cost_usd" in r and "availability_rate_7d" in r for r in rates)
    for r in rates:
        if r["expected_cost_usd"] is not None:
            assert r["expected_cost_usd"] >= r["hourly_equiv_usd"] - 1e-9 and r["availability_rate_7d"]["checks"] >= A.MIN_CHECKS
