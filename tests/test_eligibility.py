"""T47: one eligibility contract (core.eligibility) shared by compare_gpu_prices, estimate_job_cost, price-watch
matching (hosted watch + cron facts) and the calculator's stock ordering."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hosted" / "src"))

from core import cost_per_job, eligibility as EL  # noqa: E402
from core.deals import compare_gpu_prices  # noqa: E402
from core.ids import rate_id  # noqa: E402
import watch as W  # noqa: E402

NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _row(vendor, gpu, vram, price, tier="On-demand", interruptible=False, in_stock=None, regions=None):
    ts = _iso(NOW - timedelta(hours=2))
    r = {"advertiser": vendor, "gpu": gpu, "vram_gb": vram, "hourly_equiv_usd": price, "price_usd": price, "unit": "hour",
         "tier": tier, "tier_class": "interruptible" if interruptible else "on-demand", "interruptible": interruptible,
         "billing_unit": "hourly", "billing": "per hour while running", "verified_at": ts, "checked_at": ts,
         "source_url": f"https://example.com/{vendor}", "deal_id": None, "gpu_count": 1, "min_gpus": 1}
    if in_stock is not None or regions:
        c = NOW - timedelta(minutes=5)
        r["availability"] = {"origin": "scout", "in_stock": in_stock, "checked_at": _iso(c),
                             "availability_expires_at": _iso(c + timedelta(hours=1)),
                             **({"available_regions": regions, "regions_expires_at": _iso(c + timedelta(hours=1))} if regions else {})}
    return r


DOC = {"rates": [
    _row("Good80", "A100 SXM", 80, 1.20, in_stock=True, regions=["US"]),
    _row("Small40", "A100 PCIe", 40, 0.70),
    _row("Spot80", "A100 SXM", 80, 0.60, tier="Spot", interruptible=True),
    _row("SoldOut80", "A100 SXM", 80, 0.90, in_stock=False),
    _row("EU80", "A100 SXM", 80, 1.00, in_stock=True, regions=["EU"]),
    _row("NoRegion80", "A100 PCIe", 80, 1.10),
]}
IDS = {r["advertiser"]: rate_id(r) for r in DOC["rates"]}


def _watch_ids(spec):
    return {m["vendor"] for m in W.current_matches(DOC, spec, limit=50)}


def test_a100_80gb_on_demand_watch_never_matches_40gb_spot_or_sold_out():
    spec = W.normalize_watch("A100 80GB", 5, tiers=["on-demand"])
    got = _watch_ids(spec)
    assert {"Good80", "EU80", "NoRegion80"} == got
    assert not {"Small40", "Spot80", "SoldOut80"} & got


def test_parity_local_estimate_and_alert_same_eligible_set():
    c = EL.normalize(gpu="A100 80GB", tiers=["on-demand"])
    local = set(EL.eligible_ids(DOC, c, NOW))
    watch = {IDS[v] for v in _watch_ids(W.normalize_watch("A100 80GB", 5, tiers=["on-demand"]))}
    facts = W.rate_facts(DOC, NOW)
    spec = W.normalize_watch("A100 80GB", 5, tiers=["on-demand"])
    alert = {k for k, f in facts.items() if EL.check(f, W.constraints(spec))["eligible"]}
    assert local == watch == alert == {IDS["Good80"], IDS["EU80"], IDS["NoRegion80"]}


def test_region_unresolved_kept_labelled_and_other_region_dropped():
    out = compare_gpu_prices(DOC, "A100", region="US", now=NOW)
    names = [r["advertiser"] for r in out["results"]]
    assert "EU80" not in names and out["excluded_other_region"] >= 1
    assert names.index("Good80") < names.index("NoRegion80")  # unresolved ranks after resolved
    assert out["region_unresolved"] >= 1
    nr = next(r for r in out["results"] if r["advertiser"] == "NoRegion80")
    assert any(u["constraint"] == "region" for u in nr["eligibility"]["unknown"])
    # a region watch never alerts on an unresolved row
    assert "NoRegion80" not in _watch_ids(W.normalize_watch("A100 80GB", 5, region="US"))


def test_estimate_job_cost_region_and_constraints():
    out = cost_per_job.estimate_job_cost(DOC, "A100 80GB", 1, job_hours=10, region="US", now=NOW)
    vendors = [r["vendor"] for r in out["results"]]
    assert "EU80" not in vendors and "Small40" not in vendors and "Spot80" not in vendors
    assert out["constraints"]["applied"]["region"] == "US"


def test_spot_alias_and_bad_input():
    assert EL.normalize(tiers=["spot"])["tiers"] == ["interruptible"]
    with pytest.raises(EL.EligibilityError):
        EL.normalize(gpu="A100 80GB", vram_gb=40)
    with pytest.raises(W.WatchError):
        W.normalize_watch("A100", 2, in_stock="ignore")
