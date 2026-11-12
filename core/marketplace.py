"""P45 (hermesagentj): literal marketplace query next to median and n, and a composition flag
from successive median / minimum / listing count.

marketplace_query is null when the row is not a marketplace median or the query cannot be recovered.
composition_flag is taken only from successive med/min/n (not a host intersection; that waits on P44).
A composition, mixed, or unknown flag is never described as a price move. Missing previous min or n
is unknown, never invented. Stale prices stay flagged as stale elsewhere; this module does not hide them.
"""
from __future__ import annotations

import json
import urllib.parse

FLAGS = ("composition", "price", "mixed", "unknown")
# price = same listing count, median and min moved in the same direction (med/min/n only; not an intersection).
# composition = opposite median vs min, or only the basket/count changed.
# mixed = listing count changed and median and/or min also moved (cannot call it a price move).
# unknown = a median moved but the previous minimum or listing count was not recorded.
# null = not a marketplace median row, or nothing moved.

_EPS = 1e-9


def _num_eq(a, b) -> bool:
    if a is None and b is None:
        return True
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) < _EPS
    except (TypeError, ValueError):
        return False


def _sign(new, old):
    """-1, 0, or 1. None if either side is missing or not numeric."""
    try:
        n, o = float(new), float(old)
    except (TypeError, ValueError):
        return None
    if abs(n - o) < _EPS:
        return 0
    return 1 if n > o else -1


def is_marketplace_median(row: dict) -> bool:
    """Rows whose published hourly price is a host-listing median (price_status=marketplace).

    Daily snapshots before P45 have no price_status. Only the known published medians
    (Vast.ai / Clore.ai tiers that say they are a median) are treated as medians; Lium,
    Spheron, TensorDock, and any listed price are not.
    """
    row = row or {}
    ps = row.get("price_status")
    if ps == "marketplace":
        return True
    if ps:
        return False
    vendor = str(row.get("vendor") or row.get("advertiser") or "")
    tier = str(row.get("tier") or "").lower()
    if "median" not in tier:
        return False
    return vendor.startswith("Vast.ai") or vendor.startswith("Clore")


def _flatten_eq(v):
    if isinstance(v, dict) and "eq" in v and set(v) <= {"eq", "in"}:
        return v["eq"]
    return v


def marketplace_query(row: dict) -> dict | None:
    """Literal filter used for this marketplace median, plus structured filters. Null when unknown."""
    if not is_marketplace_median(row):
        return None
    url = str(row.get("source_url") or "")
    vendor = str(row.get("advertiser") or row.get("vendor") or "")
    basis = (row.get("price_basis") or "").strip() or None
    vram = row.get("vram_gb")
    gpu = row.get("gpu")

    if "vast.ai" in url.lower() or "console.vast.ai" in url.lower():
        filters: dict = {}
        raw = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", [None])[0]
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
        if isinstance(parsed, dict):
            for k in ("gpu_name", "rentable", "rented", "verified", "type", "limit"):
                if k in parsed:
                    filters[k] = _flatten_eq(parsed[k])
        if vram is not None:
            # The bundles URL does not include VRAM; refresh applies this after the API response.
            filters["vram_gb"] = vram
            filters["vram_filter"] = "applied_after_query"
        bits = []
        if "gpu_name" in filters:
            bits.append(f"gpu_name={filters['gpu_name']}")
        for k in ("rentable", "rented", "verified", "type"):
            if k in filters:
                bits.append(f"{k}={filters[k]}")
        if "vram_gb" in filters:
            bits.append(f"vram_gb={filters['vram_gb']} (applied after query)")
        if "limit" in filters:
            bits.append(f"limit={filters['limit']}")
        literal = "; ".join(bits) if bits else (url or basis)
        if not literal:
            return None
        out = {"literal": literal, "filters": filters or None, "url": url or None}
        return {k: v for k, v in out.items() if v is not None}

    if "clore.ai" in url.lower() or vendor.lower().startswith("clore"):
        filters = {
            "available": "rented == false",
            "currency": "USD",
            "price_field": "price.on_demand['USD-Blockchain']",
            "unit": "per-day whole-server / 24 / gpu_count",
            "excluded": ["spot", "bid"],
            "homogeneous_servers": True,
        }
        if gpu:
            filters["gpu"] = gpu
        if vram is not None:
            filters["vram_gb"] = vram
        # Always include the documented price field name; price_basis wording can omit it.
        literal = (
            "price.on_demand['USD-Blockchain'] per-day whole server / 24 / gpu_count; "
            "available = rented false; USD; spot/bid excluded; homogeneous servers only"
        )
        return {"literal": literal, "filters": filters, "url": url or "https://api.clore.ai/v1/marketplace"}

    # Other marketplace-median rows: only publish what the record already states. Never invent a filter.
    if not basis and not url:
        return None
    filters = {}
    if gpu:
        filters["gpu"] = gpu
    if vram is not None:
        filters["vram_gb"] = vram
    out = {"literal": basis or url, "filters": filters or None, "url": url or None}
    return {k: v for k, v in out.items() if v is not None}


def stats_from(row: dict | None) -> dict:
    """Median / min / n / verified_at as present on a snapshot or feed row. Missing keys stay missing."""
    row = row or {}
    med = row.get("hourly_usd")
    if med is None:
        med = row.get("hourly_equiv_usd")
    if med is None and row.get("price_status") == "marketplace":
        med = row.get("price_usd")
    out = {}
    if med is not None:
        out["median_usd"] = med
    if row.get("lowest_offer_usd") is not None:
        out["lowest_offer_usd"] = row["lowest_offer_usd"]
    if row.get("offer_count") is not None:
        out["offer_count"] = row["offer_count"]
    v = row.get("verified_at") or row.get("last_verified") or row.get("checked_at")
    if v:
        out["verified_at"] = v
    return out


def classify(previous: dict | None, current: dict | None) -> str | None:
    """composition_flag from two {median_usd, lowest_offer_usd, offer_count} readings. Null if nothing moved
    or the current row is not classifiable. Never returns 'price' when the listing count changed, or when
    median and min moved in opposite directions."""
    prev, cur = previous or {}, current or {}
    if "median_usd" not in cur:
        return None
    if "median_usd" not in prev:
        return "unknown"  # a current median exists but there is no previous median to compare
    med_dir = _sign(cur["median_usd"], prev["median_usd"])
    have_min = "lowest_offer_usd" in prev and "lowest_offer_usd" in cur
    have_n = "offer_count" in prev and "offer_count" in cur
    min_dir = _sign(cur.get("lowest_offer_usd"), prev.get("lowest_offer_usd")) if have_min else None
    n_changed = (cur["offer_count"] != prev["offer_count"]) if have_n else None

    nothing = (med_dir == 0) and (min_dir in (0, None)) and (n_changed in (False, None))
    if nothing:
        return None

    # A median (or min) moved but we lack the previous min or n needed to classify honestly.
    if (med_dir not in (0, None) or (have_min and min_dir not in (0, None))) and (not have_min or not have_n):
        return "unknown"

    # n changed + median and/or min also moved => mixed (never a price move).
    # n changed + only the basket/count changed => composition.
    # opposite med vs min at the same n, or same n but they do not both move the same way => composition.
    if n_changed is True:
        if med_dir == 0 and (min_dir in (0, None)):
            return "composition"
        return "mixed"
    if med_dir not in (0, None) and min_dir == med_dir:
        return "price"
    if med_dir not in (0, None) or min_dir not in (0, None):
        # same n, but only one of median/min moved, or they moved in opposite directions.
        return "composition"
    return "unknown"


def composition_fields(previous: dict | None, current: dict | None) -> dict:
    """Flag plus the two readings used to classify it (staleness of the previous reading stays visible)."""
    flag = classify(previous, current)
    out = {"composition_flag": flag}
    if previous:
        out["composition_previous"] = previous
    return out


def is_price_move(flag: str | None) -> bool:
    """Only a 'price' flag may be described as a price move."""
    return flag == "price"


def snapshot_extras(record: dict) -> dict:
    """lowest_offer_usd and offer_count for daily snapshots, only when the record already has them."""
    if not is_marketplace_median(record):
        return {}
    out = {}
    if record.get("price_status"):
        out["price_status"] = record["price_status"]
    if record.get("lowest_offer_usd") is not None:
        out["lowest_offer_usd"] = record["lowest_offer_usd"]
    if record.get("offer_count") is not None:
        out["offer_count"] = record["offer_count"]
    return out


def _same_obs(row: dict, current: dict) -> bool:
    """True when the snapshot row is the same observation as the live rate (don't compare a row to itself)."""
    cur, prev = stats_from(current), stats_from(row)
    cv, pv = cur.get("verified_at"), prev.get("verified_at")
    if cv and pv and str(cv).replace("Z", "+00:00") == str(pv).replace("Z", "+00:00"):
        return True
    return (
        _num_eq(cur.get("median_usd"), prev.get("median_usd"))
        and _num_eq(cur.get("lowest_offer_usd"), prev.get("lowest_offer_usd"))
        and cur.get("offer_count") == prev.get("offer_count")
        and (not cv or not pv)
    )


def previous_snapshot_row(snapshots: list[dict], key: str, current: dict) -> dict | None:
    """Most recent snapshot row for this series that is not the current observation. Never invented."""
    if not key:
        return None
    for snap in sorted(snapshots or [], key=lambda s: s.get("date") or "", reverse=True):
        for row in snap.get("rows") or []:
            if row.get("key") != key:
                continue
            if _same_obs(row, current):
                continue
            return row
    return None


def annotate(rates: list[dict], snapshots: list[dict] | None = None) -> None:
    """Attach marketplace_query and composition_flag to marketplace median rates (in place, additive)."""
    from .gpu_history import series_key

    snaps = snapshots or []
    for r in rates:
        if not is_marketplace_median(r):
            continue
        q = marketplace_query(r)
        r["marketplace_query"] = q
        vendor = r.get("advertiser") or r.get("vendor")
        key = series_key(vendor, r.get("gpu"), r.get("tier"), r.get("vram_gb"), r.get("gpu_count") or 1)
        prev = previous_snapshot_row(snaps, key, r)
        fields = composition_fields(stats_from(prev) if prev else None, stats_from(r))
        r["composition_flag"] = fields["composition_flag"]
        if fields.get("composition_previous"):
            r["composition_previous"] = fields["composition_previous"]
