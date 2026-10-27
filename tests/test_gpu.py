import json
from pathlib import Path
from core.gpu import RATE_SPECS, build_rates, estimate

FEED = json.loads((Path(__file__).resolve().parents[1] / "deals.json").read_text())["deals"]


def test_all_specs_verified_against_feed():
    r = build_rates(FEED)
    assert r["problems"] == [] and len(r["rates"]) == len(RATE_SPECS)


def test_estimate_hourly_vs_flat_and_rank():
    rates = build_rates(FEED)["rates"]
    e = estimate(rates, 100, gpu_filter="A100")
    assert [x["monthly_cost_usd"] for x in e] == sorted(x["monthly_cost_usd"] for x in e)
    th = next(x for x in e if x["deal_id"] == "deal-thundercompute-001")
    assert th["monthly_cost_usd"] == 109.0
    uc = next(x for x in e if x["deal_id"] == "deal-ucartz-001")
    assert uc["monthly_cost_usd"] == 3128.32
    assert estimate(rates, 1000, gpu_filter="4090")[0]["monthly_cost_usd"] == round(798.72 * 2, 2)


def test_affiliate_not_rank_input():
    rates = build_rates(FEED)["rates"]
    a = [x["deal_id"] + x["gpu"] for x in estimate(rates, 200)]
    b = [x["deal_id"] + x["gpu"] for x in estimate([{**r, "affiliate": not r["affiliate"]} for r in rates], 200)]
    assert a == b


def test_no_commission_fields():
    blob = json.dumps(build_rates(FEED)).lower()
    assert "commission" not in blob and "payout" not in blob
