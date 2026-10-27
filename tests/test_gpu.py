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
    e4090 = estimate(rates, 1000, gpu_filter="4090")
    assert next(x for x in e4090 if x["deal_id"] == "deal-ucartz-001")["monthly_cost_usd"] == round(798.72 * 2, 2)
    assert e4090[0]["monthly_cost_usd"] == 340.0  # RunPod Community $0.34/hr x 1000 h


def test_affiliate_not_rank_input():
    rates = build_rates(FEED)["rates"]
    a = [x["deal_id"] + x["gpu"] for x in estimate(rates, 200)]
    b = [x["deal_id"] + x["gpu"] for x in estimate([{**r, "affiliate": not r["affiliate"]} for r in rates], 200)]
    assert a == b


def test_no_commission_fields():
    blob = json.dumps(build_rates(FEED)).lower()
    assert "commission" not in blob and "payout" not in blob


def test_families_threshold_and_runpod():
    from core.gpu import MIN_OFFERS, MIN_VENDORS, families
    rates = build_rates(FEED)["rates"]
    assert any(r["deal_id"] == "deal-runpod-001" for r in rates)
    f = families(rates)
    for v in f.values():
        assert v["page"] == (len(v["rates"]) >= MIN_OFFERS and len(v["vendors"]) >= MIN_VENDORS)
    assert f["h100"]["page"] and f["a100"]["page"] and f["rtx-4090"]["page"]
    assert all(r["verified_at"] for v in f.values() for r in v["rates"])
