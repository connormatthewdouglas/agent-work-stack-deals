"""The shared serverless/per-second rule (core/serverless.rate_reason) also governs the agent stack
(stack._gpu_options -> optimize_stack / optimize_agent_stack / agent_stack.plan) and the /cost/ pages, so the real
Modal and Koyeb rows can never be named cheapest there, whatever their price (Gauge #125 non-blocking 1 and 2)."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from core import agent_stack, stack  # noqa: E402
from core.serverless import rate_reason  # noqa: E402
import cost_pages  # noqa: E402

FEED = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())


def _cheap_serverless(gpu="L40S"):
    """The feed with the real Modal and Koyeb rows for `gpu` repriced to $0.01/hr (cheaper than anything else)."""
    data = copy.deepcopy(FEED)
    hit = []
    for r in data["rates"]:
        if r["advertiser"] in ("Modal", "Koyeb") and r["gpu"] == gpu:
            assert rate_reason(r), r["tier"]
            r.update(price_usd=0.01, hourly_equiv_usd=0.01)
            hit.append(r["advertiser"])
    assert sorted(hit) == ["Koyeb", "Modal"]
    return data


def test_gpu_options_never_include_modal_or_koyeb():
    for gpu in ("L40S", "H100", "A100", "H200"):
        opts = stack._gpu_options(_cheap_serverless("L40S"), 100, gpu, set())
        assert opts and not {o["vendor"] for o in opts} & {"Modal", "Koyeb"}, gpu
    held = stack.held_serverless(FEED, "L40S")
    assert {h["vendor"] for h in held} == {"Koyeb", "Modal"} and all(h["reason"].startswith("serverless/per-second") for h in held)


def test_optimize_stack_lists_held_rows_and_never_picks_them():
    line = stack.optimize({"offers": []}, {"gpu_hours": 100}, _cheap_serverless(), gpu_model="L40S")["lines"][0]
    names = {line["choice"]["vendor"]} | {a["vendor"] for a in line.get("alternatives") or []}
    assert not names & {"Modal", "Koyeb"}
    assert line["excluded_serverless"] == 2 and {h["vendor"] for h in line["held_serverless"]} == {"Koyeb", "Modal"}


def test_agent_stack_plan_never_names_serverless_cheapest():
    r = agent_stack.plan("fine-tune on L40S 100 gpu hours", [], {}, _cheap_serverless(), max_data_age_hours=100000)
    line = next(x for x in r["lines"] if x["component"] == "gpu")
    assert line["choice"]["vendor"] not in ("Modal", "Koyeb")
    assert not {a["vendor"] for a in line.get("alternatives") or []} & {"Modal", "Koyeb"}
    # Modal's rows carry a deal_id the plan's compliance filter already drops, so Koyeb is the held row here
    assert line["excluded_serverless"] >= 1 and "Koyeb" in {h["vendor"] for h in line["held_serverless"]}


def test_cost_pages_use_the_shared_rule_not_the_tier_word():
    """A per-second row whose tier text lacks the word 'serverless' (real Modal L40S, relabelled as an on-demand,
    non-interruptible tier) must still never reach /cost/: the shared rule sees price_per_second_usd / billing_unit."""
    data = copy.deepcopy(FEED)
    m = next(r for r in data["rates"] if r["advertiser"] == "Modal" and r["gpu"] == "L40S")
    m.update(tier="Nvidia L40S GPU (billed per second)", tier_class="on-demand", interruptible=False,
             price_usd=0.01, hourly_equiv_usd=0.01)
    k = next(r for r in data["rates"] if r["advertiser"] == "Koyeb" and r["gpu"] == "L40S")
    k.update(tier="GPU instance", billing="per second while running", price_usd=0.01, hourly_equiv_usd=0.01)
    assert rate_reason(m) and rate_reason(k)
    rows = [r for v in cost_pages.eligible(data, "L40S").values() for r in v]
    assert rows and not {r["advertiser"] for r in rows} & {"Modal", "Koyeb"}


def test_cost_pages_real_feed_has_no_serverless_rows():
    for fam in cost_pages.GPUS.values():
        assert not any(rate_reason(r) for v in cost_pages.eligible(FEED, fam).values() for r in v), fam
