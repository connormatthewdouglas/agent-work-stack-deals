"""Hosted-only GPU price watches with signed webhook alerts (free opt-in key; no payment, no email sending).

Pure logic (no Workers imports) so it is unit-tested in CPython; entry.py wires it to D1, fetch and the cron.

Privacy/storage: per key we keep the key's SHA-256 hash, the webhook URL, an optional contact email, the watch
specs, delivered event ids (for dedupe) and per-key daily counts. No call payloads, IPs or user agents.
Signing: the per-key webhook secret is DERIVED, never stored: HMAC-SHA256(WATCH_SIGNING_MASTER, "whsec|" + key_id).
It is returned once at signup; receivers verify X-Lantern-Signature: t=<unix>,v1=hex(HMAC(secret, f"{t}.{body}")).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
from datetime import date, timedelta
from urllib.parse import urlsplit

from core import deals as core_deals
from core.ids import rate_id

KEY_RE = re.compile(r"^lwk_([0-9a-f]{12})_[A-Za-z0-9_-]{20,64}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
KINDS = ("down", "up", "new")
MAX_WATCHES_PER_KEY = 20
MAX_ALERTS_PER_KEY_PER_DAY = 100
MAX_CALLS_PER_KEY_PER_DAY = 2000
MAX_SIGNUPS_PER_DAY = 200
MAX_POSTS_PER_RUN = 40          # free plan: 50 subrequests per invocation; 3 feed fetches + headroom
LOOKBACK_DAYS = 7               # failed deliveries are retried on later runs within this window
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet", ".corp")


class WatchError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# ---- keys & signing ------------------------------------------------------------------------------------------------
def new_key() -> tuple[str, str]:
    key_id = secrets.token_hex(6)
    return key_id, f"lwk_{key_id}_{secrets.token_urlsafe(24)}"


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_key(key) -> str:
    m = KEY_RE.match(str(key or "").strip())
    if not m:
        raise WatchError("unauthorized", "missing or malformed api_key (get one with create_watch_key)")
    return m.group(1)


def check_key(key: str, stored_hash: str | None) -> bool:
    return bool(stored_hash) and hmac.compare_digest(key_hash(key), stored_hash)


def signing_secret(master: str, key_id: str) -> str:
    if not master:
        raise WatchError("watch_unavailable", "watches are not configured on this deployment")
    return "whsec_" + hmac.new(master.encode("utf-8"), f"whsec|{key_id}".encode("utf-8"), hashlib.sha256).hexdigest()


def sign(secret: str, ts: int, body: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), f"{ts}.{body}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify(secret: str, header: str, body: str, now: int, tolerance: int = 300) -> bool:
    """Reference verifier for receivers (also used by tests)."""
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    try:
        ts = int(parts["t"])
    except (KeyError, ValueError):
        return False
    return abs(now - ts) <= tolerance and hmac.compare_digest(sign(secret, ts, body), header)


# ---- webhook URL safety --------------------------------------------------------------------------------------------
def _ip_literal(host: str):
    h = host.strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        pass
    # inet_aton-style forms browsers/resolvers accept: 2130706433, 0x7f.1, 127.1, 0177.0.0.1
    if re.fullmatch(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+)){0,3}", h, re.I):
        return "numeric"
    return None


def validate_webhook_url(url) -> str:
    url = str(url or "").strip()
    if len(url) > 500:
        raise WatchError("invalid_argument", "webhook_url too long")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        raise WatchError("invalid_argument", "webhook_url is not a valid URL") from None
    if u.scheme != "https":
        raise WatchError("invalid_argument", "webhook_url must use https")
    host = (u.hostname or "").lower().rstrip(".")
    if not host or u.username or u.password:
        raise WatchError("invalid_argument", "webhook_url needs a host and no user:password")
    if port not in (None, 443):
        raise WatchError("invalid_argument", "webhook_url must use the default https port (443)")
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES) or "." not in host and not host.startswith("["):
        raise WatchError("invalid_argument", "webhook_url host must be a public internet name")
    ip = _ip_literal(host)
    if ip == "numeric":
        raise WatchError("invalid_argument", "webhook_url must not be a numeric IP form")
    if ip is not None:
        mapped = getattr(ip, "ipv4_mapped", None) or ip
        if not mapped.is_global or mapped.is_multicast:
            raise WatchError("invalid_argument", "webhook_url must not point at a private, loopback, link-local or reserved IP")
    return url


def validate_email(email):
    if email in (None, ""):
        return None
    email = str(email).strip()
    if not EMAIL_RE.match(email):
        raise WatchError("invalid_argument", "email is optional contact only; it must look like name@example.com")
    return email


# ---- watch specs ---------------------------------------------------------------------------------------------------
def normalize_watch(gpu, max_hourly_usd, region=None, kinds=None) -> dict:
    gpu = str(gpu or "").strip()
    if not gpu or len(gpu) > 40:
        raise WatchError("invalid_argument", "gpu is required, e.g. 'H100' (substring match, like get_price_changes)")
    try:
        mx = float(max_hourly_usd)
    except (TypeError, ValueError):
        raise WatchError("invalid_argument", "max_hourly_usd must be a number (USD per GPU-hour)") from None
    if not 0 < mx < 1000:
        raise WatchError("invalid_argument", "max_hourly_usd must be between 0 and 1000")
    if isinstance(kinds, str):
        kinds = [k.strip() for k in kinds.split(",") if k.strip()]
    kinds = list(dict.fromkeys(kinds or ["down"]))
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise WatchError("invalid_argument", f"kinds must be among {', '.join(KINDS)}")
    region = (str(region).strip().upper() or None) if region else None
    if region and not re.fullmatch(r"[A-Z0-9-]{2,12}", region):
        raise WatchError("invalid_argument", "region is a code as published in availability.available_regions, e.g. 'US'")
    return {"gpu": gpu, "max_hourly_usd": round(mx, 6), "region": region, "kinds": kinds}


def rate_regions(prices_doc: dict) -> dict:
    """rate_id -> set of published region codes (only rates that publish regions)."""
    out = {}
    for r in (prices_doc or {}).get("rates") or []:
        regs = ((r.get("availability") or {}).get("available_regions")) or []
        if regs:
            out[rate_id({**r, "vendor": r.get("advertiser")})] = {str(x).upper() for x in regs}
    return out


def current_matches(prices_doc: dict, spec: dict, limit: int = 5) -> list[dict]:
    """Rates already at or under the threshold when the watch is created (reported, never alerted)."""
    regions = rate_regions(prices_doc)
    q = spec["gpu"].lower()
    rows = []
    for r in (prices_doc or {}).get("rates") or []:
        if q not in (r.get("gpu") or "").lower() or r.get("tier_class") == "reserved":
            continue
        h = r.get("hourly_equiv_usd")
        rid = rate_id({**r, "vendor": r.get("advertiser")})
        if h is None or h > spec["max_hourly_usd"] or (spec["region"] and spec["region"] not in regions.get(rid, ())):
            continue
        rows.append({"rate_id": rid, "vendor": r.get("advertiser"), "gpu": r.get("gpu"), "tier": r.get("tier"),
                     "hourly_usd": h, "source_url": r.get("source_url")})
    return sorted(rows, key=lambda x: x["hourly_usd"])[:limit]


def candidate_events(latest_doc: dict, history_doc: dict, today: str) -> list[dict]:
    """Price-change events (T38 ids) from the last LOOKBACK_DAYS of history plus today's newly tracked rates."""
    since = (date.fromisoformat(today) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    evs = {}
    if history_doc:
        # price_changes caps at 200; walk the cursor so nothing in the window is dropped
        first = core_deals.price_changes(None, history_doc, since=since, limit=200)
        for c in first["changes"]:
            evs[c["event_id"]] = c
        cur = first.get("next_cursor")
        while cur and first.get("has_more"):
            page = core_deals.price_changes(None, history_doc, cursor=cur, limit=200)
            for c in page["changes"]:
                evs[c["event_id"]] = c
            cur, first = page["next_cursor"], page
    if latest_doc:
        for c in core_deals.price_changes(latest_doc, None, limit=200)["changes"]:
            if c["direction"] == "new" and c.get("event_id"):
                evs.setdefault(c["event_id"], c)
    return sorted(evs.values(), key=lambda c: (c.get("date") or "", c["event_id"]))


def after_baseline(watch: dict, ev: dict) -> bool:
    """Only events published after the watch was created: history events by T38 seq, newly tracked rates (latest
    feed, no seq) by feed date. Rates already under the threshold at creation are reported, not alerted."""
    if isinstance(ev.get("seq"), int):
        return ev["seq"] > int(watch.get("baseline_seq") or 0)
    return (ev.get("date") or "") > (watch.get("baseline_day") or "")


def match(spec: dict, ev: dict, regions: dict) -> str | None:
    """Alert reason or None. Fires when a rate crosses at/under max_hourly_usd, or a change of a watched kind lands
    at/under it. Region-constrained watches only match rates that publish that region (unknown != match)."""
    if not after_baseline(spec, ev):
        return None
    if spec["gpu"].lower() not in (ev.get("gpu") or "").lower():
        return None
    if spec.get("region") and spec["region"] not in regions.get(ev.get("rate_id"), ()):
        return None
    to, frm, mx, d = ev.get("to_hourly_usd"), ev.get("from_hourly_usd"), spec["max_hourly_usd"], ev.get("direction")
    if to is None or to > mx:
        return None
    if d == "new":
        return "new_at_or_below_max"
    if frm is not None and frm > mx:
        return "crossed_below_max"
    if d in spec["kinds"]:
        return "price_change_at_or_below_max"
    return None


def payload(watch: dict, ev: dict, reason: str, sent_at: str) -> dict:
    return {"type": "lantern_works.price_watch.alert", "version": 1, "watch_id": watch["watch_id"],
            "event_id": ev["event_id"], "rate_id": ev.get("rate_id"), "reason": reason,
            "watch": {k: watch.get(k) for k in ("gpu", "region", "max_hourly_usd", "kinds")},
            "change": {k: ev.get(k) for k in ("date", "vendor", "gpu", "tier", "direction", "from_hourly_usd",
                                              "to_hourly_usd", "change_pct", "source_url")},
            "scope": "tracked providers only (not the whole market); confirm on the vendor page before spending",
            "sent_at": sent_at}


def plan_deliveries(watches: list[dict], events: list[dict], delivered: set, regions: dict, alerts_today: dict,
                    max_posts: int = MAX_POSTS_PER_RUN) -> list[tuple[dict, dict, str]]:
    """(watch, event, reason) to send this run. Never includes an already-delivered (watch_id, event_id); respects
    the per-key daily alert cap and the per-run subrequest budget."""
    out, per_key = [], dict(alerts_today)
    for w in sorted(watches, key=lambda w: w["watch_id"]):
        for ev in events:
            if len(out) >= max_posts:
                return out
            if (w["watch_id"], ev["event_id"]) in delivered:
                continue
            reason = match(w, ev, regions)
            if not reason:
                continue
            if per_key.get(w["key_id"], 0) >= MAX_ALERTS_PER_KEY_PER_DAY:
                break
            per_key[w["key_id"]] = per_key.get(w["key_id"], 0) + 1
            out.append((w, ev, reason))
    return out


def new_watch_id() -> str:
    return "w_" + secrets.token_hex(8)


def dumps(o) -> str:
    return json.dumps(o, separators=(",", ":"), sort_keys=True)
