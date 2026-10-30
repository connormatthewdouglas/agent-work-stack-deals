"""T47: one eligibility contract for every decision surface (compare, estimate, watch, alert matching, calculator).

A constraint set is checked against one rate and returns, per constraint, met / unmet / unknown:
  gpu            all query tokens are tokens of the model name; a size in the query ('A100 80GB') pins vram_gb
  vram_gb        exact memory size (an A100 40GB is not an A100 80GB); a row without vram_gb is unknown
  tiers          allowed tier classes (on-demand | community | marketplace | interruptible | reserved | dedicated-monthly);
                 'spot' is an alias of interruptible
  region         a code from availability.available_regions; a row with no unexpired region evidence is UNKNOWN
                 (unresolved), never a match
  in_stock       'exclude_sold_out' (default): a row confirmed out of stock (in_stock false, unexpired) is unmet;
                 unknown stock is reported as unknown and does not block (unknown != available, != sold out).
                 'require': only a confirmed, unexpired in-stock claim passes.
  max_price_age_hours / max_availability_age_hours   older or undated evidence is unmet / unknown

eligible = no unmet constraint and no unknown HARD constraint (vram_gb, region, price age). Stock unknown is soft
unless in_stock='require'. Broad informational lists may still show ineligible rows, labelled with this result.
The same function runs locally, in the hosted Worker and in alert matching; the browser calculator mirrors it.
"""
from __future__ import annotations

import re
from datetime import datetime

TIER_CLASSES = ("on-demand", "community", "marketplace", "interruptible", "reserved", "dedicated-monthly")
TIER_ALIASES = {"spot": "interruptible", "preemptible": "interruptible", "ondemand": "on-demand", "on_demand": "on-demand"}
STOCK_MODES = ("exclude_sold_out", "require", "ignore")
HARD = ("gpu", "vram_gb", "tiers", "region", "max_price_age_hours")


class EligibilityError(ValueError):
    pass


def _tokens(s):
    return [t for t in "".join(c if c.isalnum() else " " for c in (s or "").lower()).split() if t]


def normalize(gpu=None, vram_gb=None, tiers=None, region=None, in_stock="exclude_sold_out",
              max_price_age_hours=None, max_availability_age_hours=None) -> dict:
    c = {}
    if gpu is not None:
        g = str(gpu).strip()
        m = re.search(r"\b(\d{2,3})\s*gb\b", g, re.I)
        toks = _tokens(re.sub(r"\b\d{2,3}\s*gb\b", " ", g, flags=re.I))
        if not toks:
            raise EligibilityError("gpu is required, e.g. 'H100', 'A100 80GB'")
        c["gpu"] = toks
        if m:
            if vram_gb is not None and int(vram_gb) != int(m.group(1)):
                raise EligibilityError(f"gpu says {m.group(1)}GB but vram_gb is {vram_gb}")
            vram_gb = int(m.group(1))
    if vram_gb is not None:
        if isinstance(vram_gb, bool) or not isinstance(vram_gb, (int, float)) or not 1 <= vram_gb <= 1024 or int(vram_gb) != vram_gb:
            raise EligibilityError("vram_gb must be an integer 1-1024 (GB per GPU)")
        c["vram_gb"] = int(vram_gb)
    if tiers:
        if isinstance(tiers, str):
            tiers = [t.strip() for t in tiers.split(",") if t.strip()]
        out = []
        for t in tiers:
            t2 = TIER_ALIASES.get(str(t).strip().lower(), str(t).strip().lower())
            if t2 not in TIER_CLASSES:
                raise EligibilityError(f"tier must be among {', '.join(TIER_CLASSES)} (or 'spot')")
            out.append(t2)
        c["tiers"] = sorted(set(out))
    if region:
        r = str(region).strip().upper()
        if not re.fullmatch(r"[A-Z0-9-]{2,12}", r):
            raise EligibilityError("region is a code as published in availability.available_regions, e.g. 'US'")
        c["region"] = r
    if in_stock not in STOCK_MODES:
        raise EligibilityError(f"in_stock must be one of {', '.join(STOCK_MODES)}")
    c["in_stock"] = in_stock
    for k, v in (("max_price_age_hours", max_price_age_hours), ("max_availability_age_hours", max_availability_age_hours)):
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                raise EligibilityError(f"{k} must be a number > 0")
            c[k] = float(v)
    return c


def facts(rate: dict, now: datetime | None = None) -> dict:
    """The few fields eligibility needs, after the request-time stale/region guards. Also what alert pushes carry."""
    from .deals import tier_class
    from .gpu_availability import stale_guard, age_hours
    from . import data_age
    a = rate.get("availability")
    a = stale_guard(a, now) if isinstance(a, dict) else {}
    a = a or {}
    regs = sorted({str(x).upper() for x in (a.get("available_regions") or [])})
    return {"gpu": rate.get("gpu"), "vram_gb": rate.get("vram_gb"), "tier_class": tier_class(rate),
            "in_stock": a.get("in_stock") if a.get("in_stock") in (True, False) else None,
            "availability_age_hours": age_hours(a.get("checked_at"), now) if a.get("checked_at") else None,
            "regions": regs or None, "price_age_hours": data_age.age_fields(rate, now)["data_age_hours"]}


def check(f: dict, c: dict) -> dict:
    """f = facts(rate). Returns {eligible, applied, unmet:[{constraint, reason}], unknown:[{constraint, reason}]}."""
    applied, unmet, unknown = [], [], []

    def bad(k, why):
        unmet.append({"constraint": k, "reason": why})

    def unk(k, why):
        unknown.append({"constraint": k, "reason": why})
    if "gpu" in c:
        applied.append("gpu")
        if not set(c["gpu"]) <= set(_tokens(f.get("gpu"))):
            bad("gpu", f"model {f.get('gpu')!r} does not match")
    if "vram_gb" in c:
        applied.append("vram_gb")
        if f.get("vram_gb") is None:
            unk("vram_gb", "memory size not published")
        elif f["vram_gb"] != c["vram_gb"]:
            bad("vram_gb", f"{f['vram_gb']}GB, not {c['vram_gb']}GB")
    if "tiers" in c:
        applied.append("tiers")
        if f.get("tier_class") not in c["tiers"]:
            bad("tiers", f"tier class {f.get('tier_class')}, not {'/'.join(c['tiers'])}")
    if "region" in c:
        applied.append("region")
        if not f.get("regions"):
            unk("region", f"no unexpired region evidence; {c['region']} unresolved")
        elif c["region"] not in f["regions"]:
            bad("region", f"{c['region']} not among published regions {', '.join(f['regions'])}")
    if "max_price_age_hours" in c:
        applied.append("max_price_age_hours")
        h = f.get("price_age_hours")
        if h is None:
            unk("max_price_age_hours", "price check time unknown")
        elif h > c["max_price_age_hours"]:
            bad("max_price_age_hours", f"price verified {h:.1f} h ago")
    mode = c.get("in_stock", "exclude_sold_out")
    stock = f.get("in_stock")
    if "max_availability_age_hours" in c:
        applied.append("max_availability_age_hours")
        ah = f.get("availability_age_hours")
        if stock is not None and (ah is None or ah > c["max_availability_age_hours"]):
            unk("max_availability_age_hours", "stock check older than the limit; treated as unknown")
            stock = None
    if mode != "ignore":
        applied.append("in_stock")
        if stock is False:
            bad("in_stock", "out of stock when checked")
        elif stock is None:
            unk("in_stock", "stock unknown (not confirmed available, not sold out)")
    hard_unknown = [u for u in unknown if u["constraint"] in HARD or (u["constraint"] == "in_stock" and mode == "require")]
    return {"eligible": not unmet and not hard_unknown, "applied": applied, "unmet": unmet, "unknown": unknown}


def evaluate(rate: dict, c: dict, now: datetime | None = None) -> dict:
    return check(facts(rate, now), c)


def eligible_ids(prices_doc: dict, c: dict, now: datetime | None = None, max_hourly_usd: float | None = None) -> list[str]:
    """Sorted rate_ids passing c (and an optional price cap): the cross-surface parity set."""
    from .ids import rate_id
    out = []
    for r in (prices_doc or {}).get("rates") or []:
        h = r.get("hourly_equiv_usd")
        if not isinstance(h, (int, float)) or (max_hourly_usd is not None and h > max_hourly_usd):
            continue
        if evaluate(r, c, now)["eligible"]:
            out.append(rate_id(r))
    return sorted(out)
