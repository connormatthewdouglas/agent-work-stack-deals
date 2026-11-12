"""P40 (scraplingdata): next_check_at / will_backfill / backfill_eta from real schedules only. Additive; ranking unchanged."""
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core import check_schedule as C
from core import contract
from core import deals as core

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
NOW = datetime(2026, 11, 11, 22, 30, tzinfo=timezone.utc)


def test_constants_match_the_workflow_files():
    g = (WF / "gpu-refresh.yml").read_text()
    assert f'cron: "{C.GPU_REFRESH_UTC[0][1]} {C.GPU_REFRESH_UTC[0][0]} * * *"' in g
    assert f'cron: "{C.GPU_REFRESH_UTC[1][1]} {C.GPU_REFRESH_UTC[1][0]} * * *"' in g
    assert f'cron: "{C.LIUM_COLLECT[1]} */{C.LIUM_COLLECT[0]} * * *"' in (WF / "lium-collect.yml").read_text()
    assert "collect_lium.py" in (WF / "lium-collect.yml").read_text()
    si = (WF / "scout-import.yml").read_text()
    assert re.search(rf"now\.hour % {C.SCOUT_IMPORT[0]} == 0 and {C.SCOUT_IMPORT[1]} <= now\.minute", si)
    assert "import_scout_wider.py" in si  # the batch price import rides the scout-import run
    assert core.REFRESH_UTC == C.GPU_REFRESH_UTC[0]


def test_price_schedules():
    d = C.price({"price_check": "daily"}, NOW)
    assert d == {"next_check_at": "2026-11-12T10:23:00Z", "will_backfill": True, "backfill_eta": "2026-11-12T14:47:00Z",
                 "next_check_basis": d["next_check_basis"]} and "gpu-refresh" in d["next_check_basis"]
    assert C.price({"price_check": "daily"}, datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc))["next_check_at"] == "2026-11-11T10:23:00Z"
    lium = C.price({"price_check": "manual snapshot", "advertiser": "Lium"}, NOW)
    assert lium["next_check_at"] == "2026-11-11T22:40:00Z" and lium["will_backfill"] is True
    assert C.price({"price_check": "batch", "advertiser": "RunPod"}, NOW)["next_check_at"] == "2026-11-12T00:10:00Z"
    assert C.price({"price_check": "manual snapshot", "advertiser": "Lium"}, datetime(2026, 11, 11, 23, 41, tzinfo=timezone.utc))["next_check_at"] == "2026-11-12T00:40:00Z"
    m = C.price({"price_check": "manual snapshot", "advertiser": "Clore.ai"}, NOW)
    assert (m["next_check_at"], m["will_backfill"], m["backfill_eta"]) == (None, False, None)
    u = C.price({"price_check": "weekly?"}, NOW)
    assert (u["next_check_at"], u["will_backfill"], u["backfill_eta"]) == (None, None, None)


def test_stock_schedules():
    assert C.stock({"availability": {"in_stock": True, "origin": "scout"}, "in_stock": True}, NOW) == {}
    s = C.stock({"availability": {"in_stock": None, "origin": "scout", "availability_stale": True}, "in_stock": None}, NOW)
    assert (s["next_check_at"], s["will_backfill"], s["backfill_eta"]) == ("2026-11-12T00:10:00Z", True, "2026-11-12T00:10:00Z")
    assert C.stock({"availability": {"in_stock": None, "origin": "scout"}}, datetime(2026, 11, 11, 4, 10, tzinfo=timezone.utc))["next_check_at"] == "2026-11-11T04:10:00Z"
    n = C.stock({"availability": {"status": "unknown", "in_stock": None}, "in_stock": None}, NOW)
    assert (n["next_check_at"], n["will_backfill"], n["backfill_eta"]) == (None, False, None)
    a = C.stock({"availability": {"in_stock": None, "origin": "scout"}, "availability_reason_detail": "no_api"}, NOW)
    assert a["will_backfill"] is False


def test_compare_results_brief_full_and_ranking():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    for gpu in ("H100", "A100", "RTX 4090"):
        o = core.compare_gpu_prices(copy.deepcopy(feed), gpu, limit=25, now=NOW)
        for x in o["results"]:
            if x["in_stock"] is None:
                assert set(C.KEYS) <= set(x) and isinstance(x["will_backfill"], bool)
            else:
                assert not set(C.KEYS) & set(x)
        for s in o["stale_prices"]:
            assert set(C.KEYS) <= set(s)
        b = contract.finalize("compare_gpu_prices", copy.deepcopy(o), "brief")
        f = contract.finalize("compare_gpu_prices", copy.deepcopy(o), "full")
        for br, fr in zip(b["results"], f["results"]):
            assert ("will_backfill" in br) == ("will_backfill" in fr) and "next_check_basis" not in br
    # every price older than the stale cut (all-stale branch) and some (mixed branch) carry their schedule
    later = datetime(2026, 12, 30, 12, 0, tzinfo=timezone.utc)
    o = core.compare_gpu_prices(copy.deepcopy(feed), "H100", limit=25, now=later)
    assert o["stale_prices"] and all(s["next_check_basis"] for s in o["stale_prices"])
    mixed = copy.deepcopy(feed)
    old = next(r for r in mixed["rates"] if r.get("gpu") == "H100" and r.get("price_check") == "daily")
    for k in ("verified_at", "last_verified", "checked_at"):
        if k in old:
            old[k] = "2026-10-01T00:00:00Z"
    o = core.compare_gpu_prices(mixed, "H100", limit=25, now=NOW)
    assert o["results"] and o["stale_prices"]
    for s in o["stale_prices"]:
        assert set(C.KEYS) <= set(s)


def test_schema_and_manifest_lockstep():
    sch = contract.output_schema("compare_gpu_prices")["properties"]
    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    t = next(t for t in plugin["tools"] if t["name"] == "compare_gpu_prices")["outputSchema"]["properties"]
    for k in C.KEYS:
        assert t["results"]["items"]["properties"][k] == sch["results"]["items"]["properties"][k]
    assert t["stale_prices"] == sch["stale_prices"]
    doc = (ROOT / "docs/GPU-PRICES-FIELDS.md").read_text()
    assert all(f"`{k}`" in doc for k in C.KEYS[:3])
