"""P8: daily aggregate demand counts from hosted GPU tool calls (no caller IDs, no raw arguments, no free text).

One counter per UTC day x tool x gpu_family x region_group x price_tier x cheapest_provider. Every dimension is a
fixed vocabulary or comes from our own published feed, never from the caller:
  - gpu_family: the requested GPU bucketed to GPU_FAMILIES, anything else 'other' (none given: 'any')
  - region_group: the requested region bucketed to REGION_GROUPS, anything else 'other' (none given: 'any')
  - price_tier / cheapest_provider: tier_class and provider of the first-ranked result in OUR answer ('none' if no result)
House traffic (src_class house or a house ref, same rule as callers.py) and known bots are not counted. Never raises.
"""
import re
from datetime import datetime, timedelta, timezone

RETENTION_DAYS = 120  # same as hits and callers
TOOLS = ("compare_gpu_prices", "estimate_job_cost", "optimize_agent_stack")
GPU_ARG = {"compare_gpu_prices": ("gpu",), "estimate_job_cost": ("gpu_family", "gpu"), "optimize_agent_stack": ("gpu_model",)}

# (family label, normalized aliases). Longest/most specific first so A100 is not read as A10, L40S not as L40/L4.
GPU_FAMILIES = (
    ("GB300", ("GB300",)), ("GB200", ("GB200",)), ("GH200", ("GH200",)),
    ("B300", ("B300",)), ("B200", ("B200",)), ("H200", ("H200",)), ("H100", ("H100",)), ("H20", ("H20",)),
    ("A100", ("A100",)), ("A40", ("A40",)), ("A10", ("A10G", "A10")),
    ("L40S", ("L40S",)), ("L40", ("L40",)), ("L4", ("L4",)),
    ("RTX PRO 6000", ("RTXPRO6000", "PRO6000")), ("RTX PRO 5000", ("RTXPRO5000", "PRO5000")), ("RTX PRO 4500", ("RTXPRO4500", "PRO4500")),
    ("RTX PRO 4000", ("RTXPRO4000", "PRO4000")),
    ("RTX 6000 Ada", ("RTX6000ADA", "6000ADA")), ("RTX A6000", ("RTXA6000", "A6000")), ("RTX A5000", ("RTXA5000", "A5000")),
    ("RTX A4000", ("RTXA4000", "A4000")),
    ("RTX 5090", ("RTX5090", "5090")), ("RTX 4090", ("RTX4090", "4090")), ("RTX 3090", ("RTX3090", "3090")),
    ("V100", ("V100",)), ("T4", ("T4",)),
    ("MI355X", ("MI355X",)), ("MI325X", ("MI325X",)), ("MI300X", ("MI300X",)), ("MI250", ("MI250X", "MI250")),
)
# Suffixes allowed after a family alias (form factor / memory). Anything else makes the input 'other'.
_SUFFIX_RE = re.compile(r"^(SXM\d?|PCIE|NVL|NVLINK|HGX|DGX|\d{2,3}GB|GB|ADA|SUPER|TI|X)*$")
REGION_GROUPS = {
    "north-america": ("US", "CA", "NA", "NORTHAMERICA", "USA", "MX"),
    "europe": ("EU", "EUROPE", "UK", "GB", "DE", "FR", "NL", "FI", "SE", "NO", "IS", "PL", "ES", "IT", "IE", "CH", "AT", "BE", "DK", "PT", "CZ"),
    "asia-pacific": ("APAC", "ASIA", "AP", "JP", "SG", "KR", "IN", "HK", "TW", "AU", "NZ", "CN", "ID", "MY", "TH", "VN", "PH"),
    "south-america": ("SA", "LATAM", "BR", "AR", "CL", "CO", "PE"),
    "middle-east-africa": ("ME", "MEA", "AF", "AE", "IL", "ZA", "SAU", "QA"),
}
PRICE_TIERS = ("on-demand", "interruptible", "community", "marketplace", "reserved", "dedicated-monthly")
HOUSE_REF_RE = re.compile(r"^(ci|qa|test|smoke|house-[a-z0-9_-]*|t\d+(-[a-z0-9_-]*)?)$")  # same as callers.py
_REGION_CODE_RE = re.compile(r"^[A-Z]{2,12}([-_][A-Z0-9]{1,12}){0,3}$")
_PROVIDER_RE = re.compile(r"^[^\x00-\x1f]{1,60}$")


def today():
    return datetime.now(timezone.utc).date().isoformat()


def excluded(ref, ua_class, src_class):
    return src_class == "house" or ua_class in ("house", "ci", "known-bot") or bool(HOUSE_REF_RE.match(ref or ""))


def gpu_family(raw):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "any"
    if not isinstance(raw, str):
        return "other"
    n = re.sub(r"[^A-Z0-9]", "", raw.upper()[:40])
    n = re.sub(r"^(NVIDIA|AMD|INSTINCT|GEFORCE|TESLA)+", "", n)
    for label, aliases in GPU_FAMILIES:
        for a in aliases:
            if n.startswith(a) and _SUFFIX_RE.match(n[len(a):]):
                return label
    return "other"


def region_group(raw):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "any"
    if not isinstance(raw, str):
        return "other"
    code = raw.strip().upper()[:40]
    if not _REGION_CODE_RE.match(code):  # only code-shaped input (US, eu-west-2, US-NE-1); free text is 'other'
        return "other"
    head = re.split(r"[-_]", code, maxsplit=1)[0]
    head = {"NORTH": "NORTHAMERICA"}.get(head, head)
    for g, codes in REGION_GROUPS.items():
        if head in codes:
            return g
    return "other"


def _first_row(out):
    if not isinstance(out, dict) or out.get("ok") is False:
        return None
    rows = out.get("results")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    for line in out.get("lines") or []:  # optimize_agent_stack: the gpu line's choice
        if isinstance(line, dict) and line.get("component") == "gpu" and isinstance(line.get("choice"), dict):
            return line["choice"]
    return None


def price_tier(row):
    if row is None:
        return "none"
    t = str(row.get("tier_class") or "").lower()
    if t in PRICE_TIERS:
        return t
    txt = str(row.get("tier") or "").lower()
    for k in ("on-demand", "interruptible", "community", "marketplace", "reserved"):
        if k in txt or k.replace("-", " ") in txt:
            return k
    return "unknown" if not t and not txt else "other"


def cheapest_provider(row):
    if row is None:
        return "none"
    p = row.get("advertiser") or row.get("vendor")
    return p if isinstance(p, str) and _PROVIDER_RE.match(p) else "other"


def dims(tool, args, out):
    """The only values that are stored for one call. Never the raw arguments."""
    args = args if isinstance(args, dict) else {}
    raw = next((args.get(k) for k in GPU_ARG.get(tool, ()) if args.get(k) is not None), None)
    row = _first_row(out)
    return (tool, gpu_family(raw), region_group(args.get("region")), price_tier(row), cheapest_provider(row))


async def record(db, tool, args, out, ref, ua_class, src_class, day=None):
    if tool not in TOOLS or excluded(ref, ua_class, src_class):
        return
    try:
        await db.prepare("INSERT INTO demand(day, tool, gpu_family, region_group, price_tier, cheapest_provider, n) "
                         "VALUES (?, ?, ?, ?, ?, ?, 1) ON CONFLICT(day, tool, gpu_family, region_group, price_tier, cheapest_provider) "
                         "DO UPDATE SET n = n + 1").bind(day or today(), *dims(tool, args, out)).run()
    except Exception:
        pass  # counting never breaks a call (also before the migration is applied)


def _get(r, k):
    return r[k] if isinstance(r, dict) else getattr(r, k)


async def stats(db, day=None):
    """Daily aggregate rows; empty before the migration is applied."""
    out = {"demand_daily": []}
    try:
        cut = (datetime.fromisoformat(day or today()).date() - timedelta(days=RETENTION_DAYS)).isoformat()
        await db.prepare("DELETE FROM demand WHERE day < ?").bind(cut).run()
        rows = (await db.prepare("SELECT day, tool, gpu_family, region_group, price_tier, cheapest_provider, n FROM demand "
                                 "ORDER BY day DESC, n DESC LIMIT 5000").all()).results
        out["demand_daily"] = [{k: _get(r, k) for k in ("day", "tool", "gpu_family", "region_group", "price_tier", "cheapest_provider", "n")}
                               for r in rows]
    except Exception:
        pass
    return out
