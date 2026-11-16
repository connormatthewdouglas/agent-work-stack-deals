"""P60: 0/N availability copy, small-sample labels, and stated hours-per-month."""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core.availability_rate import RATE_FOOTNOTE  # noqa: E402
from core.gpu import HOURS_PER_MONTH, HOURS_PER_MONTH_NOTE  # noqa: E402
import gpu_pages as GP  # noqa: E402


def _cell(row):
    return GP._avail_cell(type("G", (), {"esc": staticmethod(html.escape)}), row)


def test_avail_cell_zero_of_n_replaces_out_of_stock():
    row = {
        "advertiser": "Hyperstack",
        "availability": {
            "status": "out of stock when checked", "in_stock": False,
            "checked_at": "2026-11-13T14:58:04Z", "origin": "scout",
            "availability_expires_at": "2026-11-13T22:58:04Z",
        },
        "availability_rate_7d": {
            "known_checks": 16, "in_stock_checks": 0, "sample_status": "observed",
            "sufficient_sample": True, "observed_hours": 40.1,
        },
    }
    cell = _cell(row)
    assert "not observed in stock in 16 checks" in cell
    assert "out of stock" not in cell
    assert "sold out" not in cell
    assert "data-av-checked=" in cell



def test_avail_cell_instock_none_is_historical_unknown_note():
    row = {
        "advertiser": "Lambda",
        "availability": {"status": "unknown", "in_stock": None, "checked_at": "2026-11-15T22:23:00Z", "origin": "scout"},
        "availability_rate_7d": {
            "known_checks": 1, "in_stock_checks": 0, "sample_status": "insufficient_sample",
            "sufficient_sample": False, "observed_hours": 0, "last_check_at": "2026-11-15T22:23:00Z",
        },
    }
    cell = _cell(row)
    assert cell.startswith("unknown; not observed in stock in 1 check")
    assert "last check " in cell
    assert "small sample, N=1" in cell
    assert "out of stock" not in cell


def test_avail_cell_small_sample_is_price_only():
    row = {
        "advertiser": "RunPod",
        "availability": {
            "status": "available when checked", "in_stock": True,
            "checked_at": "2026-11-13T14:58:04Z", "origin": "scout",
            "availability_expires_at": "2026-11-13T22:58:04Z",
        },
        "availability_rate_7d": {
            "known_checks": 2, "in_stock_checks": 2, "sample_status": "insufficient_sample",
            "sufficient_sample": False, "observed_hours": 2.7,
        },
    }
    cell = _cell(row)
    assert "available when checked" in cell
    assert "observed in stock in 2 of 2 checks" in cell
    assert "small sample, N=2" in cell
    assert "price-only" in cell


def test_generated_pages_use_zero_of_n_and_month_parameter():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    zeros = [r for r in feed["rates"]
             if (r.get("availability_rate_7d") or {}).get("in_stock_checks") == 0
             and (r.get("availability_rate_7d") or {}).get("known_checks")]
    small = [r for r in feed["rates"]
             if (r.get("availability_rate_7d") or {}).get("known_checks")
             and (r.get("availability_rate_7d") or {}).get("known_checks") <= 10]
    pages = [ROOT / "gpu/price-comparison/index.html",
             ROOT / "gpu/cheapest-a100-rental/index.html",
             ROOT / "cost/a100-730-hours/index.html"]
    for p in pages:
        assert p.is_file(), p
        t = p.read_text()
        if p.name != "index.html" or "price-comparison" in str(p):
            assert "not observed in stock in " in t or not zeros
        if "720" in str(p) or p.name.endswith("730-hours") or "price-comparison" in str(p) or "cheapest-a100" in str(p):
            pass
        if "price-comparison" in str(p) or "cheapest-a100" in str(p):
            assert HOURS_PER_MONTH_NOTE in t
            assert RATE_FOOTNOTE in t
            if zeros:
                n = zeros[0]["availability_rate_7d"]["known_checks"]
                unit = "check" if n == 1 else "checks"
                assert f"not observed in stock in {n} {unit}" in t
            if small:
                assert "small sample, N=" in t
        if "730-hours" in str(p):
            assert HOURS_PER_MONTH_NOTE in t
            assert "not observed in stock in N checks" in t


def test_hours_per_month_constant_is_the_average_year():
    assert HOURS_PER_MONTH == 24 * 365 // 12 == 730
    assert "720" in HOURS_PER_MONTH_NOTE and "November" in HOURS_PER_MONTH_NOTE
