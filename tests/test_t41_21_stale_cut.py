"""T41-21: the gate's eligible pay-as-you-go minimum uses the page's 168 h stale cut (core.data_age), same clock."""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "release_gate"))
from t41_counts import payg_eligible  # noqa: E402

NOW = datetime(2026, 11, 11, 18, 4, tzinfo=timezone.utc)  # the 1:04 PM ET rebuild (4ae4261f)
AWS_A10G = {"rate_id": "r_f7f27a7439ba", "advertiser": "Amazon Web Services", "gpu": "A10G", "hourly_usd": None,
            "hourly_equiv_usd": 1.006, "min_gpus": 1, "price_status": "listed", "price_check": "manual snapshot",
            "tier": "On-demand EC2 instance g5.xlarge", "verified_at": "2026-11-04T16:11:55+00:00",
            "checked_at": "2026-11-04T16:11:55+00:00"}


def _low_cell(rows):  # what T41-21 compares: no eligible row means the page must say "no single-GPU ..."
    e = payg_eligible(rows, NOW)
    return "no single-GPU pay-as-you-go rate" if not e else e[0]


def test_stale_aws_a10g_is_excluded_and_no_single_gpu_passes():
    assert payg_eligible([AWS_A10G], NOW) == []
    assert "no single-GPU" in _low_cell([AWS_A10G])


def test_fresh_rows_still_count_including_equivalent_only():
    fresh_equiv = {**AWS_A10G, "rate_id": "r_fresh_equiv", "verified_at": "2026-11-11T12:00:00+00:00",
                   "checked_at": "2026-11-11T12:00:00+00:00"}
    fresh_quoted = {**fresh_equiv, "rate_id": "r_fresh_quoted", "hourly_usd": 1.2, "hourly_equiv_usd": 1.2}
    assert [r["rate_id"] for r in payg_eligible([AWS_A10G, fresh_quoted, fresh_equiv], NOW)] == ["r_fresh_equiv", "r_fresh_quoted"]
    # Same AWS row seen at a clock inside its 7 days: it counts again (cut is age, not equivalent-only).
    assert [r["rate_id"] for r in payg_eligible([AWS_A10G], datetime(2026, 11, 10, tzinfo=timezone.utc))] == ["r_f7f27a7439ba"]


def test_gate_matches_page_engine_on_the_stale_row():
    from core.deals import compare_gpu_prices
    out = compare_gpu_prices({"rates": [AWS_A10G]}, "A10G", gpus=1, limit=1, on_demand_only=False, include_reserved=False, now=NOW)
    assert out["count"] == 0 and out["excluded_stale"] == 1 and payg_eligible([AWS_A10G], NOW) == []


def _row(vendor, price, verified_at, gpu="H200"):
    return {"advertiser": vendor, "gpu": gpu, "hourly_equiv_usd": price, "min_gpus": 1,
            "tier": "on-demand", "tier_class": "on-demand", "price_status": "listed",
            "verified_at": verified_at, "checked_at": verified_at}


def test_cheaper_degraded_row_leads_dearer_fresh_row_for_t41_21_and_page_cell():
    """The summary 'lowest' cell must match T41-21, not compare_gpu_prices lead_key.

    A cheaper row at 49 h (degraded, still inside 168 h) must beat a dearer fresh
    (39 h) row. lead_key would name the fresh row first; that is tool ranking only.
    """
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from core.deals import compare_gpu_prices, payg_eligible as core_payg
    import gpu_pages

    clock = datetime(2026, 11, 15, 22, 34, tzinfo=timezone.utc)
    cheap = _row("Verda (formerly DataCrunch)", 3.318, "2026-11-13T21:19:40+00:00")
    dear = _row("Lium", 3.80, "2026-11-14T07:00:07+00:00")
    rows = [dear, cheap]

    # Shared helper: gate and page agree, and the re-export is the same object.
    assert payg_eligible is core_payg
    assert [r["advertiser"] for r in payg_eligible(rows, clock)] == [
        "Verda (formerly DataCrunch)", "Lium"
    ]
    assert gpu_pages.lowest_payg(rows, clock)["advertiser"] == "Verda (formerly DataCrunch)"
    assert gpu_pages.lowest_payg(rows, clock)["hourly_equiv_usd"] == 3.318

    # compare_gpu_prices still prefers the fresh dearer row (lead_key). That is
    # tool ranking; the page lowest cell must not use it.
    out = compare_gpu_prices({"rates": rows}, "H200", gpus=1, limit=2, on_demand_only=False,
                             include_reserved=False, now=clock)
    assert out["results"][0]["advertiser"] == "Lium"


def test_lowest_payg_follows_pinned_clock_not_lead_key(monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import gpu_pages

    clock = datetime(2026, 11, 15, 22, 34, tzinfo=timezone.utc)
    monkeypatch.setenv("LW_AVAIL_NOW", clock.isoformat())
    cheap = _row("CloudRift", 0.69, "2026-11-13T21:17:14+00:00", gpu="L40S")
    dear = _row("Lium", 0.74, "2026-11-14T07:00:07+00:00", gpu="L40S")
    assert gpu_pages.lowest_payg([dear, cheap])["advertiser"] == "CloudRift"
    # Same rows at a clock where both are fresh: still the cheaper one.
    early = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)
    assert gpu_pages.lowest_payg([dear, cheap], early)["advertiser"] == "CloudRift"
    # Same rows past the 168 h cut for the cheaper row only: then the dearer fresh/current wins.
    late = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)  # cheap ~171 h, dear ~161 h
    assert gpu_pages.lowest_payg([dear, cheap], late)["advertiser"] == "Lium"
