"""Shared T41-03 arithmetic. Brief compare output keeps min_gpus_unmet and drops excluded_min_gpus."""


def ranked_after_min_gpus(n_ranked: int, tool_out: dict) -> int:
    """Subtract compare's min_gpus_unmet count. Ignore excluded_min_gpus; brief mode does not return it."""
    n = (tool_out or {}).get("min_gpus_unmet") or 0
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        n = 0
    return n_ranked - n
