"""T41-03 ranked total: serverless is always held; min_gpus uses the count compare keeps in brief mode."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "release_gate"))

from core.deals import compare_gpu_prices, tier_class  # noqa: E402
from core.serverless import rate_reason  # noqa: E402
from t41_counts import ranked_after_min_gpus  # noqa: E402


def _toks(gpu: str) -> set[str]:
    return set("".join(c if c.isalnum() else " " for c in gpu.lower()).split())


def test_ranked_total_subtracts_the_min_gpus_count_not_the_list():
    """Brief mode keeps min_gpus_unmet and drops excluded_min_gpus. The count is what the gate subtracts."""
    assert ranked_after_min_gpus(19, {}) == 19
    assert ranked_after_min_gpus(19, {"min_gpus_unmet": 0}) == 19
    assert ranked_after_min_gpus(19, {"min_gpus_unmet": 2}) == 17
    # An empty or stale list must not override the count.
    assert ranked_after_min_gpus(19, {"min_gpus_unmet": 2, "excluded_min_gpus": []}) == 17
    assert ranked_after_min_gpus(19, {"excluded_min_gpus": [{"gpu": "H100"}]}) == 19


def test_live_h100_total_matches_ranked_rows_with_or_without_min_gpus_hold():
    feed = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    out = compare_gpu_prices(feed, "H100", limit=25, on_demand_only=False)
    listed = [r for r in feed["rates"] if "h100" in _toks(r.get("gpu") or "")]
    serverless = [r for r in listed if rate_reason(r)]
    reserved = [r for r in listed if tier_class(r) == "reserved"]
    before = [r for r in listed if r not in reserved and r not in serverless]
    n = out.get("min_gpus_unmet") or 0
    assert out["excluded_serverless"] == len(serverless)
    # #122: rows needing more GPUs are ranked after the rows that fit (counted, not excluded), so total keeps them.
    # #130 excludes them; there total == ranked_after_min_gpus(len(before), out).
    assert n == sum(1 for r in before if (r.get("min_gpus") or 1) > 1)
    assert out["total"] == len(before)
    assert out["count"] == min(25, out["total"])
