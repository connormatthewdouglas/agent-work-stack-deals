"""Availability attached to GPU rates (T11/T19), from data/gpu_availability/latest.json (Lantern Scout v2).

Display rules: unknown -> "unknown" (never "out of stock"); availability carries its own checked_at and cadence
(a manual Scout snapshot, time shown per row) separate from the daily price check; stock is never a guarantee."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "gpu_availability" / "latest.json"
NOTE = STOCK_EXPLAINER = ("Where a status is shown, it is a snapshot from the time in the row, not a guarantee. Statuses from a vendor's live stock check can change within minutes; \u201cvendor-labelled\u201d means a fixed label on the vendor's page, not a capacity check; \u201c\u2014\u201d or \u201cunknown\u201d means no signal, not sold out.")
UNKNOWN_NOTE = "No availability signal from this vendor for this offer; unknown, not sold out."
VAST_NOTE = ("Vast.ai: the offer count is from a separate availability check (its own checked_at), not the "
             "price snapshot; offer counts and prices on the marketplace move between checks, so they can differ "
             "from the count/minimum in the price quote.")
STATIC_LABEL_STATUS = "vendor-labelled in stock (static page label, not a capacity check)"
STATIC_LABEL_NOTE = ("The vendor's own page labels this offer in stock; that label is static page markup, not a live "
                     "capacity check, so it is treated as unknown availability.")
_CACHE: dict | None = None


def _index() -> dict:
    global _CACHE
    if _CACHE is None:
        rows = json.loads(PATH.read_text(encoding="utf-8"))["rows"] if PATH.exists() else []
        _CACHE = {(r["vendor"], r["gpu"], r.get("vram_gb"), r["tier"]): r for r in rows}
    return _CACHE


def _tier_key(tier: str) -> str:
    return tier.replace("Marketplace on-demand (verified; median per GPU)", "Marketplace on-demand (verified; median per GPU)")


def _clean(note):
    """Scout's availability_note, minus its 'null = ' prefix (shown as unknown)."""
    if not note:
        return None
    note = str(note).strip()
    for pre in ("null = ", "unknown: "):
        if note.lower().startswith(pre):
            note = note[len(pre):].strip()
    return note[:1].upper() + note[1:]


AUTH_SOURCES = ("api.datacrunch.io", "cloud.lambda.ai")  # Verda, Lambda: need an API key, so others can't re-run the check
AUTH_LABEL = "authenticated vendor API (not publicly reproducible)"
UNRENTED_NOTE = "unrented servers (one server may hold several GPUs)"


def _from_record(a: dict) -> dict:
    """Record-level availability (data/gpu_pricing/<vendor>.json "availability"), used only when Scout has no row.
    Carries its own checked_at and source; in_stock null stays "unknown", never "out of stock"."""
    if a.get("basis") == "vendor_static_label":
        # I2: a static "in stock" label on the vendor's own page is not a capacity check: in_stock stays null
        return {"status": STATIC_LABEL_STATUS, "in_stock": None, "basis": "vendor_static_label",
                "checked_at": a.get("checked_at"), "source": a.get("source"), "note": STATIC_LABEL_NOTE}
    reads = {k: a[k] for k in ("first_read_at", "second_read_at", "second_read_gap_s") if k in a}
    if reads:  # Clore snapshot two-read provenance (Gauge clore-1109 N1): both read times travel with the claim
        g = a.get("second_read_gap_s")
        reads["two_read_gap_ok"] = g is not None and g >= TWO_READ_MIN_S
    if a.get("in_stock") is None:
        return {"status": "unknown", "in_stock": None, "checked_at": a.get("checked_at"),
                "source": a.get("source"), "note": _clean(a.get("note")) or UNKNOWN_NOTE, **reads}
    out = {"status": "available when checked" if a["in_stock"] else "out of stock when checked",
           "in_stock": bool(a["in_stock"]), "checked_at": a.get("checked_at"),
           "refresh": REFRESH_AUTOMATED, "source": a.get("source"), "note": NOTE,
           "origin": "record", "max_age_hours": AVAIL_MAX_AGE_H, "availability_expires_at": expires_at(a.get("checked_at"))}
    if a.get("stock_level"):
        out["stock_level"] = str(a["stock_level"])
    if a.get("same_capture_as_price"):
        out["same_capture_as_price"] = True  # J6: price quote and stock count read from one page capture
    if a.get("note"):
        out["detail"] = _clean(a["note"])
    out.update(reads)
    return out


AVAIL_MAX_AGE_H = 8  # same limit as Scout's enrich_feed_v2 (2x its 4h cadence)
STALE_NOTE = ("This availability check is past its availability_expires_at, or expires before the next rebuild, so it "
              "is shown as unknown (not in stock, not sold out) until a newer check is imported. Claim lifetimes: 15 min "
              "for Verda spot; 1 h for Lambda, Verda, RunPod/Oblivus overall, region and region-derived claims; "
              f"{AVAIL_MAX_AGE_H} h for marketplace overall claims.")


def _et_zone():
    """America/New_York; falls back to UTC where no tz database is installed (e.g. Windows without tzdata)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York"), "ET"
    except Exception:
        return timezone.utc, "UTC"


def now_utc() -> datetime:
    """Current time; LW_AVAIL_NOW (ISO) pins it for tests and the T41 stale fixture."""
    v = os.environ.get("LW_AVAIL_NOW")
    return _parse(v) if v else datetime.now(timezone.utc)


def _parse(ts) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def et_time(ts) -> str:
    d = _parse(ts)
    if not d:
        return "n/a"
    z, label = _et_zone()
    return d.astimezone(z).strftime("%Y-%m-%d %H:%M ") + label


def age_hours(ts, now: datetime | None = None) -> float | None:
    d = _parse(ts)
    return None if d is None else ((now or now_utc()) - d).total_seconds() / 3600


def expires_at(checked_at) -> str | None:
    """availability_expires_at: checked_at + AVAIL_MAX_AGE_H (UTC, Z). After it, treat the stock claim as unknown."""
    from datetime import timedelta
    d = _parse(checked_at)
    return (d + timedelta(hours=AVAIL_MAX_AGE_H)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if d else None


def et_hm(ts) -> str:
    """HH:MM ET (or UTC without a tz database)."""
    t = et_time(ts)
    return t[11:] if t != "n/a" else t


REGIONS_NOTE = "Region lists refresh with each Scout cycle and may be blank between cycles."


def claim_hours(checked_at, expires) -> float:
    """Gauge F4: a claim's real lifetime in hours (availability_expires_at - checked_at), e.g. 0.25 for a Verda spot claim."""
    c, x = _parse(checked_at), _parse(expires)
    if not c or not x:
        return AVAIL_MAX_AGE_H
    return round(max(0.0, (x - c).total_seconds() / 3600), 2)


REFRESH_AUTOMATED = "automated check, time shown (prices checked daily)"
REFRESH_MANUAL = "manual snapshot, time shown (prices checked daily)"


def regions_expires_at(r: dict | None) -> str | None:
    """Scout v2.9: each region in available_regions_detail carries its own availability_expires_at (1 h). The region
    list as a whole is valid until the earliest of them (separate from the row's 8 h stock-claim expiry)."""
    ts = [d.get("availability_expires_at") for d in ((r or {}).get("available_regions_detail") or []) if isinstance(d, dict)]
    ts = [t for t in ts if _parse(t)]
    return min(ts, key=_parse) if ts else None


def region_guard(a, now: datetime | None = None):
    """Blank available_regions (and the per-region detail) once the earliest region expiry has passed."""
    if not isinstance(a, dict) or not a.get("regions_expires_at") or a.get("regions_expired"):
        return a
    x = _parse(a["regions_expires_at"])
    if x is None or (now or now_utc()) <= x:
        return a
    out = dict(a)
    out["available_regions"] = None
    out["available_regions_detail"] = None
    if "available_regions_normalized" in out:
        out["available_regions_normalized"] = None
    out["regions_expired"] = True
    out["regions_note"] = f"region list expires at {et_hm(a['regions_expires_at'])} (left out once expired or expiring before the next rebuild). " + REGIONS_NOTE
    return out


CLAIM_AUDIT_KEYS = ("stock_read_at", "price_read_at", "price_at_claim_usd", "gpu_count", "price_join_failed",
                    "first_read_at", "second_read_at", "second_read_gap_s", "second_read_basis", "two_read_gap_ok")


LAST_KNOWN_KEYS = ("last_known_in_stock", "last_known_at")


def last_known(src: dict) -> tuple[bool | None, str | None]:
    """P36: the most recent firm stock answer (in_stock true/false) and its checked_at. A current firm claim is its own last
    known value; an unknown or lapsed claim keeps whatever an earlier pass recorded. Never invented: both null when no firm
    claim with a check time was ever seen. Display only; ranking reads in_stock, never these."""
    if isinstance(src.get("in_stock"), bool) and src.get("checked_at"):
        return src["in_stock"], src["checked_at"]
    v, t = src.get("last_known_in_stock"), src.get("last_known_at")
    return (v, t) if isinstance(v, bool) and isinstance(t, str) and t else (None, None)


def stale_guard(a, now: datetime | None = None):
    """_stale_guard plus P36: when a claim lapses here, the stale result also carries last_known_in_stock / last_known_at,
    taken from the claim BEFORE it lapsed. Current claims are returned unchanged (their in_stock is the firm value)."""
    out = _stale_guard(a, now)
    if not isinstance(a, dict) or not isinstance(out, dict) or out is a or not out.get("availability_stale") \
            or a.get("availability_stale"):
        return out  # current claims and already-lapsed ones pass through unchanged (same object, same fields)
    v, t = last_known(a)  # lapsing now: keep the answer it gave before it lapsed (null when it never gave one)
    return {**out, "last_known_in_stock": v, "last_known_at": t}


def _stale_guard(a, now: datetime | None = None):
    """Scout (or record-level, J6) availability older than AVAIL_MAX_AGE_H renders unknown (in_stock null, availability_stale true).
    Applied when the feed is built and again when the MCP tool reads it, so a stale stock claim never ranks or leads."""
    if not isinstance(a, dict) or a.get("origin") not in ("scout", "record") or a.get("availability_stale"):
        return a
    h = age_hours(a.get("checked_at"), now)
    x = _parse(a.get("availability_expires_at"))  # v3.2: Scout may set a shorter claim lifetime than 8 h
    rx = _parse(a.get("regions_expires_at"))
    if a.get("derived_from_regions") and a.get("in_stock") is not None and rx and (not x or rx < x):
        x = rx  # N1: an overall claim derived from regions ends when its regions expire
    if h is not None and h <= AVAIL_MAX_AGE_H and not (x and (now or now_utc()) > x):
        return region_guard(a, now)
    if h is None and not x:
        return region_guard(a, now)
    out = {"status": f"unknown (stale availability, last checked {et_time(a.get('checked_at'))})", "in_stock": None,
           "availability_stale": True, "checked_at": a.get("checked_at"),
           "max_age_hours": claim_hours(a.get("checked_at"), a.get("availability_expires_at")),
           "origin": a["origin"], "note": STALE_NOTE}
    if a.get("derived_from_regions"):
        out["derived_from_regions"] = True
    for k in ("source", "source_label", "availability_expires_at", "feed_status"):
        if a.get(k):
            out[k] = a[k]
    for k in CLAIM_AUDIT_KEYS:  # Gauge T73 F1-F6 #3: an expired claim keeps its audit fields (additive)
        if k in a:
            out[k] = a[k]
    return out


REGION_TTL_H = 1  # Scout region lists last 1 h
SHORT_CLAIM_VENDORS = ("Lambda", "Verda")  # re20 P3: vendor-API overall claims last no longer than a region list


def _plus_h(ts, h) -> str | None:
    from datetime import timedelta
    d = _parse(ts)
    return (d + timedelta(hours=h)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if d else None


def _min_expiry(r: dict, vendor: str = "") -> str | None:
    """The earliest of checked_at + 8 h, Scout's own availability_expires_at (v3.2 shortens some claims) and, for
    Lambda/Verda vendor-API claims and region-derived claims, checked_at + 1 h (re20 P3)."""
    c = r.get("availability_checked_at")
    short = _plus_h(c, REGION_TTL_H) if (vendor.startswith(SHORT_CLAIM_VENDORS) or r.get("derived_from_regions")) else None
    ts = [t for t in (expires_at(c), r.get("availability_expires_at"), short) if _parse(t)]
    return min(ts, key=_parse) if ts else None


BUILD_HORIZON_MIN = 25  # Gauge re24 (a): build cutoff = Scout cadence + deploy. Every Scout push rebuilds; the */10 backstop rebuilds before any published claim expires


def build_now(now: datetime | None = None) -> datetime:
    """Build-time clock: now + LW_BUILD_HORIZON_MIN (set by the page/feed generator). A claim that would expire within the
    cutoff (25 min: Scout cadence + deploy) is written as unknown, so static output is rebuilt (next Scout push, or the
    backstop that fires when a published claim is within 20 min of expiry) before any published claim expires. The MCP
    applies expiry at request time and is the source of truth; feed consumers must still enforce availability_expires_at."""
    from datetime import timedelta
    return (now or now_utc()) + timedelta(minutes=int(os.environ.get("LW_BUILD_HORIZON_MIN") or 0))


PRICE_JOIN_USD = 0.005  # Gauge T73: a stock claim stands only if the price in force when stock was read is within $0.005 of today's
PRICE_JOIN_NOTE = ("The price changed after this stock check (the price shown when stock was read differs from today's "
                   "price by more than $0.005), so the stock claim is dropped and shown as unknown until a newer check.")
_SNAP_CACHE: dict | None = None


def _snapshot_prices() -> dict:
    """series key -> [(verified_at, price_usd)] from the daily price snapshots (append-only)."""
    global _SNAP_CACHE
    if _SNAP_CACHE is None:
        from . import gpu_history
        _SNAP_CACHE = {}
        try:
            snaps = gpu_history.load_snapshots()
        except Exception:
            snaps = []
        for snap in snaps:
            for row in snap.get("rows", []):
                if row.get("verified_at") and row.get("price_usd") is not None:
                    _SNAP_CACHE.setdefault(row["key"], []).append((row["verified_at"], per_gpu_price(row)))
    return _SNAP_CACHE


def per_gpu_price(row: dict) -> float | None:
    """Per-GPU price, the same unit as the feed's price_usd: monthly servers divided by gpu_count, otherwise the
    per-GPU hourly rate (hourly_usd; an 8x Lambda server at $31.92/h is $3.99 per GPU-hour)."""
    if row.get("price_usd") is None:
        return None
    n = row.get("gpu_count") or 1
    if row.get("billing_unit") == "monthly":
        return round(row["price_usd"] / n, 2)
    return row["hourly_usd"] if row.get("hourly_usd") is not None else round(row["price_usd"] / n, 6)


def price_at_claim(price_rec: dict, claim_at) -> tuple[float | None, str | None]:
    """(per-GPU price, price read time) of the price in force at claim_at: the latest price read at or before the stock read."""
    from . import gpu_history
    t = _parse(claim_at)
    if t is None or not isinstance(price_rec, dict) or price_rec.get("price_usd") is None:
        return None, None
    key = gpu_history.series_key(price_rec["vendor"], price_rec["gpu"], price_rec["tier"], price_rec.get("vram_gb"), price_rec.get("gpu_count", 1))
    cur_at = price_rec.get("verified_at") or price_rec.get("checked_at")
    cands = list(_snapshot_prices().get(key, [])) + ([(cur_at, per_gpu_price(price_rec))] if cur_at else [])
    cands = [(_parse(a), a, p) for a, p in cands if _parse(a) and _parse(a) <= t]
    if not cands:
        return None, None
    _, at, p = max(cands, key=lambda c: c[0])
    return p, at


def price_join_guard(a: dict, price_rec: dict | None) -> dict:
    """A stock claim read against a price that no longer matches today's (> $0.005 apart) is dropped (unknown)."""
    if not isinstance(a, dict) or a.get("in_stock") is None or not isinstance(price_rec, dict) or price_rec.get("price_usd") is None:
        return a
    p, p_at = price_at_claim(price_rec, a.get("checked_at"))
    # T73 F4 (additive): every stock claim carries when stock was read, when the price in force then was read, and
    # that price, so the 60 s two-read and +/-$0.005 join rules can be audited from the feed and the MCP output
    # price_at_claim_usd is per GPU (gpu_count says how many GPUs the priced server has), the feed's price_usd unit
    audit = {"stock_read_at": a.get("checked_at"), "price_read_at": p_at, "price_at_claim_usd": p,
             "gpu_count": price_rec.get("gpu_count") or 1}
    if p is None or abs(float(p) - float(per_gpu_price(price_rec))) <= PRICE_JOIN_USD + 1e-9:
        return {**a, **audit}
    out = {"status": "unknown (price changed)", "in_stock": None, "price_join_failed": True,
           "checked_at": a.get("checked_at"), "origin": a.get("origin"), "note": PRICE_JOIN_NOTE, **audit}
    for k in ("source", "source_label", "availability_expires_at"):
        if a.get(k):
            out[k] = a[k]
    return out


def availability_for(vendor: str, gpu: str, vram_gb, tier: str, record: dict | None = None, now: datetime | None = None,
                     price_rec: dict | None = None) -> dict:
    now = build_now(now)
    r = _index().get((vendor, gpu, vram_gb, _tier_key(tier)))
    if isinstance(record, dict) and r and record.get("same_capture_as_price") and \
            (_parse(record.get("checked_at")) or datetime.min.replace(tzinfo=timezone.utc)) > \
            (_parse(r.get("availability_checked_at")) or datetime.min.replace(tzinfo=timezone.utc)):
        r = None  # Gauge rel053: a newer record read from the same capture as the price beats an older Scout row
    if not r and isinstance(record, dict):
        return stale_guard(price_join_guard(_from_record(record), price_rec), now)  # record-origin stock expires at build time too
    # join first, then expiry: an expired claim still says which price it was read against (stale_guard keeps the audit)
    return stale_guard(price_join_guard(_scout(vendor, r), price_rec), now)


HELD_NOTE = "Held by Scout: fewer offers than its publish minimum, so no stock claim is shown."


TWO_READ_MIN_S = 60


SCOUT_STATUS_KEYS = ("availability_status", "availability_reason", "availability_reason_detail")


def _scout(vendor: str, r: dict | None) -> dict:
    """Additive: Scout's own availability_status/reason/reason_detail (schema 3.2) carried through unchanged."""
    out = _scout_base(vendor, r)
    for k in SCOUT_STATUS_KEYS:
        if r and r.get(k) is not None:
            out[k] = r[k]
    return out


def _scout_base(vendor: str, r: dict | None) -> dict:
    if r and r.get("feed_status") == "held_below_min_offers":  # v3.2: never shown as available
        return {"status": "unknown (held: below minimum offers)", "in_stock": None, "checked_at": r.get("availability_checked_at"),
                "note": HELD_NOTE, "feed_status": r["feed_status"], "origin": "scout",
                "availability_expires_at": _min_expiry(r, vendor)}
    if not r or r.get("in_stock") is None:
        out = {"status": "unknown", "in_stock": None, "checked_at": (r or {}).get("availability_checked_at"),
               "note": _clean((r or {}).get("availability_note")) or UNKNOWN_NOTE}
        if r and r.get("availability_checked_at"):  # Scout checked and found no signal: show when (unknown, not sold out)
            out["source"] = r.get("availability_source")
            out["origin"] = "scout"
        return out
    out = {"status": "available when checked" if r["in_stock"] else "out of stock when checked",
           "in_stock": r["in_stock"], "checked_at": r.get("availability_checked_at"),
           "refresh": REFRESH_MANUAL if vendor.lower().startswith("clore") else REFRESH_AUTOMATED,
           "note": NOTE, "origin": "scout", "availability_expires_at": _min_expiry(r, vendor)}
    out["max_age_hours"] = claim_hours(out["checked_at"], out["availability_expires_at"])
    for k in ("feed_status", "derived_from_regions", "offer_count", "unrented_servers", "stock_level", "available_regions", "available_regions_detail", "available_regions_label"):
        if r.get(k) is not None:
            out[k] = r[k]
    if "first_read_at" in r:  # Gauge T73 F1-F6 #2: both read times stored; a claim with reads < 60 s apart is not counted
        for k in ("first_read_at", "second_read_at", "second_read_gap_s", "second_read_basis"):
            if k in r:
                out[k] = r[k]
        g = r.get("second_read_gap_s")
        out["two_read_gap_ok"] = g is not None and g >= TWO_READ_MIN_S
    if out.get("available_regions"):  # re30 a: {label (original), zone, country, group} per published region
        from .regions import normalize as _rn
        out["available_regions_normalized"] = [_rn(x) for x in out["available_regions"]]
    rx = regions_expires_at(r)
    if not rx and r.get("derived_from_regions"):  # re20 P4: a derived row (out of stock too) gets a region expiry
        rx = _plus_h(r.get("availability_checked_at"), REGION_TTL_H)
    if rx:
        out["regions_expires_at"] = rx
    if r.get("unrented_servers") is not None:  # Clore: servers, not GPU offers
        out["unrented_servers_note"] = UNRENTED_NOTE
    if r.get("availability_source_type") == AUTH_LABEL or any(a in (r.get("availability_source") or "") for a in AUTH_SOURCES):
        out["source_label"] = AUTH_LABEL
    if r.get("availability_note"):
        out["detail"] = _clean(r["availability_note"])
    if vendor == "Vast.ai":
        out["consistency_note"] = VAST_NOTE
    return out
