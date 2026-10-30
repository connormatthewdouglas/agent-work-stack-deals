"""One shared USD formatter (Gauge F3): at least 2 decimals, never rounds away a significant digit (up to 6)."""
from __future__ import annotations


def usd(x, comma: bool = True, max_dp: int = 6) -> str:
    if x is None:
        return "n/a"
    x = float(x)
    for dp in range(2, max_dp + 1):
        if abs(round(x, dp) - x) < 1e-9:
            break
    return f"${x:,.{dp}f}" if comma else f"${x:.{dp}f}"


def usd_pair(a, b, max_dp: int = 6) -> tuple[str, str]:
    """Format two prices with enough decimals that they read differently whenever they differ."""
    sa, sb = usd(a), usd(b)
    dp = 2
    while sa == sb and a != b and dp < max_dp:
        dp += 1
        sa, sb = f"${float(a):,.{dp}f}", f"${float(b):,.{dp}f}"
    return sa, sb
