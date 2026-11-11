"""Shared T41-03 arithmetic. Brief compare output keeps min_gpus_unmet and drops excluded_min_gpus."""


def ranked_after_min_gpus(n_ranked: int, tool_out: dict) -> int:
    """Subtract compare's min_gpus_unmet count. Ignore excluded_min_gpus; brief mode does not return it."""
    n = (tool_out or {}).get("min_gpus_unmet") or 0
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        n = 0
    return n_ranked - n


def payg_eligible(rs: list, now) -> list:
    """T41-21: single-GPU pay-as-you-go rows for the eligible minimum: min_gpus <= 1, not reserved, not serverless,
    an hourly figure, and (T41-21 fix) inside the same default stale cut compare_gpu_prices / the page use
    (core.data_age.split_current, 168 h, evaluated at the gate's clock = the build clock or LW_AVAIL_NOW).
    Sorted out of stock last, then price, advertiser, gpu."""
    from core import data_age, deals as D
    from core.serverless import rate_reason

    def _n(r):
        n = r.get("min_gpus") or 1
        return 1 if isinstance(n, bool) or not isinstance(n, int) or n < 1 else n
    eligible = [r for r in rs if _n(r) <= 1 and D.tier_class(r) != "reserved" and not rate_reason(r) and r.get("hourly_equiv_usd") is not None]
    eligible = data_age.split_current(eligible, None, now)[0]
    eligible.sort(key=lambda r: (D.out_of_stock(r), r["hourly_equiv_usd"], r.get("advertiser") or "", r.get("gpu") or ""))
    return eligible
