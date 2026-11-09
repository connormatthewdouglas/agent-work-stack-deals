"""T63 (Gauge/Bjorn 1108): serverless and per-second prices are not dedicated instance rates. They are held: never
imported as an hourly rate (scripts/import_scout_wider.py) and never ranked by compare_gpu_prices in any pricing mode
(on-demand only, all tiers, reserved included). Held rows stay visible with a reason; nothing is hidden or invented."""
import re

# Serverless / per-second text signals (feed side checks these in structured fields only, see RATE_FIELDS).
SERVERLESS_RE = re.compile(r"serverless|\bflex\b|active[-_ ]worker|per[-_ ]?sec(?:ond)?s?\b|/\s*sec(?:ond)?\b|scale[-_ ]to[-_ ]zero", re.I)
# Import side, any field: serverless product words only. "per second" text is NOT a hold signal anywhere in a row,
# because dedicated pods are billed per second too (quotes like "$0.42 /hr $0.00012 /sec", billing_granularity).
SERVERLESS_WORD_RE = re.compile(r"serverless|\bflex\b|active[-_ ]worker|scale[-_ ]to[-_ ]zero", re.I)
# Per-second PRICE keys only (Gauge 1108 #102 a): a price/usd/cost/rate key priced per second, e.g. price_usd_sec,
# price_per_second, usd_per_sec, cost_per_second. Non-price keys (two_read_gap_seconds, min_billing_seconds) never match.
PER_SECOND_KEY_RE = re.compile(r"^(?=.*(?:price|usd|cost|rate))(?:.*_)?(?:per_?)?sec(?:ond)?s?(?:_|$)", re.I)
# The billing unit itself (not text about billing granularity) saying per-second.
PER_SECOND_UNIT_RE = re.compile(r"^\s*(?:per[-_ ]?)?sec(?:ond)?s?\s*$", re.I)
UNIT_FIELDS = ("billing_unit", "billing", "unit", "price_unit")
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
    """Import side (untrusted batch rows, field names vary): a per-second PRICE key, a per-second billing unit, or a
    serverless/flex/active-worker/scale-to-zero word in any string value holds the row."""
    keys = per_second_keys(r)
    if keys:
        return f"{REASON} (per-second price field {keys[0]})"
    for k in UNIT_FIELDS:
        if isinstance(r.get(k), str) and PER_SECOND_UNIT_RE.match(r[k]):
            return f"{REASON} ({k}: {r[k]!r})"
    for txt in _strings(r):
        m = SERVERLESS_WORD_RE.search(txt)
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
