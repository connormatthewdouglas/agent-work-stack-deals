"""T63 (Gauge/Bjorn 1108): serverless and per-second prices are not dedicated instance rates. They are held: never
imported as an hourly rate (scripts/import_scout_wider.py) and never ranked by compare_gpu_prices in any pricing mode
(on-demand only, all tiers, reserved included). Held rows stay visible with a reason; nothing is hidden or invented."""
import re

# Text signals, whatever field carries them (tier, price_basis, billing_granularity, billing, notes, gpu_model, URL path...).
SERVERLESS_RE = re.compile(r"serverless|\bflex\b|active[-_ ]worker|per[-_ ]?sec(?:ond)?s?\b|/\s*sec(?:ond)?\b|scale[-_ ]to[-_ ]zero", re.I)
# Per-second price keys (price_usd_sec, price_per_second, usd_per_sec, ...).
PER_SECOND_KEY_RE = re.compile(r"(?:^|_)(?:per_?)?sec(?:ond)?s?$|_per_?sec(?:ond)?_|_sec_", re.I)
REASON = "serverless/per-second price: not a dedicated instance rate"


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


def per_second_keys(r: dict) -> list[str]:
    return [k for k, v in r.items() if v not in (None, "", 0) and PER_SECOND_KEY_RE.search(str(k))]


def row_reason(r: dict) -> str | None:
    """Import side (untrusted batch rows, field names vary): any per-second price key or any string value anywhere in
    the row that says serverless/flex/active-worker/per-second holds the row. Conservative by design."""
    keys = per_second_keys(r)
    if keys:
        return f"{REASON} (per-second field {keys[0]})"
    for txt in _strings(r):
        m = SERVERLESS_RE.search(txt)
        if m:
            return f"{REASON} ({m.group(0)!r} in row)"
    return None


# Published-rate side: structured fields only (evidence quotes of dedicated pods may say "billed per second").
RATE_FIELDS = ("tier", "billing_unit", "billing", "price_basis_label", "price_basis", "tier_class")


def rate_reason(r: dict) -> str | None:
    """Feed side (gpu-prices.json rates): per-second billing, a per-second price, or a serverless tier/label."""
    if r.get("price_per_second_usd") not in (None, "", 0):
        return f"{REASON} (price_per_second_usd)"
    for k in RATE_FIELDS:
        v = r.get(k)
        if isinstance(v, str):
            m = SERVERLESS_RE.search(v)
            if m:
                return f"{REASON} ({k}: {m.group(0)!r})"
    return None
