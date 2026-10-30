"""T37: per-row data_age_hours / degraded / stale flags and the max_data_age_hours filter."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import agent_stack as a
from core import data_age
from core.deals import DealError, compare_gpu_prices

ROOT = Path(__file__).resolve().parents[1]
DEALS = json.loads((ROOT / "api" / "v1" / "deals.json").read_text())["deals"]
GPU = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
STACK = json.loads((ROOT / "api" / "v1" / "stack-pricing.json").read_text())
NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def _row(vendor, hours_old, price):
    ts = (NOW - timedelta(hours=hours_old)).isoformat()
    return {"advertiser": vendor, "gpu": "H100", "vram_gb": 80, "hourly_equiv_usd": price, "price_usd": price, "unit": "hour",
            "tier": "On-demand", "interruptible": False, "billing_unit": "hourly", "verified_at": ts, "checked_at": ts,
            "source_url": "https://example.com", "deal_id": None}


DATA = {"rates": [_row("Fresh", 2, 2.0), _row("Old", 72, 1.5), _row("Ancient", 24 * 10, 1.0)]}


def test_flags_on_each_row():
    out = compare_gpu_prices(DATA, "H100", now=NOW)
    res = {r["advertiser"]: r for r in out["results"]}
    assert "Ancient" not in res  # re28: > 168 h never ranks by default
    res["Ancient"] = compare_gpu_prices(DATA, "H100", max_data_age_hours=24 * 30, now=NOW)["results"][0]
    assert res["Fresh"]["data_age_hours"] == 2.0 and not res["Fresh"]["degraded"] and not res["Fresh"]["stale"]
    assert res["Old"]["data_age_hours"] == 72.0 and res["Old"]["degraded"] and not res["Old"]["stale"]
    assert res["Ancient"]["degraded"] and res["Ancient"]["stale"]
    assert data_age.age_fields({}, NOW) == {"data_age_hours": None, "degraded": True, "stale": True}


def test_max_data_age_excludes_and_counts():
    out = compare_gpu_prices(DATA, "H100", max_data_age_hours=48, now=NOW)
    assert [r["advertiser"] for r in out["results"]] == ["Fresh"]
    assert out["excluded_too_old"] == 2 and out["max_data_age_hours"] == 48
    assert compare_gpu_prices(DATA, "H100", now=NOW)["excluded_too_old"] == 0
    with pytest.raises(DealError):
        compare_gpu_prices(DATA, "H100", max_data_age_hours=1, now=NOW)
    with pytest.raises(DealError):
        compare_gpu_prices(DATA, "H100", max_data_age_hours=0, now=NOW)


def test_optimize_agent_stack_flags_and_filter():
    r = a.plan("fine-tune on H100 100 gpu hours", DEALS, STACK, GPU)
    line = next(l for l in r["lines"] if l["component"] == "gpu")
    for o in [line["choice"]] + line["alternatives"]:
        assert {"data_age_hours", "degraded", "stale"} <= set(o)
    assert r["excluded_too_old"] == 0
    # Pretend it is a year later: every option is older than 24 h, so the line has no fresh data.
    later = datetime.now(timezone.utc) + timedelta(days=365)
    r2 = a.plan("fine-tune on H100 100 gpu hours", DEALS, STACK, GPU, max_data_age_hours=24, now=later)
    l2 = next(l for l in r2["lines"] if l["component"] == "gpu")
    assert l2["status"] == "no_data" and l2["choice"] is None and r2["excluded_too_old"] >= 1
    assert r2["estimate_is_complete"] is False
