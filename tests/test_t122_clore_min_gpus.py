"""#122 (Bjorn, from Gauge's Clore QA 2026-11-09 and Scout's per-allocation Vast rows):
A) Clore importer: a stock claim needs a second read >= 60 s later (else in_stock null, held rows always null);
   provenance text describes the actual method (no hardcoded 'Gauge'); an import that changes no row does not bump
   checked_at/verified_at (so feed_updated_at does not move).
B) min_gpus: a row sold only as a multi-GPU allocation never ranks cheapest for a 1-GPU request (compare_gpu_prices,
   cheapest_by_form_factor, core.gpu.estimate, the agent stack); no GPU count means 1 GPU and says so in assumptions;
   the wider importer keeps allocation sizes (tier, gpu_count) as separate rows."""
import copy
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from core import agent_stack, deals, gpu as G, stack  # noqa: E402

spec = importlib.util.spec_from_file_location("ics122", ROOT / "scripts" / "import_clore_snapshot.py")
ics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ics)

SUM = {"RTX 4090": {"available_with_usd_price": 9, "median": 0.5, "range_on_demand": [0.3, 1.0],
                    "lowest_available_on_demand_usd_gpu_hr": 0.3, "listings_available": 12},
       "A100": {"available_with_usd_price": 3, "lowest_available_on_demand_usd_gpu_hr": 0.3333, "listings_available": 3}}


def _snap(**k):
    return {"source_url": "https://api.clore.ai/v1/marketplace", "checked_at": "2026-11-02T15:14:19Z", "listings": [],
            "summary": copy.deepcopy(SUM), **k}


def _doc():
    return copy.deepcopy(json.loads(ics.PATH.read_text()))


def _by(doc):
    return {r["gpu"]: r for r in doc["records"]}


# ---- A) Clore importer ------------------------------------------------------------------------------------------

def test_clore_single_read_leaves_in_stock_null():
    doc = _doc()
    ics.apply(doc, _snap())
    a = _by(doc)["RTX 4090"]["availability"]
    assert a["in_stock"] is None and a["second_read_at"] is None and "single read" in a["note"]


def test_clore_second_read_60s_apart_sets_in_stock_and_short_gap_does_not():
    s = _snap(second_read_at="2026-11-02T15:15:49Z")
    s["summary"]["RTX 4090"]["second_read_listings_available"] = 11
    doc = _doc()
    ics.apply(doc, s)
    a = _by(doc)["RTX 4090"]["availability"]
    assert a["in_stock"] is True and a["second_read_gap_s"] == 90 and a["first_read_at"] == "2026-11-02T15:14:19+00:00"
    s2 = _snap(second_read_at="2026-11-02T15:14:49Z")
    s2["summary"]["RTX 4090"]["second_read_listings_available"] = 11
    doc2 = _doc()
    ics.apply(doc2, s2)
    assert _by(doc2)["RTX 4090"]["availability"]["in_stock"] is None


def test_clore_held_row_never_claims_stock_even_with_second_read():
    s = _snap(second_read_at="2026-11-02T15:16:19Z")
    s["summary"]["A100"]["second_read_listings_available"] = 3
    doc = _doc()
    ics.apply(doc, s)
    r = _by(doc)["A100 SXM"]
    assert "stale" in r and r["availability"]["in_stock"] is None and "row held" in r["availability"]["note"]


def test_clore_provenance_is_neutral_and_states_the_method():
    doc = _doc()
    ics.apply(doc, _snap(method="median of available USD listings (test method)"))
    blob = json.dumps({k: doc[k] for k in ("source_note", "manual_snapshot")})
    assert "Gauge" not in blob
    assert "median of available USD listings (test method)" in doc["source_note"]
    doc2 = _doc()
    ics.apply(doc2, _snap())
    assert "Gauge" not in doc2["source_note"] and ics.METHOD in doc2["source_note"]


def test_clore_unchanged_reimport_keeps_timestamps():
    first, _, changed = ics.apply_if_changed(_doc(), _snap())
    assert changed
    later = _snap(checked_at="2026-11-03T09:00:00Z")  # same numbers, later snapshot time
    again, log, changed2 = ics.apply_if_changed(first, later)
    assert not changed2 and again is first and "nothing written" in log[-1]
    assert all(r["checked_at"] == "2026-11-02T15:14:19+00:00" for r in again["records"] if r["gpu"] in ics.MAP)
    moved = _snap(checked_at="2026-11-03T09:00:00Z")
    moved["summary"]["RTX 4090"]["median"] = 0.55
    out, _, changed3 = ics.apply_if_changed(first, moved)
    assert changed3 and _by(out)["RTX 4090"]["checked_at"] == "2026-11-03T09:00:00+00:00"


# ---- B) min_gpus ------------------------------------------------------------------------------------------------

FEED = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
NOW = datetime.fromisoformat("2026-11-06T08:00:00+00:00")


def _data():
    """Two real Lium H100 SXM rates reshaped: a 1-GPU row at $2.05 and a 2-GPU-minimum allocation at $0.50/GPU
    (whole allocation $1.00/hr, cheaper per job than $2.05 too), plus a PCIe row so form-factor picks appear."""
    one, multi = [copy.deepcopy(x) for x in FEED["rates"] if x["advertiser"] == "Lium" and x["gpu"] == "H100 SXM"][:2]
    if one["min_gpus"] > 1:
        one, multi = multi, one
    one.update(rate_id="r_one", snapshot_at="2026-11-06T06:49:42+00:00", verified_at="2026-11-06T06:49:42+00:00",
               checked_at="2026-11-06T06:49:42+00:00", hold_after="2026-11-13T06:49:42+00:00")
    multi.update(rate_id="r_two", price_usd=0.5, hourly_equiv_usd=0.5, gpu_count=2, min_gpus=2, server_price_usd=1.0,
                 server_hourly_usd=1.0, interruptible=False, tier_class="marketplace", tier="Marketplace secure node (2x GPU)")
    pcie = copy.deepcopy(one)
    pcie.update(rate_id="r_pcie", gpu="H100 PCIe", form_factor="PCIe", form_class="PCIe", price_usd=2.4, hourly_equiv_usd=2.4)
    return {**FEED, "rates": [multi, one, pcie]}


def test_compare_never_names_a_multi_gpu_minimum_cheapest_for_one_gpu():
    out = deals.compare_gpu_prices(_data(), "H100", now=NOW)
    assert out["results"][0]["min_gpus"] == 1 and out["results"][0]["hourly_usd"] == 2.05
    # Bjorn 1109: the 2-GPU-minimum row is not ranked at all for 1 GPU; it is listed in excluded_min_gpus
    assert all(r["min_gpus"] == 1 for r in out["results"]) and "$0.5" not in out["summary"].split(".")[0]
    assert out["min_gpus_unmet"] == 1 and out["excluded_min_gpus"][0]["min_gpus"] == 2
    sxm = next(p for p in out["cheapest_by_form_factor"] if p["form_factor"] == "SXM")
    assert sxm["hourly_usd"] == 2.05


def test_compare_no_gpu_count_is_one_and_says_so():
    out = deals.compare_gpu_prices(_data(), "H100", now=NOW)
    assert out["gpus"] == 1 and any("treated as 1 GPU" in a for a in out["assumptions"])
    two = deals.compare_gpu_prices(_data(), "H100", now=NOW, gpus=2)
    assert two["assumptions"] == [] and two["results"][0]["hourly_usd"] == 0.5


def test_cheapest_by_form_factor_skips_unmet_minimum():
    rows = _data()["rates"]
    picks = {p["form_factor"]: p["hourly_usd"] for p in deals.cheapest_by_form_factor(rows)}
    assert picks["SXM"] == 2.05
    assert {p["form_factor"]: p["hourly_usd"] for p in deals.cheapest_by_form_factor(rows, gpus=2)}["SXM"] == 0.5


def test_estimate_ranks_rows_that_fit_the_gpu_count_first():
    rates = _data()["rates"]
    assert G.estimate(rates, 100, gpus=1, gpu_filter="H100")[0]["min_gpus"] == 1
    assert G.estimate(rates, 100, gpus=2, gpu_filter="H100")[0]["min_gpus"] == 2


def test_agent_stack_gpu_choice_honors_min_gpus_and_states_assumption():
    opts = stack._gpu_options(_data(), 100, "H100", set())
    assert opts[0].get("min_gpus_unmet") is not True and any(o.get("min_gpus_unmet") for o in opts)
    r = agent_stack.plan("fine-tune on H100 100 gpu hours", [], {}, _data())
    line = next(l for l in r["lines"] if l["component"] == "gpu")
    assert line["choice"]["gpus_billed"] == 1 and line["choice"]["monthly_cost_usd"] == 205.0  # not the 2-GPU $100 allocation
    assert any("treated as 1 GPU" in a for a in r["assumptions"])


def test_wider_importer_keeps_allocation_sizes_separate():
    from import_scout_wider import apply
    base = {"vendor": "RunPod", "gpu_model": "H100 SXM", "vram_gb": 80, "tier": "On-demand",
            "source_url": "https://example.test/pricing", "source_detail": "https://example.test/api",
            "verified_at": "2026-10-31T13:08:29+00:00", "batch": "wider-gpu", "price_basis": "api.price_per_hour"}
    rows = [{**base, "price_usd_hr": 2.0, "gpu_count": 1}, {**base, "price_usd_hr": 1.8, "gpu_count": 2, "min_gpus": 2},
            {**base, "price_usd_hr": 1.7, "gpu_count": 4, "min_gpus": 4}]
    doc = {"vendor": "RunPod", "deal_id": None, "source_url": "https://example.test/pricing",
           "checked_at": "2026-10-31T13:08:29+00:00", "records": []}
    out, unresolved, total = apply({"RunPod": doc}, rows)
    assert total == 3 and not unresolved
    assert sorted(r.get("gpu_count", 1) for r in out["RunPod"]["records"]) == [1, 2, 4]


def test_mcp_compare_accepts_gpus_and_keeps_assumption_in_brief():
    import asyncio
    from mcp_server import server
    async def go(args):
        res = await server.mcp.call_tool("compare_gpu_prices", args)
        blocks = res[0] if isinstance(res, tuple) else res
        return json.loads(blocks[0].text)
    brief = asyncio.run(go({"gpu": "H100"}))
    assert brief["gpus"] == 1 and any("treated as 1 GPU" in a for a in brief["assumptions"])
    assert all(r.get("min_gpus", 1) <= 1 or r.get("min_gpus_unmet") for r in brief["results"])
    two = asyncio.run(go({"gpu": "H100", "gpus": 8}))
    assert two["gpus"] == 8 and two["assumptions"] == []


# ---- #122 (Bjorn 1109): RTX 5090 D identity; N-GPU requests -------------------------------------------------------

def test_rtx_5090_d_is_its_own_identity_and_never_aliases():
    from core import gpu_identity
    d, std = gpu_identity.identity("RTX 5090 D"), gpu_identity.identity("RTX 5090")
    assert d["model"] == "RTX 5090 D" and std["model"] == "RTX 5090"
    assert d["nominal_memory"]["gb"] == 32 and "32 GB GDDR7" in d["nominal_memory"]["quote"]
    # Bjorn 1109: NVIDIA's own 5090 D page as archived 2025-03-10 is the source (the live URL now shows the 24 GB v2)
    assert d["nominal_memory"]["source_url"] == ("https://web.archive.org/web/20250310021605/"
                                                 "https://www.nvidia.cn/geforce/graphics-cards/50-series/rtx-5090-d/")
    assert d["usable_memory"]["gb"] is None
    assert gpu_identity.identity("RTX 5090 D v2") is None  # the 24 GB v2 is a different SKU, not this entry
    assert G.canonical_model("RTX 5090 D") == "RTX 5090 D" and G.family_of("RTX 5090 D") is None
    assert G.canonical_model("RTX 5090 D v2") != "RTX 5090"
    assert G.canonical_model("RTX 5090") == "RTX 5090" and G.family_of("RTX 5090") == "rtx-5090"


def test_two_gpu_request_ranks_qualifying_allocation_by_per_gpu_price():
    """Bjorn 1109 (1): for N GPUs, rows with min_gpus <= N rank on per-GPU price as usual. Real Lium L40S rows:
    the 2x-minimum secure node qualifies for N=2 and leads on per-GPU price; for N=1 it ranks after rows that fit."""
    rates = [copy.deepcopy(r) for r in FEED["rates"] if r["advertiser"] == "Lium" and r["gpu"] == "L40S"]
    two = [r for r in rates if r.get("min_gpus") == 2]
    assert two, "real Lium L40S 2x row expected in the feed"
    one = copy.deepcopy(two[0])
    one.update(price_usd=two[0]["hourly_equiv_usd"] + 0.4, hourly_equiv_usd=round(two[0]["hourly_equiv_usd"] + 0.4, 4),
               min_gpus=1, gpu_count=1, server_price_usd=None, server_hourly_usd=None, tier="Marketplace secure node (1x)")
    data = {**FEED, "rates": [one, two[0]]}
    when = datetime.fromisoformat(two[0]["verified_at"])
    r2 = deals.compare_gpu_prices(data, "L40S", now=when, gpus=2)["results"]
    assert [x["min_gpus"] for x in r2] == [2, 1] and not any(x.get("min_gpus_unmet") for x in r2)
    assert [x["hourly_usd"] for x in r2] == sorted(x["hourly_usd"] for x in r2)
    o1 = deals.compare_gpu_prices(data, "L40S", now=when)  # Bjorn 1109: for 1 GPU the 2x row is excluded, not ranked
    assert [x["min_gpus"] for x in o1["results"]] == [1] and [x["min_gpus"] for x in o1["excluded_min_gpus"]] == [2]
    assert G.estimate(data["rates"], 100, gpus=2, gpu_filter="L40S")[0]["min_gpus"] == 2
    opts = stack._gpu_options(data, 100, "L40S", set(), gpus=2)
    assert not any(o.get("min_gpus_unmet") for o in opts) and opts[0]["monthly_cost_usd"] < opts[1]["monthly_cost_usd"]
    assert stack._gpu_options(data, 100, "L40S", set())[0].get("min_gpus_unmet") is not True
