"""Bjorn 1109: compare_gpu_prices ranks a row only when min_gpus <= the requested GPU count (1 when none is given,
stated in assumptions). Rows sold only as larger allocations are excluded and listed in excluded_min_gpus with the
reason; the count (min_gpus_unmet) is in brief mode too. cheapest_by_form_factor never returns an unmet row. When
every row is unmet the answer is a clear not_found (same handling as serverless-only)."""
import asyncio
import copy
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import deals  # noqa: E402

# Frozen fixture (main 1b47ecc7), not the live feed: the Lium collector rewrites Lium rows, and a live 8x row going away
# made module import raise StopIteration (Lium collector run 42820326406). The checks below are unchanged.
FEED_FILE = ROOT / "tests" / "fixtures" / "gpu-prices-min-gpus-2026-11-10.json"
FEED = json.loads(FEED_FILE.read_text())
LIUM8 = next(r for r in FEED["rates"] if r["advertiser"] == "Lium" and r["gpu"] == "H100 SXM" and r.get("min_gpus") == 8)
NOW = datetime.fromisoformat(LIUM8["verified_at"]) + timedelta(hours=1)  # inside the freshness window


def test_real_lium_h100_8x_row_is_in_the_feed():
    assert LIUM8["hourly_equiv_usd"] == 1.55 and LIUM8["gpu_count"] == 8


def test_lium_8x_not_ranked_for_one_gpu_and_listed_with_reason():
    out = deals.compare_gpu_prices(FEED, "H100", limit=25, now=NOW)
    assert all((r.get("min_gpus") or 1) <= 1 for r in out["results"])
    assert not any(r["advertiser"] == "Lium" and r["hourly_usd"] == 1.55 for r in out["results"])
    ex = next(x for x in out["excluded_min_gpus"] if x["vendor"] == "Lium" and x["hourly_usd"] == 1.55)
    assert ex["min_gpus"] == 8 and ex["reason"] == "sold only as 8-GPU allocations; 1 GPU(s) requested"
    assert out["min_gpus_unmet"] == len(out["excluded_min_gpus"]) >= 1 and out["gpus"] == 1
    assert any("treated as 1 GPU" in a and "excluded_min_gpus" in a for a in out["assumptions"])
    assert "$1.55" not in out["summary"].split(" Cheapest on-demand")[0] and "see excluded_min_gpus" in out["summary"]


def test_lium_8x_ranks_on_per_gpu_price_for_eight_gpus():
    out = deals.compare_gpu_prices(FEED, "H100", limit=25, now=NOW, gpus=8)
    assert any(r["advertiser"] == "Lium" and r["hourly_usd"] == 1.55 for r in out["results"])
    assert out["assumptions"] == [] and all((x["min_gpus"] or 1) > 8 for x in out["excluded_min_gpus"])


def test_cheapest_by_form_factor_never_returns_an_unmet_row():
    out = deals.compare_gpu_prices(FEED, "H100", limit=25, now=NOW)
    assert all(p["hourly_usd"] != 1.55 or p["advertiser"] != "Lium" for p in out.get("cheapest_by_form_factor") or [])
    picks = deals.cheapest_by_form_factor([r for r in FEED["rates"] if r["gpu"].startswith("H100")])
    from core.ids import rate_id
    rows = {rate_id(r): r for r in FEED["rates"] if r["gpu"].startswith("H100")}
    assert picks and all((rows[p["rate_id"]].get("min_gpus") or 1) <= 1 for p in picks)


def test_all_unmet_is_a_clear_not_found():
    data = {**FEED, "rates": [copy.deepcopy(LIUM8)]}
    with pytest.raises(deals.DealError) as e:
        deals.compare_gpu_prices(data, "H100", now=NOW)
    assert e.value.code == "not_found" and "Lium H100 SXM min 8" in e.value.message and "gpus >= 8" in e.value.message
    assert deals.compare_gpu_prices(data, "H100", now=NOW, gpus=8)["results"][0]["hourly_usd"] == 1.55


def test_brief_mode_keeps_the_count():
    from mcp_server import server
    old_file, old_cache = server.gpu_loader.file, server.gpu_loader._cache
    server.gpu_loader.file, server.gpu_loader._cache = str(FEED_FILE), None
    try:
        res = asyncio.run(server.mcp.call_tool("compare_gpu_prices", {"gpu": "H100", "mode": "brief", "max_data_age_hours": 100000}))
    finally:
        server.gpu_loader.file, server.gpu_loader._cache = old_file, old_cache
    out = json.loads((res[0] if isinstance(res, tuple) else res)[0].text)
    assert out["mode"] == "brief" and out["min_gpus_unmet"] >= 1 and out["gpus"] == 1
    assert all((r.get("min_gpus") or 1) <= 1 for r in out["results"])


# ---- Bjorn 1109 (2): serverless/per-second rows never rank in compare or cheapest_by_form_factor -----------------

KOYEB = next(r for r in FEED["rates"] if r["advertiser"] == "Koyeb" and r["gpu"] == "L40S")


def test_real_koyeb_l40s_row_is_serverless():
    from core.serverless import rate_reason
    assert KOYEB["hourly_equiv_usd"] == 1.2 and KOYEB["tier_class"] == "on-demand" and not KOYEB["interruptible"]
    assert rate_reason(KOYEB)


def test_unfiltered_cheapest_by_form_factor_never_picks_koyeb():
    """Pages call cheapest_by_form_factor with unfiltered rows (scripts/gpu_pages._form_split). Real L40S rows; Koyeb and
    a pricier real row share a form so Koyeb would win that form on price alone."""
    rows = [copy.deepcopy(r) for r in FEED["rates"] if r["gpu"] == "L40S"]
    other = min((r for r in rows if r["advertiser"] not in ("Koyeb", "Modal") and r["hourly_equiv_usd"] > KOYEB["hourly_equiv_usd"]
                 and r.get("tier_class") != "reserved"), key=lambda r: r["hourly_equiv_usd"])
    for r in rows:
        if r["advertiser"] == "Koyeb" or r is other:
            r["form_factor"] = "PCIe"
    picks = {p["form_factor"]: p for p in deals.cheapest_by_form_factor(rows)}
    assert picks["PCIe"]["advertiser"] == other["advertiser"] and picks["PCIe"]["hourly_usd"] == other["hourly_equiv_usd"]
    assert not any(p["advertiser"] in ("Koyeb", "Modal") for p in picks.values())


def test_compare_l40s_holds_koyeb_in_held_serverless_not_results():
    out = deals.compare_gpu_prices(FEED, "L40S", limit=25, now=datetime.fromisoformat(KOYEB["verified_at"]) + timedelta(hours=1))
    assert not any(r["advertiser"] in ("Koyeb", "Modal") for r in out["results"])
    assert {h["vendor"] for h in out["held_serverless"]} >= {"Koyeb"} and out["excluded_serverless"] >= 1
    assert all(h["reason"].startswith("serverless/per-second") for h in out["held_serverless"])


# ---- Gauge #130 N2: the on-demand fallback also fires when every on-demand row needs more GPUs -------------------

def test_on_demand_rows_all_multi_gpu_fall_back_to_single_gpu_spot(tmp_path):
    """Real Lium H100 SXM rows: the 8x row relabelled on-demand (the only on-demand row, 8-GPU minimum) plus the real
    1-GPU Lium secure-node row as marketplace. MCP default (on_demand_only=true, 1 GPU) must fall back to all tiers,
    rank the 1-GPU row, list the 8x row in excluded_min_gpus and say why in on_demand_fallback."""
    from mcp_server import server
    od8 = copy.deepcopy(LIUM8)
    od8.update(tier="On-demand node (8x)", tier_class="on-demand", interruptible=False)
    one = copy.deepcopy(next(r for r in FEED["rates"] if r["advertiser"] == "Lium" and r["gpu"] == "H100 SXM" and r.get("min_gpus") == 1))
    data = {**FEED, "rates": [od8, one]}
    with pytest.raises(deals.DealError) as e:
        deals.compare_gpu_prices(data, "H100", now=NOW, on_demand_only=True)
    assert e.value.reason == "min_gpus"

    f = tmp_path / "gpu-prices.json"
    f.write_text(json.dumps(data))
    old_file, old_cache = server.gpu_loader.file, server.gpu_loader._cache
    server.gpu_loader.file, server.gpu_loader._cache = str(f), None
    try:
        res = asyncio.run(server.mcp.call_tool("compare_gpu_prices", {"gpu": "H100", "mode": "full", "max_data_age_hours": 100000}))
    finally:
        server.gpu_loader.file, server.gpu_loader._cache = old_file, old_cache
    out = json.loads((res[0] if isinstance(res, tuple) else res)[0].text)
    assert out.get("ok", True) and [r["min_gpus"] for r in out["results"]] == [1]
    assert "larger allocation than 1 GPU" in out["on_demand_fallback"] and "rates from other tiers" in out["on_demand_fallback"]
    assert [x["min_gpus"] for x in out["excluded_min_gpus"]] == [8] and out["min_gpus_unmet"] == 1


# ---- Gauge #130 re-review nits ----------------------------------------------------------------------------------

CLORE_MKT = next(r for r in FEED["rates"] if r.get("price_status") == "marketplace" and r.get("lowest_offer_usd") is not None)


@pytest.mark.parametrize("lowest", ["drop", None, "n/a", True])
def test_summary_survives_a_marketplace_row_without_a_numeric_lowest_offer(lowest):
    """Real Clore.ai marketplace row with lowest_offer_usd removed / null / non-numeric: the summary still builds and
    says 'variable marketplace median' without inventing a lowest offer."""
    row = copy.deepcopy(CLORE_MKT)
    if lowest == "drop":
        row.pop("lowest_offer_usd")
    else:
        row["lowest_offer_usd"] = lowest
    now = datetime.fromisoformat(row["verified_at"]) + timedelta(hours=1)
    out = deals.compare_gpu_prices({**FEED, "rates": [row]}, row["gpu"], now=now, on_demand_only=False)
    assert out["results"] and "variable marketplace median" in out["summary"] and "lowest offer" not in out["summary"]


def test_summary_keeps_the_lowest_offer_when_present():
    now = datetime.fromisoformat(CLORE_MKT["verified_at"]) + timedelta(hours=1)
    out = deals.compare_gpu_prices({**FEED, "rates": [copy.deepcopy(CLORE_MKT)]}, CLORE_MKT["gpu"], now=now, on_demand_only=False)
    assert f"lowest offer ${CLORE_MKT['lowest_offer_usd']:g}/hr" in out["summary"]


def test_tool_description_lists_every_excluded_min_gpus_field():
    from core.contract import EXTRA_PROPS
    from mcp_server import server
    doc = " ".join((server.compare_gpu_prices.__doc__ or "").split())
    fields = list(EXTRA_PROPS["compare_gpu_prices"]["excluded_min_gpus"]["items"]["properties"])
    assert len(fields) == 12  # P43 (additive): + min_bill_usd_per_hour, min_bill_basis
    listed = doc[doc.index("listed in excluded_min_gpus ("):].split(")")[0]
    assert all(f in listed.replace(",", " ").replace("(", " ").split() for f in fields), (fields, listed)
