"""Availability attached to GPU rates (T11/T19), from data/gpu_availability/latest.json (Lantern Scout v2).

Display rules: unknown -> "unknown" (never "out of stock"); availability carries its own checked_at and cadence
(a manual Scout snapshot, time shown per row) separate from the daily price check; stock is never a guarantee.

P72: every availability object carries max_age_source (provider / policy / fallback) and always has
availability_expires_at (null when there is no time basis, with max_age_reason). Values are never invented.

P73: a crashed stock/terms probe is recorded as probe_error plus probe_attempted_at. That attempt stamp is
not a successful check. Freshness, the 72h ceiling and expire_held_rows still read only successful-check
stamps (evidence.checked_at / verified_at / a successful checked_at). Failed collection never writes a
fresh verified_at or success checked_at.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "gpu_availability" / "latest.json"
NOTE = STOCK_EXPLAINER = ("Where a status is shown, it is a snapshot from the time in the row, not a guarantee. Statuses from a vendor's live stock check can change within minutes; \u201cvendor-labelled\u201d means a fixed label on the vendor's page, not a capacity check; \u201c\u2014\u201d or \u201cnever read\u201d means no stock check has been taken; \u201cunknown (stale availability, last checked \u2026)\u201d means a check was taken and the claim has expired. Neither is sold out.")
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
# P68 (additive): the last firm claim's own window, kept across failed/no_source reads (never extended).
LAST_KNOWN_WINDOW_KEYS = ("last_known_expires_at", "last_known_max_age_hours")


def _check_ts(src: dict) -> str | None:
    """Observation / check time on an availability dict or a Scout latest.json row."""
    for k in ("checked_at", "availability_checked_at", "last_check_at"):
        v = src.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def is_firm_observation(src: dict) -> bool:
    """P64: a real successful stock reading (in_stock true or false) with a check time.

    Quota, region, rate-limit and recorded check failures are not firm observations, even if in_stock
    was stored as false. Display only; ranking still reads in_stock after apply_probe_outcome nulls those.
    """
    if not isinstance(src, dict) or not isinstance(src.get("in_stock"), bool) or not _check_ts(src):
        return False
    from .probe_reason import is_quota_or_region_failure, _FAILED
    if is_quota_or_region_failure(src):
        return False
    reason = src.get("availability_reason")
    if reason is None and isinstance(src.get("availability"), dict):
        reason = src["availability"].get("availability_reason")
    if isinstance(reason, str) and (reason.startswith("check_failed") or reason in _FAILED):
        return False
    return True


def last_known(src: dict) -> tuple[bool | None, str | None]:
    """P36/P64: the most recent firm stock answer and its check time. A current firm claim (in_stock true/false
    that is not a quota/region/rate-limit or check failure) is its own last known value; an unknown, failed, or
    lapsed claim keeps whatever an earlier pass recorded. Never invented: both null when no firm, dated claim
    was ever seen. Display only; ranking reads in_stock, never these."""
    if is_firm_observation(src):
        return src["in_stock"], src.get("checked_at") or _check_ts(src)
    v, t = src.get("last_known_in_stock"), src.get("last_known_at")
    return (v, t) if isinstance(v, bool) and isinstance(t, str) and t else (None, None)


def last_known_window(av: dict) -> tuple[str | None, float | None]:
    """Expiry and TTL of the last firm stock claim (P68).

    Anchored on last_known_at, never on a later failed-read checked_at, so a no_source
    or quota check cannot extend the last good window. Does not change stale_guard.
    """
    if not isinstance(av, dict):
        return None, None
    _, t = last_known(av)
    if not t:
        return None, None
    if _parse(av.get("last_known_expires_at")):
        h = av.get("last_known_max_age_hours")
        if not isinstance(h, (int, float)) or isinstance(h, bool):
            h = claim_hours(t, av["last_known_expires_at"])
        return av["last_known_expires_at"], float(h)
    h = av.get("last_known_max_age_hours")
    if isinstance(h, (int, float)) and not isinstance(h, bool) and h >= 0:
        return _plus_h(t, h), float(h)
    exp, mh = av.get("availability_expires_at"), av.get("max_age_hours")
    ch, lk = _parse(av.get("checked_at")), _parse(t)
    # Same claim (no later check, or checked_at is the last_known_at): the live expiry is the window.
    if _parse(exp) and lk and (ch is None or ch <= lk):
        if not isinstance(mh, (int, float)) or isinstance(mh, bool):
            mh = claim_hours(t, exp)
        return exp, float(mh)
    # Later failed/no_source read: re-anchor on last_known_at using the row TTL, which
    # yields an earlier expiry than checked_at + TTL (never extend).
    if isinstance(mh, (int, float)) and not isinstance(mh, bool) and mh >= 0:
        return _plus_h(t, mh), float(mh)
    if _parse(exp) and lk and ch and ch > lk:
        # TTL unknown; do not adopt a later checked_at-anchored expiry.
        # Fall through to the 8h policy clock that stale_guard already uses for last_known.
        pass
    return _plus_h(t, AVAIL_MAX_AGE_H), float(AVAIL_MAX_AGE_H)


def annotate_last_known_window(av: dict, now: datetime | None = None) -> dict:
    """P68: flag last_known against its own claim window and surface that window.

    Purely additive, after stale_guard (and P72 annotate_max_age). Never invents a
    last_known value, never changes in_stock / availability_stale / the 8h P64 clock.
    """
    if not isinstance(av, dict):
        return av
    out = dict(av)
    v, t = last_known(out)
    if not (isinstance(v, bool) and t):
        return out
    out["last_known_in_stock"], out["last_known_at"] = v, t
    exp, h = last_known_window(out)
    if exp:
        out["last_known_expires_at"] = exp
    if h is not None:
        out["last_known_max_age_hours"] = h
    x = _parse(exp)
    if x is not None:
        out["last_known_outside_window"] = (now or now_utc()) > x
    return out


def apply_probe_outcome(av: dict, previous: dict | None = None) -> dict:
    """P64: last_known_* updates only on a firm observation. A quota/region (or rate-limit) failure sets
    the current reading to unknown (in_stock null) and keeps the previous last_known value and time.
    Check time (checked_at, and last_check_at when present) comes from the current probe and moves forward."""
    if not isinstance(av, dict):
        return av
    out = dict(av)
    ts = out.get("checked_at") or _check_ts(out)
    if ts:
        out["checked_at"] = ts
    if "last_check_at" in out or (previous and "last_check_at" in previous):
        if ts:
            out["last_check_at"] = ts
    if is_firm_observation(out):
        out["last_known_in_stock"], out["last_known_at"] = out["in_stock"], out["checked_at"]
        return out
    from .probe_reason import is_quota_or_region_failure
    if is_quota_or_region_failure(out):
        out["in_stock"] = None
        st = out.get("status")
        if isinstance(st, str) and (st.startswith("out of stock") or st.startswith("available when checked")):
            out["status"] = "unknown"
    prior = last_known(previous) if previous is not None else last_known(out)
    if isinstance(prior[0], bool) and prior[1]:
        out["last_known_in_stock"], out["last_known_at"] = prior
    else:
        for k in LAST_KNOWN_KEYS:
            out.pop(k, None)
    return out


def apply_probe(previous: dict | None, current: dict, now: datetime | None = None) -> dict:
    """Apply a new probe onto previous availability state (P64). Used by tests and Scout import.

    If current carries a crashed probe (`error` as an exception, or `probe_crash`), record
    probe_error + probe_attempted_at and do not treat the attempt as a successful check.
    """
    cur = dict(current)
    crash = cur.pop("probe_crash", None) or cur.pop("error", None)
    if isinstance(crash, BaseException):
        attempted = cur.get("probe_attempted_at") or cur.get("attempted_at") or now
        return apply_probe_crash(previous, crash, attempted_at=attempted)
    if previous and not cur.get("origin") and previous.get("origin"):
        cur["origin"] = previous["origin"]
    out = apply_probe_outcome(cur, previous)
    if out.get("origin") in ("scout", "record"):
        return stale_guard(out, now)
    return out


def carry_scout_row(row: dict, previous: dict | None) -> dict:
    """Write last_known_* onto a data/gpu_availability/latest.json row from the previous snapshot."""
    cur = {**row, "checked_at": row.get("availability_checked_at") or row.get("checked_at")}
    prev = None
    if previous:
        prev = {**previous, "checked_at": previous.get("availability_checked_at") or previous.get("checked_at")
                or previous.get("last_known_at")}
    out = apply_probe_outcome(cur, prev)
    if is_firm_observation(out):
        # Current in_stock is the last firm answer; do not duplicate it as last_known_* on a firm snapshot row.
        for k in LAST_KNOWN_KEYS:
            row.pop(k, None)
        return row
    v, ts = out.get("last_known_in_stock"), out.get("last_known_at")
    if isinstance(v, bool) and ts:
        row["last_known_in_stock"], row["last_known_at"] = v, ts
    else:
        for k in LAST_KNOWN_KEYS:
            row.pop(k, None)
    if out.get("in_stock") is None and is_firm_observation(cur) is False and cur.get("in_stock") is not None:
        # quota/region: current reading is unknown; do not persist a false as a stock claim
        from .probe_reason import is_quota_or_region_failure
        if is_quota_or_region_failure(cur):
            row["in_stock"] = None
    return row


def stale_guard(a, now: datetime | None = None):
    """_stale_guard plus P36/P64: when a firm claim lapses, keep last_known_* from before the lapse.
    A last_known true and a last_known false (sold_out) use the same clock: marked stale
    AVAIL_MAX_AGE_H hours after last_known_at (or sooner if a live claim's own expiry already lapsed it).
    When the current reading is a failed check, checked_at may be newer; last_known still ages from last_known_at."""
    out = _stale_guard(a, now)
    if not isinstance(a, dict) or not isinstance(out, dict):
        return out
    if out is not a and out.get("availability_stale") and not a.get("availability_stale"):
        v, t = last_known(a)
        out = {**out, "last_known_in_stock": v, "last_known_at": t}
    return _age_last_known(out, now)


def request_availability(av, now: datetime | None = None):
    """P64 request-time expiry check shared by find_available_gpus, compare_gpu_prices,
    and estimate_job_cost. Applies stale_guard so a lapsed stock claim is never shown
    as in_stock true or false; last_known_* stays visible. Non-dicts pass through."""
    if not isinstance(av, dict):
        return av
    return stale_guard(av, now)


def with_request_availability(r: dict, now: datetime | None = None) -> dict:
    """Copy of a rate with availability passed through request_availability (P64)."""
    if not isinstance(r, dict) or not isinstance(r.get("availability"), dict):
        return r
    guarded = request_availability(r["availability"], now)
    return r if guarded is r["availability"] else {**r, "availability": guarded}


def _age_last_known(av: dict, now: datetime | None = None) -> dict:
    """If the current reading is not a firm observation, mark last_known stale on the same AVAIL_MAX_AGE_H
    clock as a live in_stock true or sold_out claim, without moving checked_at back."""
    if is_firm_observation(av) or av.get("availability_stale"):
        # Firm claims already went through _stale_guard on checked_at (== last_known_at). Already-lapsed
        # objects keep last_known (P36) and stay stale.
        if av.get("availability_stale"):
            v, t = last_known(av)
            if v is not None and (av.get("last_known_in_stock") is not v or av.get("last_known_at") != t):
                return {**av, "last_known_in_stock": v, "last_known_at": t}
        return av
    v, t = last_known(av)
    if not isinstance(v, bool) or not t:
        return av
    ghost = {"in_stock": v, "checked_at": t, "origin": av.get("origin") or "scout",
             "availability_expires_at": expires_at(t)}
    g = _stale_guard(ghost, now)
    if not g.get("availability_stale"):
        if av.get("last_known_in_stock") is v and av.get("last_known_at") == t:
            return av
        return {**av, "last_known_in_stock": v, "last_known_at": t}
    out = dict(av)
    out["availability_stale"] = True
    out["in_stock"] = None
    out["last_known_in_stock"], out["last_known_at"] = v, t
    out.setdefault("max_age_hours", AVAIL_MAX_AGE_H)
    # P64: last_known is marked stale on last_known_at's 8h clock; keep the same
    # "unknown (stale availability, last checked ...)" label _stale_guard uses for a
    # lapsed firm claim (PR #323). Do not leave a bare "unknown" next to availability_stale.
    if g.get("status"):
        out["status"] = g["status"]
        # Status cites last_known_at. If the current reading has no check time
        # (no_source / no_matching_api_row), fill checked_at so it agrees.
        # Do not move a newer failed-check timestamp backward (P64).
        if not out.get("checked_at") and t:
            out["checked_at"] = t
    if g.get("note"):
        out["note"] = g["note"]
    if g.get("max_age_hours") is not None:
        out["max_age_hours"] = g["max_age_hours"]
    return out


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



MAX_AGE_SOURCE_PROVIDER = "provider"
MAX_AGE_SOURCE_POLICY = "policy"
MAX_AGE_SOURCE_FALLBACK = "fallback"
# Same vendors as _min_expiry / SHORT_CLAIM_VENDORS: 1h overall claims for Lambda and Verda only.
# RunPod, Oblivus, Novita and Thunder stay at AVAIL_MAX_AGE_H (8h), as on main.
POLICY_ONE_HOUR_VENDORS = SHORT_CLAIM_VENDORS
_PROBE_SECRET_QS = re.compile(
    r"(?i)([?&](?:access_token|token|key|secret|password|passwd|api[_-]?key|auth|authorization|bearer)=)[^&\s]*"
)
_PROBE_SECRET_KV = re.compile(
    r"(?i)\b(access_token|token|secret|password|passwd|api[_-]?key|authorization|bearer)\b\s*[:=]\s*\S+"
)
_PROBE_USERINFO = re.compile(r"://[^/@\s]+:[^/@\s]+@")


def sanitize_probe_message(message: str, limit: int = 200) -> str:
    """Short exception text with credentials, tokens, and userinfo URLs stripped. Never returns secrets."""
    s = " ".join(str(message or "").split())
    s = _PROBE_USERINFO.sub("://[redacted]@", s)
    s = _PROBE_SECRET_QS.sub(r"\1[redacted]", s)
    s = _PROBE_SECRET_KV.sub(r"\1=[redacted]", s)
    return s[:limit]


def format_probe_error(exc: BaseException) -> dict:
    """Additive probe_error object: exception class plus a sanitized short message. No URLs with credentials."""
    return {"type": type(exc).__name__, "message": sanitize_probe_message(exc)}


def policy_ttl_hours(vendor: str | None = None, tier: str | None = None,
                     *, derived_from_regions: bool = False) -> float:
    """Claim-lifetime policy in hours, aligned with _min_expiry.

    15 min Verda spot; 1 h for Lambda, Verda, and region-derived claims; 8 h otherwise
    (including RunPod, Oblivus, Novita, and Thunder). This table describes policy. The
    published annotation still reports the TTL stale_guard actually applied: if a row
    had no availability_expires_at, that bar is AVAIL_MAX_AGE_H (8 h).
    """
    v = vendor or ""
    if v.startswith("Verda") and "Spot" in (tier or ""):
        return 0.25
    if derived_from_regions or v.startswith(SHORT_CLAIM_VENDORS):
        return 1.0
    return float(AVAIL_MAX_AGE_H)


def annotate_max_age(av: dict, vendor: str | None = None, tier: str | None = None) -> dict:
    """P72: every availability row gets max_age_source and a always-present availability_expires_at.

    Purely additive: call only after stale_guard so enforcement is unchanged.
    provider: a vendor-stated lifetime (provider_max_age_hours on the row).
    policy: the TTL stale_guard actually applied — Scout/_min_expiry availability_expires_at
    when present, otherwise AVAIL_MAX_AGE_H (8 h). That matches main: 1 h only when
    _min_expiry already put a short expiry on the row (Lambda, Verda, region-derived).
    fallback: no time basis to compute expiry; max_age_hours and availability_expires_at are null
    and max_age_reason explains why. Never invents a timestamp.
    """
    if not isinstance(av, dict):
        return av
    out = dict(av)
    vendor = vendor or out.get("advertiser") or out.get("vendor")
    tier = tier if tier is not None else out.get("tier")
    checked = out.get("checked_at") or out.get("availability_checked_at")
    provider_h = out.get("provider_max_age_hours")
    derived = bool(out.get("derived_from_regions"))

    if isinstance(provider_h, (int, float)) and not isinstance(provider_h, bool) and provider_h >= 0 and _parse(checked):
        out["max_age_hours"] = float(provider_h)
        out["max_age_source"] = MAX_AGE_SOURCE_PROVIDER
        out["availability_expires_at"] = _plus_h(checked, provider_h)
        out.pop("max_age_reason", None)
        return out

    existing = out.get("availability_expires_at")
    if _parse(checked) and _parse(existing):
        out["max_age_hours"] = claim_hours(checked, existing)
        out["max_age_source"] = MAX_AGE_SOURCE_POLICY
        out["availability_expires_at"] = existing
        out.pop("max_age_reason", None)
        return out

    if _parse(checked):
        # No expiry was present for stale_guard to enforce, so the applied bar is 8 h.
        # Do not write a shorter Lambda/Verda policy expiry here: that would change
        # later request-time enforcement. Firm short claims already carry _min_expiry.
        ttl = float(AVAIL_MAX_AGE_H)
        out["max_age_hours"] = ttl
        out["max_age_source"] = MAX_AGE_SOURCE_POLICY
        out["availability_expires_at"] = _plus_h(checked, ttl)
        out.pop("max_age_reason", None)
        return out

    out["max_age_hours"] = None
    out["max_age_source"] = MAX_AGE_SOURCE_FALLBACK
    out["availability_expires_at"] = None
    reason = "no check time to compute expiry"
    if (out.get("availability_reason") or "") == "never_ran":
        reason = "never_ran: no check time to compute expiry"
    elif (out.get("availability_reason") or "") == "no_source":
        reason = "no_source: no check time to compute expiry"
    out["max_age_reason"] = reason
    return out


def apply_probe_crash(previous: dict | None, exc: BaseException, attempted_at) -> dict:
    """P73: record a crashed stock/terms probe without treating the attempt as a successful check.

    Writes probe_error (class + short sanitized message) and probe_attempted_at. Leaves verified_at
    and the successful checked_at unchanged (does not invent them). Availability in_stock is left
    as previously known or unknown; nothing is ranked from this attempt.
    """
    out = dict(previous) if isinstance(previous, dict) else {}
    stamp = attempted_at
    if hasattr(stamp, "strftime"):
        if getattr(stamp, "tzinfo", None) is None:
            from datetime import timezone as _tz
            stamp = stamp.replace(tzinfo=_tz.utc)
        stamp = stamp.astimezone(__import__("datetime").timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    out["probe_error"] = format_probe_error(exc)
    out["probe_attempted_at"] = stamp
    # Do not refresh verified_at or a successful checked_at. If there was never a successful
    # check, those keys stay absent (unknown stays unknown).
    return out


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
    # Keep the firm, dated claim that existed before this drop (observed value and its
    # observation time). Never invented: both null when there was no firm, dated claim.
    # in_stock stays null; ranking still reads in_stock. Staleness is applied by stale_guard.
    v, ts = last_known(a)
    out["last_known_in_stock"], out["last_known_at"] = v, ts
    return out


def publish_availability(av: dict, vendor: str | None = None, tier: str | None = None,
                         now: datetime | None = None, *, annotate: bool = True) -> dict:
    """stale_guard first, then optional P72 annotation. annotate=False is the main pipeline."""
    guarded = stale_guard(av, now)
    if not annotate:
        return guarded
    return annotate_max_age(guarded, vendor, tier)


def availability_for(vendor: str, gpu: str, vram_gb, tier: str, record: dict | None = None, now: datetime | None = None,
                     price_rec: dict | None = None) -> dict:
    now = build_now(now)
    r = _index().get((vendor, gpu, vram_gb, _tier_key(tier)))
    if isinstance(record, dict) and r and record.get("same_capture_as_price") and \
            (_parse(record.get("checked_at")) or datetime.min.replace(tzinfo=timezone.utc)) > \
            (_parse(r.get("availability_checked_at")) or datetime.min.replace(tzinfo=timezone.utc)):
        r = None  # Gauge rel053: a newer record read from the same capture as the price beats an older Scout row
    def _publish(av):
        # Annotation is a purely additive pass after stale_guard. Enforcement, TTLs,
        # the stale set and stale reasons stay as on main.
        return publish_availability(av, vendor, tier, now, annotate=True)
    if not r and isinstance(record, dict):
        return _publish(price_join_guard(_from_record(record), price_rec))
    # join first, then expiry: an expired claim still says which price it was read against
    return _publish(price_join_guard(_scout(vendor, r), price_rec))


HELD_NOTE = "Held by Scout: fewer offers than its publish minimum, so no stock claim is shown."


TWO_READ_MIN_S = 60


SCOUT_STATUS_KEYS = ("availability_status", "availability_reason", "availability_reason_detail")


def _scout(vendor: str, r: dict | None) -> dict:
    """Additive: Scout's own availability_status/reason/reason_detail (schema 3.2) carried through unchanged."""
    out = _scout_base(vendor, r)
    for k in SCOUT_STATUS_KEYS:
        if r and r.get(k) is not None:
            out[k] = r[k]
    if r:
        for k in LAST_KNOWN_KEYS + LAST_KNOWN_WINDOW_KEYS:
            if r.get(k) is not None and k not in out:
                out[k] = r[k]
        prev = r if any(r.get(k) is not None for k in LAST_KNOWN_KEYS) else None
        if prev is not None or not is_firm_observation(out):
            out = apply_probe_outcome(out, prev)
            # Fresh firm claims keep the P36 feed shape (no last_known keys); MCP full mode fills them.
            if is_firm_observation(out):
                for k in LAST_KNOWN_KEYS:
                    out.pop(k, None)
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
    if r.get("availability_source"):  # URL or API identifier from Scout; never invent a source when the snapshot has none
        out["source"] = r["availability_source"]
    if r.get("availability_source_type") == AUTH_LABEL or any(a in (r.get("availability_source") or "") for a in AUTH_SOURCES):
        out["source_label"] = AUTH_LABEL
    if r.get("availability_note"):
        out["detail"] = _clean(r["availability_note"])
    if vendor == "Vast.ai":
        out["consistency_note"] = VAST_NOTE
    return out
