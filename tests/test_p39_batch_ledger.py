"""P39 (hermesagentj): batch due ledger from real schedules only. Additive; ranking unchanged."""
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from core import batch_ledger as L
from core import contract
from core import deals as core
from core.ids import rate_id

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
NOW = datetime(2026, 11, 11, 22, 30, tzinfo=timezone.utc)


def test_constants_match_the_workflow_files():
    g = (WF / "gpu-refresh.yml").read_text()
    assert f'cron: "{L.GPU_REFRESH_UTC[0][1]} {L.GPU_REFRESH_UTC[0][0]} * * *"' in g
    assert f'cron: "{L.GPU_REFRESH_UTC[1][1]} {L.GPU_REFRESH_UTC[1][0]} * * *"' in g
    assert f'cron: "{L.LIUM_COLLECT[1]} */{L.LIUM_COLLECT[0]} * * *"' in (WF / "lium-collect.yml").read_text()
    assert "collect_lium.py" in (WF / "lium-collect.yml").read_text()
    si = (WF / "scout-import.yml").read_text()
    assert re.search(rf"now\.hour % {L.SCOUT_IMPORT[0]} == 0 and {L.SCOUT_IMPORT[1]} <= now\.minute", si)
    assert "import_scout_wider.py" in si


def test_expected_at_and_last_expected_at():
    led = {e["build"]: e for e in L.ledger({"rates": []}, NOW)}
    assert led["gpu-refresh"]["expected_at"] == "2026-11-12T10:23:00Z"
    assert led["gpu-refresh"]["last_expected_at"] == "2026-11-11T10:23:00Z"
    assert led["gpu-refresh"]["fallback_expected_at"] == "2026-11-12T14:47:00Z"
    assert led["lium-collect"]["expected_at"] == "2026-11-11T22:40:00Z"
    assert led["lium-collect"]["last_expected_at"] == "2026-11-11T20:40:00Z"
    assert led["scout-import"]["expected_at"] == led["scout-wider"]["expected_at"] == "2026-11-12T00:10:00Z"
    assert led["scout-import"]["last_expected_at"] == "2026-11-11T20:10:00Z"
    # a slot that is due now is both last and next
    at = datetime(2026, 11, 11, 4, 10, tzinfo=timezone.utc)
    s = {e["build"]: e for e in L.ledger({"rates": []}, at)}["scout-import"]
    assert s["expected_at"] == s["last_expected_at"] == "2026-11-11T04:10:00Z"
    morning = datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
    g = {e["build"]: e for e in L.ledger({"rates": []}, morning)}["gpu-refresh"]
    assert g["expected_at"] == "2026-11-11T10:23:00Z" and g["fallback_expected_at"] == "2026-11-11T14:47:00Z"
    assert g["last_expected_at"] == "2026-11-10T10:23:00Z"


def test_membership_matches_feed_and_excludes_no_api():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    rates = [r for r in feed["rates"] if isinstance(r, dict)]
    led = {e["build"]: e for e in L.ledger(feed, NOW)}
    assert [e["build"] for e in L.ledger(feed, NOW)] == list(L.BUILDS)
    assert set(led["gpu-refresh"]["member_rate_ids"]) == {rate_id(r) for r in rates if r.get("price_check") in ("daily", "rotating snapshot") and not str(r.get("advertiser") or "").startswith("Lium")}
    assert set(led["lium-collect"]["member_rate_ids"]) == {rate_id(r) for r in rates if str(r.get("advertiser") or "").startswith("Lium")}
    assert set(led["scout-wider"]["member_rate_ids"]) == {rate_id(r) for r in rates if r.get("price_check") == "batch"}
    scout = [r for r in rates if isinstance(r.get("availability"), dict) and r["availability"].get("origin") == "scout"
             and (r.get("availability_reason_detail") or r["availability"].get("availability_reason_detail")) != "no_api"]
    assert set(led["scout-import"]["member_rate_ids"]) == {rate_id(r) for r in scout}
    assert all(e["member_count"] == len(e["member_rate_ids"]) for e in led.values())
    # a no_api scout row is never in the stock batch
    fake = {"rates": [
        {"advertiser": "Jarvislabs", "gpu": "H100", "vram_gb": 80, "tier": "On-demand", "gpu_count": 1,
         "billing_unit": "hour", "availability": {"origin": "scout", "in_stock": None, "availability_reason_detail": "no_api"},
         "availability_reason_detail": "no_api", "price_check": "daily", "hourly_equiv_usd": 2.0},
        {"advertiser": "RunPod", "gpu": "H100", "vram_gb": 80, "tier": "On-demand", "gpu_count": 1,
         "billing_unit": "hour", "availability": {"origin": "scout", "in_stock": True}, "price_check": "daily",
         "hourly_equiv_usd": 2.1},
    ]}
    s = {e["build"]: e for e in L.ledger(fake, NOW)}["scout-import"]
    assert s["member_count"] == 1 and rate_id(fake["rates"][1]) in s["member_rate_ids"]
    assert rate_id(fake["rates"][0]) not in s["member_rate_ids"]


def test_compare_exposes_ledger_in_full_not_brief_and_ranking_unchanged():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    raw = core.compare_gpu_prices(copy.deepcopy(feed), "H100", limit=25, now=NOW)
    assert "batch_due_ledger" in raw and [e["build"] for e in raw["batch_due_ledger"]] == list(L.BUILDS)
    # membership is the whole feed, not just this GPU, so "in batch vs never in batch" is checkable
    assert raw["batch_due_ledger"] == L.ledger(feed, NOW)
    full = contract.finalize("compare_gpu_prices", copy.deepcopy(raw), "full")
    brief = contract.finalize("compare_gpu_prices", copy.deepcopy(raw), "brief")
    assert "batch_due_ledger" in full and "batch_due_ledger" not in brief
    a = [x["rate_id"] for x in raw["results"]]
    stripped = copy.deepcopy(feed)
    b = [x["rate_id"] for x in core.compare_gpu_prices(stripped, "H100", limit=25, now=NOW)["results"]]
    assert a == b


def test_schema_and_manifest_lockstep():
    sch = contract.output_schema("compare_gpu_prices")["properties"]["batch_due_ledger"]
    assert sch["type"] == "array"
    item = sch["items"]["properties"]
    for k in ("build", "expected_at", "last_expected_at", "member_rate_ids", "member_count", "schedule_basis"):
        assert k in item
    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    t = next(t for t in plugin["tools"] if t["name"] == "compare_gpu_prices")
    assert t["outputSchema"]["properties"]["batch_due_ledger"] == sch
    doc = (ROOT / "docs/GPU-PRICES-FIELDS.md").read_text()
    assert all(f"`{k}`" in doc for k in ("expected_at", "last_expected_at", "member_rate_ids"))
