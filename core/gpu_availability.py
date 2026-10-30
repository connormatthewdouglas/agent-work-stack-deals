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
    if a.get("in_stock") is None:
        return {"status": "unknown", "in_stock": None, "checked_at": a.get("checked_at"),
                "source": a.get("source"), "note": _clean(a.get("note")) or UNKNOWN_NOTE}
    out = {"status": "available when checked" if a["in_stock"] else "out of stock when checked",
           "in_stock": bool(a["in_stock"]), "checked_at": a.get("checked_at"),
           "refresh": "manual snapshot, time shown (prices checked daily)", "source": a.get("source"), "note": NOTE,
           "origin": "record", "max_age_hours": AVAIL_MAX_AGE_H, "availability_expires_at": expires_at(a.get("checked_at"))}
    if a.get("stock_level"):
        out["stock_level"] = str(a["stock_level"])
    if a.get("same_capture_as_price"):
        out["same_capture_as_price"] = True  # J6: price quote and stock count read from one page capture
    if a.get("note"):
        out["detail"] = _clean(a["note"])
    return out


AVAIL_MAX_AGE_H = 8  # same limit as Scout's enrich_feed_v2 (2x its 4h cadence)
STALE_NOTE = (f"This availability check is more than {AVAIL_MAX_AGE_H} h old, so it is shown as unknown "
              "(not in stock, not sold out) until a newer check is imported.")


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
    out["regions_expired"] = True
    out["regions_note"] = f"region list expires at {et_hm(a['regions_expires_at'])} (left out once expired or expiring before the next rebuild). " + REGIONS_NOTE
    return out


def stale_guard(a, now: datetime | None = None):
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
           "availability_stale": True, "checked_at": a.get("checked_at"), "max_age_hours": AVAIL_MAX_AGE_H,
           "origin": a["origin"], "note": STALE_NOTE}
    if a.get("derived_from_regions"):
        out["derived_from_regions"] = True
    for k in ("source", "source_label", "availability_expires_at", "feed_status"):
        if a.get(k):
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


BUILD_HORIZON_MIN = 60  # N3: the next rebuild is not guaranteed sooner (hourly gated import; GitHub cron can be late)


def build_now(now: datetime | None = None) -> datetime:
    """Build-time clock: now + LW_BUILD_HORIZON_MIN (set by the page/feed generator). A claim that would expire before the
    next rebuild is written as unknown, so static HTML and JSON never hold a claim past its expiry."""
    from datetime import timedelta
    return (now or now_utc()) + timedelta(minutes=int(os.environ.get("LW_BUILD_HORIZON_MIN") or 0))


def availability_for(vendor: str, gpu: str, vram_gb, tier: str, record: dict | None = None, now: datetime | None = None) -> dict:
    now = build_now(now)
    r = _index().get((vendor, gpu, vram_gb, _tier_key(tier)))
    if not r and isinstance(record, dict):
        return stale_guard(_from_record(record), now)  # record-origin stock expires at build time too
    return stale_guard(_scout(vendor, r), now)


HELD_NOTE = "Held by Scout: fewer offers than its publish minimum, so no stock claim is shown."


def _scout(vendor: str, r: dict | None) -> dict:
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
           "refresh": "manual snapshot, time shown (prices checked daily)",
           "note": NOTE, "origin": "scout", "max_age_hours": AVAIL_MAX_AGE_H,
           "availability_expires_at": _min_expiry(r, vendor)}
    for k in ("feed_status", "derived_from_regions", "offer_count", "unrented_servers", "stock_level", "available_regions", "available_regions_detail", "available_regions_label"):
        if r.get(k) is not None:
            out[k] = r[k]
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
