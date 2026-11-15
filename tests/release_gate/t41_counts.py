"""Shared T41-03 arithmetic. Brief compare output keeps min_gpus_unmet and drops excluded_min_gpus."""

# T41-21 and the price-comparison per-model "lowest" cell share core.deals.payg_eligible
# (168 h stale cut, no lead_key). Do not compute a second copy here.
from core.deals import payg_eligible  # noqa: E402

def ranked_after_min_gpus(n_ranked: int, tool_out: dict) -> int:
    """Subtract compare's min_gpus_unmet count. Ignore excluded_min_gpus; brief mode does not return it."""
    n = (tool_out or {}).get("min_gpus_unmet") or 0
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        n = 0
    return n_ranked - n


