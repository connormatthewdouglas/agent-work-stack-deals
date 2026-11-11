"""P36: keep the last firm stock answer beside a lapsed claim (additive; ranking unchanged; never invented)."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import contract
from core import deals as core
from core.gpu_availability import LAST_KNOWN_KEYS, last_known, stale_guard

ROOT = Path(__file__).resolve().parents[1]
CHECK = "2026-11-11T12:00:00Z"
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def _claim(in_stock):
    return {"status": "out of stock when checked" if in_stock is False else "available when checked", "in_stock": in_stock,
            "checked_at": CHECK, "origin": "scout", "availability_expires_at": "2026-11-11T13:00:00Z", "max_age_hours": 1.0}


def test_fresh_claim_unchanged_and_mcp_reports_it_as_last_known():  # full mode; brief omits them for a current claim
    a = _claim(True)
    g = stale_guard(a, T0 + timedelta(minutes=30))
    assert g is a and not set(LAST_KNOWN_KEYS) & set(g)  # feed: same object, existing fields only
    out = contract.finalize("compare_gpu_prices", {"gpu": "H100", "summary": "", "count": 1, "results": [
        {"rank": 1, "rate_id": "r_000000000001", "advertiser": "A", "gpu": "H100", "hourly_usd": 2.0, "source_url": "https://a.example",
         "availability": g, "in_stock": True}]}, "full")
    av = out["results"][0]["availability"]
    assert av["in_stock"] is True and av["last_known_in_stock"] is True and av["last_known_at"] == CHECK


def test_lapsed_claim_keeps_last_value_beside_stale_mark():
    for firm in (True, False):
        g = stale_guard(_claim(firm), T0 + timedelta(hours=2))
        assert g["availability_stale"] is True and g["in_stock"] is None  # existing semantics unchanged
        assert g["last_known_in_stock"] is firm and g["last_known_at"] == CHECK
        again = stale_guard(g, T0 + timedelta(hours=5))  # re-checked at MCP read time: kept, not lost
        assert again["last_known_in_stock"] is firm and again["last_known_at"] == CHECK
        assert core.out_of_stock({"availability": g}) is False  # a lapsed claim is unknown for ranking, never in/out of stock


def test_never_claimed_is_null():
    g = stale_guard(_claim(None), T0 + timedelta(hours=2))
    assert g["last_known_in_stock"] is None and g["last_known_at"] is None
    assert last_known({"status": "unknown", "in_stock": None}) == (None, None)
    assert last_known({"in_stock": True}) == (None, None)  # no check time: not a firm claim we can date
    assert last_known({"in_stock": None, "last_known_in_stock": "yes", "last_known_at": CHECK}) == (None, None)


def test_brief_rows_carry_the_fields():
    lapsed = stale_guard(_claim(False), T0 + timedelta(hours=2))
    raw = {"gpu": "H100", "summary": "", "count": 2, "results": [
        {"rank": 1, "rate_id": "r_000000000001", "advertiser": "A", "gpu": "H100", "hourly_usd": 2.0, "source_url": "https://a.example",
         "availability": lapsed, "in_stock": None},
        {"rank": 2, "rate_id": "r_000000000002", "advertiser": "B", "gpu": "H100", "hourly_usd": 3.0, "source_url": "https://b.example",
         "availability": {"status": "unknown", "in_stock": None}, "in_stock": None}]}
    b = contract.finalize("compare_gpu_prices", copy.deepcopy(raw), "brief")["results"]
    assert (b[0]["last_known_in_stock"], b[0]["last_known_at"], b[0]["in_stock"]) == (False, CHECK, None)
    assert "last_known_in_stock" not in b[1] and "last_known_at" not in b[1]  # brief omits them when null (absent = null)


def test_ranking_ignores_last_known_on_the_committed_feed():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    stripped = copy.deepcopy(feed)
    for r in stripped["rates"]:
        if isinstance(r.get("availability"), dict):
            for k in LAST_KNOWN_KEYS:
                r["availability"].pop(k, None)
    for gpu in ("H100", "A100", "RTX 4090"):
        a = [x["rate_id"] for x in core.compare_gpu_prices(feed, gpu, limit=25, now=T0)["results"]]
        b = [x["rate_id"] for x in core.compare_gpu_prices(stripped, gpu, limit=25, now=T0)["results"]]
        assert a == b, gpu


def test_schema_and_manifest_lockstep():
    s = contract.output_schema("compare_gpu_prices")["properties"]["results"]["items"]["properties"]
    assert s["last_known_in_stock"]["type"] == ["boolean", "null"] and s["last_known_at"]["type"] == ["string", "null"]
    assert {"last_known_in_stock", "last_known_at"} <= set(contract.SPEC["compare_gpu_prices"][4])
    assert {"last_known_in_stock", "last_known_at"} <= set(contract.SPEC["estimate_job_cost"][4])
    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    tool = next(t for t in plugin["tools"] if t["name"] == "compare_gpu_prices")
    p = tool["outputSchema"]["properties"]["results"]["items"]["properties"]
    assert p["last_known_in_stock"] == s["last_known_in_stock"] and p["last_known_at"] == s["last_known_at"]
