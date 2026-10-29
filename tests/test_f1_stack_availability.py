"""F1: optimize_stack / optimize_agent_stack / estimate_job_cost never pick an explicit out-of-stock row over
in-stock/unknown rows; the cheaper out-of-stock row is named in a note with its checked_at time."""
from core import agent_stack, stack
from core.contract import EXTRA_PROPS
from core.cost_per_job import estimate_job_cost

OOS = {"status": "out of stock when checked", "in_stock": False, "checked_at": "2026-10-29T15:19:43Z", "note": None}
UNK = {"status": "unknown", "in_stock": None, "checked_at": None, "note": "unknown, not sold out."}
TS = "2026-10-29T15:19:43Z"


def _r(adv, price, avail=None, tier="On-demand", interruptible=False):
    r = {"advertiser": adv, "gpu": "A100", "vram_gb": 40, "price_usd": price, "unit": "hour", "tier": tier,
         "verified_at": "2026-10-29T19:00:00Z", "source_url": "https://example.com", "interruptible": interruptible}
    if avail is not None:
        r["availability"] = avail
    return r


VERDA = _r("Verda (formerly DataCrunch)", 0.7965, OOS, "Spot instance (1x GPU)", True)
GPU = {"rates": [VERDA, _r("Hyperstack", 1.08), _r("Lambda", 1.99, UNK)]}
STACK = {"offers": []}


def _line(r):
    return [l for l in r["lines"] if l.get("need") == "gpu_hours" or l.get("component") == "gpu"][0]


def test_optimize_stack_skips_oos_verda():
    l = stack.optimize(STACK, {"gpu_hours": 100}, GPU, gpu_model="A100")["lines"][0]
    assert l["choice"]["vendor"] == "Hyperstack" and l["monthly_cost_usd"] == 108
    assert l["choice"]["in_stock"] is None and l["choice"]["availability"] is None
    assert "Verda" in l["availability_note"] and TS in l["availability_note"] and "79.65" in l["availability_note"]
    v = [a for a in l["alternatives"] if a["vendor"].startswith("Verda")][0]
    assert v["in_stock"] is False and v["availability"] == OOS


def test_optimize_stack_all_oos_flagged():
    l = stack.optimize(STACK, {"gpu_hours": 100}, {"rates": [VERDA]}, gpu_model="A100")["lines"][0]
    assert l["choice"]["vendor"].startswith("Verda") and "no in-stock" in l["availability_note"] and TS in l["availability_note"]


def test_agent_stack_skips_oos_verda():
    l = _line(agent_stack.plan("100 GPU hours on an A100", [], STACK, GPU, gpu_hours=100, gpu_model="A100"))
    assert l["choice"]["vendor"] == "Hyperstack" and l["monthly_cost_usd"] == 108
    assert "Verda" in l["availability_note"] and TS in l["availability_note"]


def test_agent_stack_all_oos_flagged():
    l = _line(agent_stack.plan("100 GPU hours on an A100", [], STACK, {"rates": [VERDA]}, gpu_hours=100, gpu_model="A100"))
    assert l["choice"]["vendor"].startswith("Verda") and "no in-stock" in l["availability_note"]


def test_job_cost_skips_oos():
    r = estimate_job_cost(GPU, "A100", 1, job_hours=100, allow_interruptible=True)
    assert r["results"][0]["vendor"] == "Hyperstack" and r["results"][-1]["in_stock"] is False
    assert "Cheaper but out of stock when checked at " + TS in r["summary"] and "Verda" in r["summary"]


def test_job_cost_all_oos_flagged():
    r = estimate_job_cost({"rates": [VERDA]}, "A100", 1, job_hours=10, allow_interruptible=True)
    assert r["count"] == 1 and "no in-stock" in r["summary"]


def test_schemas_expose_availability():
    for tool in ("optimize_stack", "optimize_agent_stack"):
        props = EXTRA_PROPS[tool]["lines"]["items"]["properties"]
        assert "availability_note" in props
        assert {"availability", "in_stock", "availability_note"} <= set(props["choice"]["properties"])
    assert "in_stock" in EXTRA_PROPS["estimate_job_cost"]["results"]["items"]["properties"]
