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
