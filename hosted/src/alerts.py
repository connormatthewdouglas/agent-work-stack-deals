"""F1 poll-only price alerts (Brain #1028), hosted only: create_alert / check_alerts / delete_alert.

No webhook, no email, no cron, no accounts, no PII. An agent creates an alert, gets a secret alert_token ONCE
(only its SHA-256 is stored), and polls check_alerts after the feed refresh (daily 10:23 UTC, plus mid-day Scout/Lium
rebuilds). An alert is a stable rate_id, or a gpu (+ optional vendor, vram_gb, tiers) filter, with a threshold and a
direction. It never fires on a held_stale row or a row whose last price verification is older than DEGRADED_HOURS (48 h); those are
reported in skipped_stale with would_have_crossed (computed for that poll only; the next check re-evaluates the current
feed). Pure logic here; D1 helpers come from watch_store (rows are plain dicts, SQL NULL -> None)."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

import watch as W
import watch_store as S
from core import data_age
from core import deals as core_deals
from core import eligibility as EL
from core.ids import rate_id

TOKEN_RE = re.compile(r"^lwa_([0-9a-f]{12})_[A-Za-z0-9_-]{20,64}$")
RATE_ID_RE = re.compile(r"^r_[0-9a-f]{12}$")
DIRECTIONS = ("below", "above")
TTL_DAYS = 30
EXPIRED_KEEP_DAYS = 7           # an expired alert stays visible (status expired) this long, then is purged
MAX_ALERTS_PER_TOKEN = 10
MAX_CHECKS_PER_TOKEN_PER_HOUR = 60
MAX_CHECKS_PER_TOKEN_PER_DAY = 500
MAX_CREATES_PER_IP_PER_DAY = 10
MAX_CREATES_PER_DAY = 100
MAX_ARGS_BYTES = 4096
MAX_ITEMS = 5                   # fired / skipped_stale rows listed per alert
STALE_HOURS = data_age.DEGRADED_HOURS
STALE_NOTE = (f"Never fires on a held_stale row or a row whose last price verification is older than {STALE_HOURS} hours "
              "(data_age_hours is measured from the row's verified_at, or checked_at if verified_at is missing, not from "
              "feed write time): those are listed in skipped_stale with would_have_crossed, and a crossing on stale data "
              "is not a fire. would_have_crossed is not stored; the next check_alerts re-evaluates the current feed, and "
              "a now-fresh row can fire then if the current price still crosses (that is not a delayed fire of the stale crossing).")

_NUM, _STR = {"type": ["number", "null"]}, {"type": ["string", "null"]}
_ITEM = {"type": "object", "required": ["rate_id", "vendor", "gpu", "hourly_usd"],
         "properties": {"rate_id": {"type": "string"}, "vendor": _STR, "gpu": _STR, "vram_gb": {"type": ["integer", "null"]},
                        "tier": _STR, "hourly_usd": _NUM, "checked_at": _STR, "price_age_hours": _NUM, "source_url": _STR,
                        "in_stock": {"type": ["boolean", "null"]}, "hold": {"type": "string"}, "reason": _STR,
                        "would_have_crossed": {"type": "boolean"}}}
_ALERT = {"type": "object", "required": ["alert_id", "threshold_usd", "direction", "expires_at"],
          "properties": {"alert_id": {"type": "string"}, "rate_id": _STR, "gpu": _STR, "vendor": _STR, "vram_gb": {"type": ["integer", "null"]},
                         "tiers": {"type": ["array", "null"], "items": {"type": "string"}}, "threshold_usd": {"type": "number"},
                         "direction": {"type": "string", "enum": list(DIRECTIONS)}, "created_at": _STR, "expires_at": {"type": "string"}}}
_RESULT = {"type": "object", "required": ["alert_id", "status", "fired", "skipped_stale"],
           "properties": {"alert_id": {"type": "string"}, "status": {"type": "string", "enum": ["fired", "not_triggered", "skipped_stale", "not_in_feed", "expired"]},
                          "new": {"type": "boolean"}, "fired": {"type": "array", "items": _ITEM}, "skipped_stale": {"type": "array", "items": _ITEM},
                          "threshold_usd": _NUM, "direction": _STR, "expires_at": _STR}}
_ERR = {"type": "object", "required": ["code", "message"], "properties": {"code": {"type": "string"}, "message": {"type": "string"}}}


def _out(props, req):
    return {"type": "object", "required": ["ok", *req], "additionalProperties": True,
            "properties": {"ok": {"type": "boolean"}, "error": _ERR, **props}}


_TOKEN = {"type": "string"}
TOOL_SPECS = [
    ("create_alert",
     "Hosted only, free, opt-in, poll-only (no webhook, no email, no account). Create a price alert on a stable rate_id "
     "(from compare_gpu_prices) OR a gpu filter (all words must match the model; optional vendor, vram_gb, tiers) with "
     "threshold_usd (USD per GPU-hour) and direction 'below' (default, at or below) or 'above' (at or above). Returns an "
     "alert_token ONCE when you do not pass one (store it; only its hash is kept) and expires_at (30 days; check_alerts "
     "renew=true extends it). Poll check_alerts after the feed refresh (daily ~10:23 UTC). " + STALE_NOTE,
     {"rate_id": {"type": "string"}, "gpu": {"type": "string"}, "vendor": {"type": "string"}, "vram_gb": {"type": "integer"},
      "tiers": {"type": "array", "items": {"type": "string"}}, "threshold_usd": {"type": "number"},
      "direction": {"type": "string", "enum": list(DIRECTIONS)}, "alert_token": _TOKEN}, ["threshold_usd"],
     _out({"alert": _ALERT, "alert_token": {"type": "string"}, "shown_once": {"type": "string"}, "evaluation": _RESULT,
           "limits": {"type": "object"}, "stale_rule": {"type": "string"}}, ["alert", "limits", "stale_rule"])),
    ("check_alerts",
     "Hosted only. Evaluate every alert on your alert_token against the current feed. Each alert is fired, not_triggered, "
     "skipped_stale, not_in_feed or expired; `new` is false when the same price was already reported. renew=true first "
     "extends every unexpired alert to 30 days from now. " + STALE_NOTE,
     {"alert_token": _TOKEN, "renew": {"type": "boolean", "default": False}}, [],
     _out({"alerts": {"type": "array", "items": _RESULT}, "fired_count": {"type": "integer"}, "skipped_stale_count": {"type": "integer"},
           "renewed": {"type": "integer"}, "feed_updated_at": _STR, "prices_verified_through": _STR, "stale_rule": {"type": "string"}},
          ["alerts", "fired_count", "skipped_stale_count", "stale_rule"])),
    ("delete_alert", "Hosted only. Delete one alert by alert_id (needs its alert_token).",
     {"alert_id": {"type": "string"}, "alert_token": _TOKEN}, ["alert_id"],
     _out({"deleted": {"type": "string"}}, ["deleted"])),
]
NAMES = {t[0] for t in TOOL_SPECS}
SCHEMAS = {t[0]: t[4] for t in TOOL_SPECS}


def tool_list():
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p, **({"required": r} if r else {})},
             "outputSchema": o, "annotations": {"readOnlyHint": False, "openWorldHint": True}}
            for n, d, p, r, o in TOOL_SPECS]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else None
    except ValueError:
        return None


# ---- tokens --------------------------------------------------------------------------------------------------------
def new_token() -> tuple[str, str]:
    token_id = secrets.token_hex(6)
    return token_id, f"lwa_{token_id}_{secrets.token_urlsafe(24)}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_from(args, bearer):
    t = args.get("alert_token")
    if t in (None, "") and isinstance(bearer, str) and bearer.startswith("lwa_"):
        t = bearer
    return str(t).strip() if t not in (None, "") else None


async def _auth(db, token):
    m = TOKEN_RE.match(token or "")
    if not m:
        raise W.WatchError("unauthorized", "missing or malformed alert_token (create_alert returns one)")
    row = await S._first(db, "SELECT token_hash FROM price_alert_tokens WHERE token_id = ?", m.group(1))
    if not row or not hmac.compare_digest(token_hash(token), row["token_hash"]):
        raise W.WatchError("unauthorized", "unknown alert_token")
    return m.group(1)


async def _limit(db, bucket, scope, cap, msg):
    row = await S._first(db, "SELECT n FROM price_alert_counters WHERE bucket = ? AND scope = ?", bucket, scope)
    if row and row["n"] >= cap:
        raise W.WatchError("rate_limited", msg)
    await S._run(db, "INSERT INTO price_alert_counters(bucket, scope, n) VALUES (?, ?, 1) "
                     "ON CONFLICT(bucket, scope) DO UPDATE SET n = n + 1", bucket, scope)


def _ip_hash(master, ip, day) -> str:
    """Keyed, per-day hash of the caller IP for the create cap. The raw IP is never stored; the hash changes daily."""
    return hmac.new(master.encode(), f"alert-ip|{day}|{ip or ''}".encode(), hashlib.sha256).hexdigest()[:16]


# ---- spec + matching (pure) ----------------------------------------------------------------------------------------
def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def normalize_alert(args: dict) -> dict:
    thr = args.get("threshold_usd")
    if isinstance(thr, bool) or not isinstance(thr, (int, float)) or not 0 < thr < 1000:
        raise W.WatchError("invalid_argument", "threshold_usd must be a number between 0 and 1000 (USD per GPU-hour)")
    direction = args.get("direction") or "below"
    if direction not in DIRECTIONS:
        raise W.WatchError("invalid_argument", "direction must be 'below' or 'above'")
    rid, gpu, vendor = args.get("rate_id"), args.get("gpu"), args.get("vendor")
    for k, v, mx in (("rate_id", rid, 20), ("gpu", gpu, 40), ("vendor", vendor, 60)):
        if v is not None and (not isinstance(v, str) or len(v) > mx):
            raise W.WatchError("invalid_argument", f"{k} must be a string of at most {mx} characters")
    if rid:
        if not RATE_ID_RE.match(rid):
            raise W.WatchError("invalid_argument", "rate_id looks like r_ followed by 12 hex characters (from compare_gpu_prices)")
        if gpu or vendor or args.get("vram_gb") is not None or args.get("tiers"):
            raise W.WatchError("invalid_argument", "pass either rate_id or a gpu filter (gpu, vendor, vram_gb, tiers), not both")
        return {"rate_id": rid, "gpu": None, "vendor": None, "vram_gb": None, "tiers": None,
                "threshold_usd": round(float(thr), 6), "direction": direction}
    if not (gpu or "").strip():
        raise W.WatchError("invalid_argument", "pass a rate_id or a gpu filter, e.g. gpu='H100' (optionally vendor, vram_gb, tiers)")
    try:
        c = EL.normalize(gpu=gpu, vram_gb=args.get("vram_gb"), tiers=args.get("tiers"), in_stock="ignore")
    except EL.EligibilityError as e:
        raise W.WatchError("invalid_argument", str(e)) from None
    return {"rate_id": None, "gpu": gpu.strip(), "vendor": (vendor or "").strip() or None, "vram_gb": c.get("vram_gb"),
            "tiers": c.get("tiers"), "threshold_usd": round(float(thr), 6), "direction": direction}


def _constraints(a: dict) -> dict:
    return EL.normalize(gpu=a["gpu"], vram_gb=a.get("vram_gb"),
                        tiers=a.get("tiers") or [t for t in EL.TIER_CLASSES if t != "reserved"], in_stock="ignore")


def _crosses(a: dict, h) -> bool:
    return isinstance(h, (int, float)) and (h <= a["threshold_usd"] if a["direction"] == "below" else h >= a["threshold_usd"])


def _candidates(a: dict, prices: dict, now: datetime):
    """Yield (item, held_reason|None, stale) for every ranked row and held_stale record the alert targets."""
    c = _constraints(a) if not a.get("rate_id") else None

    def hit(rid, vendor, f):
        if a.get("rate_id"):
            return rid == a["rate_id"]
        return EL.check(f, c)["eligible"] and (not a.get("vendor") or _norm(a["vendor"]) == _norm(vendor))

    for r in prices.get("rates") or []:
        rid = rate_id(r)
        f = {"gpu": r.get("gpu"), "vram_gb": r.get("vram_gb"), "tier_class": core_deals.tier_class(r)}
        if not hit(rid, r.get("advertiser"), f):
            continue
        age = data_age.age_fields(r, now)
        av = r.get("availability") if isinstance(r.get("availability"), dict) else {}
        yield ({"rate_id": rid, "vendor": r.get("advertiser"), "gpu": r.get("gpu"), "vram_gb": r.get("vram_gb"), "tier": r.get("tier"),
                "hourly_usd": r.get("hourly_equiv_usd"), "checked_at": r.get("checked_at"), "price_age_hours": age["data_age_hours"],
                "source_url": r.get("source_url"), "in_stock": av.get("in_stock") if av.get("in_stock") in (True, False) else None},
               None, bool(age["degraded"]))
    for h in prices.get("held_stale") or []:
        for rec in h.get("records") or []:
            rid = rate_id({**rec, "vendor": h.get("vendor")})
            f = {"gpu": rec.get("gpu"), "vram_gb": rec.get("vram_gb"), "tier_class": core_deals.tier_class({"tier": rec.get("tier")})}
            if hit(rid, h.get("vendor"), f):
                yield ({"rate_id": rid, "vendor": h.get("vendor"), "gpu": rec.get("gpu"), "vram_gb": rec.get("vram_gb"),
                        "tier": rec.get("tier"), "hourly_usd": rec.get("hourly_usd"), "checked_at": h.get("checked_at"),
                        "price_age_hours": None, "source_url": h.get("source_url"), "in_stock": None},
                       str(h.get("reason") or "held_stale"), True)


def evaluate_alert(a: dict, prices: dict, now: datetime) -> dict:
    """Pure: one alert row vs the feed. Never fires on held_stale or degraded (> 48 h or undated) rows."""
    exp = _parse(a.get("expires_at"))
    base = {"alert_id": a["alert_id"], "threshold_usd": a["threshold_usd"], "direction": a["direction"], "expires_at": a.get("expires_at"),
            "fired": [], "skipped_stale": [], "new": False}
    if exp is not None and exp <= now:
        return {**base, "status": "expired"}
    fired, stale, fresh = [], [], 0
    for item, held, is_stale in _candidates(a, prices, now):
        if is_stale:
            stale.append({**item, "hold": "held_stale" if held else f"older_than_{STALE_HOURS}h", "reason": held,
                          "would_have_crossed": _crosses(a, item["hourly_usd"])})
        else:
            fresh += 1
            if _crosses(a, item["hourly_usd"]):
                fired.append(item)
    fired.sort(key=lambda x: x["hourly_usd"], reverse=a["direction"] == "above")
    stale.sort(key=lambda x: (not x["would_have_crossed"], x["hourly_usd"] if isinstance(x["hourly_usd"], (int, float)) else 0))
    status = "fired" if fired else "not_triggered" if fresh else "skipped_stale" if stale else "not_in_feed"
    return {**base, "status": status, "fired": fired[:MAX_ITEMS], "skipped_stale": stale[:MAX_ITEMS]}


def known_rate_ids(prices: dict) -> set:
    ids = {rate_id(r) for r in prices.get("rates") or []}
    for h in prices.get("held_stale") or []:
        ids |= {rate_id({**rec, "vendor": h.get("vendor")}) for rec in h.get("records") or []}
    return ids


def _public(a: dict) -> dict:
    tiers = a.get("tiers")
    if isinstance(tiers, str):
        tiers = [t for t in tiers.split(",") if t] or None
    return {"alert_id": a["alert_id"], "rate_id": a.get("rate_id"), "gpu": a.get("gpu"), "vendor": a.get("vendor"),
            "vram_gb": a.get("vram_gb"), "tiers": tiers, "threshold_usd": a["threshold_usd"], "direction": a["direction"],
            "created_at": a.get("created_at"), "expires_at": a["expires_at"]}


def _row_spec(a: dict) -> dict:
    """D1 row -> matcher spec (tiers stored as a comma list)."""
    return {**a, "tiers": [t for t in str(a.get("tiers") or "").split(",") if t] or None}


# ---- D1 glue -------------------------------------------------------------------------------------------------------
async def _run_tool(name, args, env, bearer, prices_fn, ip):
    db, now = env.WATCH_DB, _now()
    if len(json.dumps(args, default=str)) > MAX_ARGS_BYTES:
        raise W.WatchError("invalid_argument", f"arguments larger than {MAX_ARGS_BYTES} bytes")
    token = _token_from(args, bearer)
    if name == "create_alert":
        spec = normalize_alert(args)
        master = getattr(env, "WATCH_SIGNING_MASTER", None)
        if not master:
            raise W.WatchError("alerts_unavailable", "alerts are not configured on this deployment")
        token_id = await _auth(db, token) if token else None
        prices = await prices_fn()
        if spec["rate_id"] and spec["rate_id"] not in known_rate_ids(prices):
            raise W.WatchError("not_found", "unknown rate_id; take one from compare_gpu_prices (results[].rate_id)")
        if spec["gpu"]:
            W.check_known_gpu(prices, {"gpu": spec["gpu"], "vram_gb": spec["vram_gb"]})
        day = now.date().isoformat()
        await S._run(db, "DELETE FROM price_alert_counters WHERE bucket < ?", day)
        await _limit(db, day, "create:all", MAX_CREATES_PER_DAY, "daily alert-creation limit reached; try again tomorrow (UTC)")
        await _limit(db, day, "create:ip:" + _ip_hash(master, ip, day), MAX_CREATES_PER_IP_PER_DAY,
                     "daily alert-creation limit for this caller reached; try again tomorrow (UTC)")
        minted = None
        if token_id is None:
            token_id, minted = new_token()
            await S._run(db, "INSERT INTO price_alert_tokens(token_id, token_hash, created_at) VALUES (?, ?, ?)",
                         token_id, token_hash(minted), _iso(now))
        else:
            have = await S._first(db, "SELECT COUNT(*) AS n FROM price_alerts WHERE token_id = ? AND expires_at > ?", token_id, _iso(now))
            if have and have["n"] >= MAX_ALERTS_PER_TOKEN:
                raise W.WatchError("rate_limited", f"at most {MAX_ALERTS_PER_TOKEN} active alerts per alert_token")
        row = {"alert_id": "al_" + secrets.token_hex(6), **spec, "created_at": _iso(now), "expires_at": _iso(now + timedelta(days=TTL_DAYS))}
        await S._run(db, "INSERT INTO price_alerts(alert_id, token_id, rate_id, gpu, vendor, vram_gb, tiers, threshold_usd, direction, "
                         "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     row["alert_id"], token_id, spec["rate_id"], spec["gpu"], spec["vendor"], spec["vram_gb"],
                     ",".join(spec["tiers"] or []) or None, spec["threshold_usd"], spec["direction"], row["created_at"], row["expires_at"])
        out = {"ok": True, "alert": _public(row), "evaluation": evaluate_alert(_row_spec({**row, "tiers": ",".join(spec["tiers"] or [])}), prices, now),
               "limits": {"alerts_per_token": MAX_ALERTS_PER_TOKEN, "ttl_days": TTL_DAYS,
                          "checks_per_token_per_hour": MAX_CHECKS_PER_TOKEN_PER_HOUR},
               "stale_rule": STALE_NOTE}
        if minted:
            out["alert_token"] = minted
            out["shown_once"] = "Store alert_token now; only its hash is kept, so it cannot be shown again."
        return out
    token_id = await _auth(db, token)
    if name == "delete_alert":
        aid = str(args.get("alert_id") or "")
        if not re.fullmatch(r"al_[0-9a-f]{12}", aid) or not await S._first(db, "SELECT alert_id FROM price_alerts WHERE alert_id = ? AND token_id = ?", aid, token_id):
            raise W.WatchError("not_found", "no such alert_id for this alert_token")
        await S._run(db, "DELETE FROM price_alerts WHERE alert_id = ? AND token_id = ?", aid, token_id)
        return {"ok": True, "deleted": aid}
    # check_alerts
    hour, day = now.strftime("%Y-%m-%dT%H"), now.date().isoformat()
    await _limit(db, hour, "check:" + token_id, MAX_CHECKS_PER_TOKEN_PER_HOUR, "hourly check limit for this alert_token reached")
    await _limit(db, day, "check:" + token_id, MAX_CHECKS_PER_TOKEN_PER_DAY, "daily check limit for this alert_token reached; try again tomorrow (UTC)")
    await S._run(db, "DELETE FROM price_alerts WHERE token_id = ? AND expires_at < ?", token_id, _iso(now - timedelta(days=EXPIRED_KEEP_DAYS)))
    renewed = 0
    if args.get("renew") is True:
        renewed = (await S._first(db, "SELECT COUNT(*) AS n FROM price_alerts WHERE token_id = ? AND expires_at > ?", token_id, _iso(now)) or {}).get("n", 0)
        await S._run(db, "UPDATE price_alerts SET expires_at = ? WHERE token_id = ? AND expires_at > ?",
                     _iso(now + timedelta(days=TTL_DAYS)), token_id, _iso(now))
    rows = await S._all(db, "SELECT * FROM price_alerts WHERE token_id = ? ORDER BY created_at", token_id)
    prices = await prices_fn()
    results = []
    for a in rows:
        res = evaluate_alert(_row_spec(a), prices, now)
        if res["status"] == "fired":
            best = res["fired"][0]["hourly_usd"]
            res["new"] = a.get("last_fired_price") != best
            if res["new"]:
                await S._run(db, "UPDATE price_alerts SET last_fired_at = ?, last_fired_price = ? WHERE alert_id = ?", _iso(now), best, a["alert_id"])
        if res["status"] != "expired":
            await S._run(db, "UPDATE price_alerts SET last_evaluated_at = ? WHERE alert_id = ?", _iso(now), a["alert_id"])
        results.append(res)
    return {"ok": True, "alerts": results, "fired_count": sum(r["status"] == "fired" for r in results),
            "skipped_stale_count": sum(len(r["skipped_stale"]) for r in results), "renewed": int(renewed or 0),
            "feed_updated_at": prices.get("feed_updated_at"), "prices_verified_through": prices.get("prices_verified_through"),
            "stale_rule": STALE_NOTE}


async def call(name, args, env, bearer, prices_fn, ip=""):
    """Run one hosted alert tool. prices_fn: async () -> the gpu-prices.json document. Errors use the watch envelope."""
    try:
        return await _run_tool(name, args if isinstance(args, dict) else {}, env, bearer, prices_fn, ip)
    except W.WatchError as e:
        return {"ok": False, "error": {"code": e.code, "message": e.message}}
    except Exception as e:  # noqa: BLE001
        if "no such table" in str(e).lower():  # migration 0008 not applied yet (Mart's deploy flow)
            return {"ok": False, "error": {"code": "alerts_unavailable", "message": "alerts storage is not set up on this deployment yet"}}
        raise
