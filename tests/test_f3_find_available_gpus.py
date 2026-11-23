"""F3 (Brain #1030): find_available_gpus from existing availability — no invented stock."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import contract  # noqa: E402
from core.deals import find_available_gpus, compare_gpu_prices, DealError  # noqa: E402
from core.gpu_availability import AVAIL_MAX_AGE_H, STATIC_LABEL_STATUS, expires_at  # noqa: E402

NOW = datetime(2026, 11, 23, 18, 0, 0, tzinfo=timezone.utc)
FRESH = "2026-11-23T17:00:00Z"
FRESHER = "2026-11-23T17:30:00Z"
OLDER = "2026-11-23T16:00:00Z"
STALE_8H = "2026-11-23T09:00:00Z"  # 9h before NOW
SHORT_CHECKED = "2026-11-23T17:30:00Z"
SHORT_EXPIRES = "2026-11-23T17:45:00Z"  # 15 min claim, already lapsed at NOW
FEED_PATH = ROOT / "api" / "v1" / "gpu-prices.json"


def _av(in_stock, checked, expires=None, **kw):
    av = {"in_stock": in_stock, "checked_at": checked, "origin": "scout",
          "availability_expires_at": expires or expires_at(checked)}
    av.update(kw)
    return av


def _row(vendor, gpu="H100", price=2.0, av=None, min_gpus=1, **kw):
    r = {
        "advertiser": vendor, "vendor": vendor, "gpu": gpu, "tier": "On-demand",
        "vram_gb": 80, "gpu_count": min_gpus, "min_gpus": min_gpus,
        "hourly_equiv_usd": price, "hourly_usd": price, "billing_unit": "hourly",
        "source_url": f"https://example.test/{vendor.lower().replace(' ', '-')}",
        "verified_at": (av or {}).get("checked_at"),
        "checked_at": (av or {}).get("checked_at"),
        "availability": av or {},
    }
    r.update(kw)
    return r


def _feed(rates, held=None):
    return {"rates": rates, "held_stale": held or [],
            "availability_collected_at": "2026-11-23T12:53:11Z",
            "feed_updated_at": "2026-11-23T12:54:52Z"}


def test_eight_hour_stale_is_unknown_with_last_known():
    rates = [
        _row("Acme", price=2.0, av=_av(True, STALE_8H, expires_at(STALE_8H))),
        _row("Beta", price=3.0, av=_av(True, FRESH)),
    ]
    out = find_available_gpus(_feed(rates), "H100", now=NOW)
    assert [r["advertiser"] for r in out["available"]] == ["Beta"]
    stale = [r for r in out["unknown"] if r["advertiser"] == "Acme"]
    assert len(stale) == 1 and stale[0]["reason"] == "stale" and stale[0]["in_stock"] is None
    assert stale[0]["last_known_in_stock"] is True and stale[0]["last_known_at"].endswith("Z")
    assert stale[0]["availability_stale"] is True
    assert stale[0]["last_known_at"].startswith("2026-11-23T09:00:00")


def test_short_claim_expiry_is_unknown_not_available():
    av = _av(True, SHORT_CHECKED, SHORT_EXPIRES)
    out = find_available_gpus(_feed([_row("VerdaSpot", av=av)]), "H100", now=NOW)
    assert out["available"] == [] and out["available_total"] == 0
    u = out["unknown"][0]
    assert u["reason"] == "stale" and u["in_stock"] is None
    assert u["last_known_in_stock"] is True
    assert u["availability_expires_at"].endswith("Z")


def test_static_label_never_confirms_stock():
    av = {"in_stock": True, "checked_at": FRESH, "origin": "scout",
          "availability_expires_at": expires_at(FRESH),
          "status": STATIC_LABEL_STATUS, "basis": "vendor_static_label"}
    out = find_available_gpus(_feed([_row("Nova", av=av)]), "H100", now=NOW)
    assert out["available"] == [] and out["sold_out"] == []
    assert out["unknown"][0]["reason"] == "static_label" and out["unknown"][0]["in_stock"] is None


def test_no_source_and_seven_day_rate_never_confirm_stock():
    no_src = _row("RunPod", av=_av(None, FRESH, availability_reason="no_source"))
    # A perfect 7d rate must not stand in for a live in_stock reading.
    hist = _row("Vast", av={"in_stock": None, "checked_at": FRESH, "origin": "scout",
                            "availability_reason": None})
    hist["availability_rate_7d"] = {"rate": 1.0, "known_checks": 20, "in_stock_checks": 20,
                                    "window_days": 7, "observed_hours": 168.0, "window_stale": False}
    out = find_available_gpus(_feed([no_src, hist]), "H100", now=NOW)
    assert out["available"] == [] and out["sold_out"] == []
    reasons = {r["advertiser"]: r["reason"] for r in out["unknown"]}
    assert reasons["RunPod"] == "no_source" and reasons["Vast"] == "no_signal"


def test_sold_out_is_not_unknown():
    rates = [
        _row("Hyperstack", price=2.4, av=_av(False, FRESH, availability_reason="out_of_stock")),
        _row("Civo", price=2.1, av=_av(True, FRESH)),
    ]
    out = find_available_gpus(_feed(rates), "H100", now=NOW)
    assert [r["advertiser"] for r in out["available"]] == ["Civo"]
    assert [r["advertiser"] for r in out["sold_out"]] == ["Hyperstack"]
    assert out["sold_out"][0]["in_stock"] is False
    assert all(r["advertiser"] != "Hyperstack" for r in out["unknown"])


def test_quota_and_region_failures_are_unknown_not_sold_out():
    quota = _row("QVendor", av=_av(False, FRESH, availability_reason="quota"))
    region = _row("RVendor", av=_av(False, FRESH, availability_reason="region"))
    out = find_available_gpus(_feed([quota, region]), "H100", now=NOW)
    assert out["available"] == [] and out["sold_out"] == []
    reasons = {r["advertiser"]: r["reason"] for r in out["unknown"]}
    assert reasons["QVendor"] == "quota" and reasons["RVendor"] == "region"


def test_min_gpus_exclusion():
    rates = [
        _row("Node8", price=1.5, av=_av(True, FRESH), min_gpus=8),
        _row("Single", price=2.0, av=_av(True, FRESH), min_gpus=1),
    ]
    out = find_available_gpus(_feed(rates), "H100", gpus=1, now=NOW)
    assert [r["advertiser"] for r in out["available"]] == ["Single"]
    assert out["min_gpus_unmet"] == 1 and out["excluded_min_gpus"][0]["vendor"] == "Node8"
    out8 = find_available_gpus(_feed(rates), "H100", gpus=8, now=NOW)
    assert {r["advertiser"] for r in out8["available"]} == {"Node8", "Single"}


def test_rank_freshness_then_price():
    # Newer but dearer ranks ahead of older cheaper (stock freshness first).
    rates = [
        _row("CheapOld", price=1.0, av=_av(True, OLDER)),
        _row("DearNew", price=3.0, av=_av(True, FRESHER)),
        _row("MidSameTime", price=2.0, av=_av(True, FRESHER)),
    ]
    out = find_available_gpus(_feed(rates), "H100", now=NOW)
    assert [r["advertiser"] for r in out["available"]] == ["MidSameTime", "DearNew", "CheapOld"]


def test_timestamps_are_utc_z():
    out = find_available_gpus(_feed([_row("Civo", av=_av(True, FRESH))]), "H100", now=NOW)
    assert out["as_of"] == "2026-11-23T18:00:00Z"
    assert out["availability_collected_at"] == "2026-11-23T12:53:11Z"
    assert out["feed_updated_at"].endswith("Z")
    row = out["available"][0]
    assert row["checked_at"].endswith("Z") and "T" in row["checked_at"]
    assert row["availability_expires_at"].endswith("Z")


def test_stock_level_passthrough_never_invented():
    with_sl = _row("Lambda", av=_av(True, FRESH, stock_level="9 GPUs free on 2 nodes"))
    without = _row("Civo", price=2.2, av=_av(True, FRESH))
    out = find_available_gpus(_feed([with_sl, without]), "H100", now=NOW)
    by = {r["advertiser"]: r for r in out["available"]}
    assert by["Lambda"]["stock_level"] == "9 GPUs free on 2 nodes"
    assert "stock_level" not in by["Civo"]
    assert "free_gpus" not in by["Lambda"] and "free_gpus" not in by["Civo"]


def test_held_stale_is_unknown_never_available():
    held = [{"vendor": "Azure", "checked_at": FRESH, "reason": "Manual snapshot not re-verified",
             "records": [{"gpu": "H100", "vram_gb": 80, "hourly_usd": 6.0, "tier": "On-demand",
                          "in_stock": True}]}]
    live = _row("Civo", av=_av(True, FRESH))
    out = find_available_gpus(_feed([live], held=held), "H100", now=NOW)
    assert [r["advertiser"] for r in out["available"]] == ["Civo"]
    hs = [r for r in out["unknown"] if r["reason"] == "held_stale"]
    assert hs and hs[0]["advertiser"] == "Azure" and hs[0]["in_stock"] is not True


def test_limit_applies_only_to_available():
    rates = [_row(f"V{i}", price=1.0 + i, av=_av(True, FRESH)) for i in range(5)]
    rates.append(_row("Sold", price=0.5, av=_av(False, FRESH)))
    out = find_available_gpus(_feed(rates), "H100", limit=2, now=NOW)
    assert out["count"] == 2 and len(out["available"]) == 2 and out["available_total"] == 5
    assert out["sold_out_total"] == 1 and len(out["sold_out"]) == 1


def test_unknown_model_is_not_found():
    with pytest.raises(DealError) as ei:
        find_available_gpus(_feed([_row("Civo", av=_av(True, FRESH))]), "NoSuchGPU", now=NOW)
    assert ei.value.code == "not_found"


def test_committed_feed_unchanged():
    raw = FEED_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)
    # Call should be read-only on the committed document.
    find_available_gpus(copy.deepcopy(data), "H100", now=NOW)
    assert hashlib.sha256(FEED_PATH.read_bytes()).hexdigest() == digest
    assert json.loads(FEED_PATH.read_text()) == data


def test_tool_contract_and_jsonschema():
    from mcp_server import server
    from core.contract import output_schema, finalize
    data = _feed([_row("Civo", av=_av(True, FRESH)),
                  _row("Hyperstack", price=2.4, av=_av(False, FRESH))])
    raw = find_available_gpus(data, "H100", now=NOW)
    wrapped = finalize("find_available_gpus", raw, "full")
    import jsonschema
    jsonschema.validate(json.loads(json.dumps(wrapped)), output_schema("find_available_gpus"))
    assert wrapped["ok"] is True and wrapped["as_of"].endswith("Z")
    # registered on the stdio server (hosted entry auto-lists @mcp.tool)
    import asyncio
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert "find_available_gpus" in names
    tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == "find_available_gpus")
    assert tool.annotations.readOnlyHint is True


def test_live_feed_does_not_promote_unknown_or_stale():
    """Sanity on the committed feed: every available row is a firm live in_stock true."""
    data = json.loads(FEED_PATH.read_text())
    out = find_available_gpus(data, "H100", on_demand_only=True)
    for r in out["available"]:
        assert r["in_stock"] is True and r.get("reason") is None
        assert r.get("availability_stale") is not True
    for r in out["sold_out"]:
        assert r["in_stock"] is False
    for r in out["unknown"]:
        assert r["in_stock"] is not True and r.get("reason")
    # compare stays cheapest-first; this tool does not change it
    cmp = compare_gpu_prices(data, "H100", 5)
    assert "results" in cmp
