"""D1 + webhook glue for hosted price watches (see watch.py). Free-plan sized: few queries per invocation,
multi-row statements, <= 40 webhook POSTs per cron run. `fetch_fn` is injected so tests run in CPython."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import watch as W

MAX_BIND = 90  # D1 caps bound parameters per statement at 100

TOOL_SPECS = [
    ("create_watch_key",
     "Hosted only, free, opt-in. Register a webhook for GPU price alerts and get an api_key plus a webhook signing "
     "secret (both shown ONCE; store them). webhook_url must be public https. email is optional contact only (no mail "
     "is sent). No payment. Stored: a hash of the key, the webhook URL, optional email, your watches and per-key counts.",
     {"webhook_url": {"type": "string"}, "email": {"type": "string"}}, ["webhook_url"]),
    ("watch_price",
     "Hosted only. Alert your webhook (signed POST) after the daily refresh when a tracked rate for `gpu` crosses at "
     "or below max_hourly_usd, or a change of a watched kind (down/up/new; default down) lands at or below it. "
     "region: optional code from availability.available_regions (rates that publish no region never match). "
     "Each event is delivered at most once per watch (dedupe on event_id). Pass api_key or an Authorization: Bearer header.",
     {"gpu": {"type": "string"}, "max_hourly_usd": {"type": "number"}, "region": {"type": "string"},
      "kinds": {"type": "array", "items": {"type": "string", "enum": list(W.KINDS)}}, "api_key": {"type": "string"}},
     ["gpu", "max_hourly_usd"]),
    ("list_watches", "Hosted only. Your watches and per-key alert counts.", {"api_key": {"type": "string"}}, []),
    ("delete_watch", "Hosted only. Delete one of your watches by watch_id.",
     {"watch_id": {"type": "string"}, "api_key": {"type": "string"}}, ["watch_id"]),
]
NAMES = {n for n, *_ in TOOL_SPECS}
OUTPUT_SCHEMA = {"type": "object", "required": ["ok"], "additionalProperties": True,
                 "properties": {"ok": {"type": "boolean"},
                                "error": {"type": "object", "required": ["code", "message"],
                                          "properties": {"code": {"type": "string"}, "message": {"type": "string"}}}}}


def tool_list():
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p, **({"required": r} if r else {})},
             "outputSchema": OUTPUT_SCHEMA, "annotations": {"readOnlyHint": n == "list_watches", "openWorldHint": True}}
            for n, d, p, r in TOOL_SPECS]


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(res):
    rows = getattr(res, "results", res) or []
    if hasattr(rows, "to_py"):
        rows = rows.to_py()
    return [r if isinstance(r, dict) else (r.to_py() if hasattr(r, "to_py") else dict(r)) for r in rows]


def _stmt(db, sql, a):
    """D1 rejects a Python None bound from Pyodide (it arrives as JS undefined): inline NULL for None args."""
    if any(x is None for x in a):
        parts, out = sql.split("?"), []
        assert len(parts) == len(a) + 1, "placeholder count"
        sql, keep = parts[0], []
        for x, rest in zip(a, parts[1:]):
            sql += ("NULL" if x is None else "?") + rest
            if x is not None:
                keep.append(x)
        a = keep
    st = db.prepare(sql)
    return st.bind(*a) if a else st


async def _all(db, sql, *a):
    return _rows(await _stmt(db, sql, a).all())


async def _first(db, sql, *a):
    r = _rows(await _stmt(db, sql, a).all())
    return r[0] if r else None


async def _run(db, sql, *a):
    return await _stmt(db, sql, a).run()


async def _host_is_public(url, fetch_fn) -> bool:
    """Resolve the webhook host over DNS-over-HTTPS (A + AAAA) and require every address to be public. Literal IPs
    were already checked by W.validate_webhook_url. Fails closed: no fetch, a DoH error or no answers -> False."""
    host = (W.urlsplit(url).hostname or "").lower().rstrip(".")
    if W._ip_literal(host) is not None:
        return True
    if fetch_fn is None:
        return False
    docs = []
    try:
        for t in ("A", "AAAA"):
            r = await fetch_fn(f"{W.DOH_URL}?name={host}&type={t}", method="GET", headers={"accept": "application/dns-json"})
            if not 200 <= int(r.status) < 300:
                return False
            docs.append(json.loads(await r.text()))
    except Exception:
        return False
    return W.resolved_ips_public(docs)


async def _bump(db, key_id, metric, n=1):
    await _run(db, "INSERT INTO watch_key_counters(key_id, day, metric, n) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(key_id, day, metric) DO UPDATE SET n = n + excluded.n", key_id, _today(), metric, n)


async def _auth(db, args, bearer):
    key = args.get("api_key") or bearer
    key_id = W.parse_key(key)
    row = await _first(db, "SELECT k.key_hash, k.disabled, COALESCE(c.n, 0) AS calls FROM watch_keys k "
                           "LEFT JOIN watch_key_counters c ON c.key_id = k.key_id AND c.day = ? AND c.metric = 'calls' "
                           "WHERE k.key_id = ?", _today(), key_id)
    if not row or not W.check_key(key, row["key_hash"]) or row["disabled"]:
        raise W.WatchError("unauthorized", "unknown or disabled api_key")
    if row["calls"] >= W.MAX_CALLS_PER_KEY_PER_DAY:
        raise W.WatchError("rate_limited", "daily call limit for this key reached; try again tomorrow (UTC)")
    await _bump(db, key_id, "calls")
    return key_id


async def call(name, args, env, bearer, feeds, fetch_fn=None):
    """Run one hosted watch tool. feeds: async () -> (prices_doc, history_doc, latest_doc)."""
    db = env.WATCH_DB
    try:
        if name == "create_watch_key":
            url = W.validate_webhook_url(args.get("webhook_url"))
            email = W.validate_email(args.get("email"))
            if not await _host_is_public(url, fetch_fn):
                raise W.WatchError("invalid_argument", "webhook_url host must resolve only to public IPs (private, loopback, link-local and reserved addresses are blocked)")
            master = getattr(env, "WATCH_SIGNING_MASTER", None)
            n = await _first(db, "SELECT n FROM watch_metrics WHERE day = ? AND metric = 'signups'", _today())
            if n and n["n"] >= W.MAX_SIGNUPS_PER_DAY:
                raise W.WatchError("rate_limited", "signup limit for today reached; try again tomorrow (UTC)")
            key_id, key = W.new_key()
            secret = W.signing_secret(master, key_id)
            await _run(db, "INSERT INTO watch_keys(key_id, key_hash, webhook_url, email, created_at, disabled) VALUES (?, ?, ?, ?, ?, 0)",
                       key_id, W.key_hash(key), url, email, _now_iso())
            await _run(db, "INSERT INTO watch_metrics(day, metric, n) VALUES (?, 'signups', 1) "
                           "ON CONFLICT(day, metric) DO UPDATE SET n = n + 1", _today())
            return {"ok": True, "key_id": key_id, "api_key": key, "webhook_signing_secret": secret,
                    "shown_once": "Store api_key and webhook_signing_secret now; they cannot be shown again.",
                    "signature": "Header X-Lantern-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, '<t>.<raw body>')>. "
                                 "Reject if t is more than 5 minutes old. X-Lantern-Event-Id is the dedupe key.",
                    "next": "call watch_price(gpu, max_hourly_usd, api_key=...)"}
        key_id = await _auth(db, args, bearer)
        if name == "watch_price":
            spec = W.normalize_watch(args.get("gpu"), args.get("max_hourly_usd"), args.get("region"), args.get("kinds"))
            have = await _first(db, "SELECT COUNT(*) AS n FROM watches WHERE key_id = ?", key_id)
            if have and have["n"] >= W.MAX_WATCHES_PER_KEY:
                raise W.WatchError("rate_limited", f"at most {W.MAX_WATCHES_PER_KEY} watches per key")
            prices, history, latest = await feeds()
            wid = W.new_watch_id()
            base_seq = max([int(c.get("seq") or 0) for c in (history or {}).get("changes") or []] or [0])
            base_day = (latest or {}).get("date") or _today()
            await _run(db, "INSERT INTO watches(watch_id, key_id, gpu, region, max_hourly_usd, kinds, baseline_seq, baseline_day, created_at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", wid, key_id, spec["gpu"], spec["region"],
                       spec["max_hourly_usd"], ",".join(spec["kinds"]), base_seq, base_day, _now_iso())
            return {"ok": True, "watch": {"watch_id": wid, **spec},
                    "current_matches": W.current_matches(prices, spec),
                    "note": "current_matches are already at or below your max and are NOT alerted; alerts cover changes "
                            "published after now (checked after the daily refresh, ~10:23 UTC)."}
        if name == "list_watches":
            ws = await _all(db, "SELECT watch_id, gpu, region, max_hourly_usd, kinds, created_at FROM watches WHERE key_id = ? ORDER BY created_at", key_id)
            for w in ws:
                w["kinds"] = (w.get("kinds") or "").split(",")
            sent = await _first(db, "SELECT COALESCE(SUM(n), 0) AS n FROM watch_key_counters WHERE key_id = ? AND metric = 'alerts'", key_id)
            return {"ok": True, "count": len(ws), "watches": ws, "alerts_delivered": (sent or {}).get("n", 0),
                    "limits": {"watches_per_key": W.MAX_WATCHES_PER_KEY, "alerts_per_key_per_day": W.MAX_ALERTS_PER_KEY_PER_DAY}}
        if name == "delete_watch":
            wid = str(args.get("watch_id") or "")
            row = await _first(db, "SELECT watch_id FROM watches WHERE watch_id = ? AND key_id = ?", wid, key_id)
            if not row:
                raise W.WatchError("not_found", "no such watch for this key")
            await _run(db, "DELETE FROM watches WHERE watch_id = ? AND key_id = ?", wid, key_id)
            await _run(db, "DELETE FROM watch_deliveries WHERE watch_id = ?", wid)
            return {"ok": True, "deleted": wid}
        raise W.WatchError("invalid_argument", f"unknown tool {name}")
    except W.WatchError as e:
        return {"ok": False, "error": {"code": e.code, "message": e.message}}


async def run_cron(env, feeds, fetch_fn, now=None) -> dict:
    """After the daily refresh: send signed alerts for new matching events, at most once per (watch, event)."""
    db = env.WATCH_DB
    master = getattr(env, "WATCH_SIGNING_MASTER", None)
    if not master:
        return {"sent": 0, "skipped": "WATCH_SIGNING_MASTER not set"}
    prices, history, latest = await feeds()
    return await deliver(env, W.candidate_events(latest, history, _today()), W.rate_regions(prices), fetch_fn, now)


async def deliver(env, events, regions, fetch_fn, now=None) -> dict:
    """Match, sign and send for a precomputed event list (pushed by the daily GitHub Actions build, so the Worker never
    parses the big feeds on this path). Same dedupe, caps, https-only and public-IP (after DNS) checks as the cron."""
    db = env.WATCH_DB
    master = getattr(env, "WATCH_SIGNING_MASTER", None)
    if not master:
        return {"sent": 0, "skipped": "WATCH_SIGNING_MASTER not set"}
    today = _today()
    watches = await _all(db, "SELECT w.watch_id, w.key_id, w.gpu, w.region, w.max_hourly_usd, w.kinds, w.baseline_seq, "
                             "w.baseline_day, k.webhook_url FROM watches w JOIN watch_keys k ON k.key_id = w.key_id WHERE k.disabled = 0")
    for w in watches:
        w["kinds"] = (w.get("kinds") or "down").split(",")
    if not watches or not events:
        return {"sent": 0, "events": len(events), "watches": len(watches)}
    ids = list({e["event_id"] for e in events})
    delivered = set()
    for i in range(0, len(ids), MAX_BIND):
        chunk = ids[i:i + MAX_BIND]
        for r in await _all(db, f"SELECT watch_id, event_id FROM watch_deliveries WHERE event_id IN ({','.join('?' * len(chunk))})", *chunk):
            delivered.add((r["watch_id"], r["event_id"]))
    today_alerts = {r["key_id"]: r["n"] for r in await _all(db, "SELECT key_id, n FROM watch_key_counters WHERE day = ? AND metric = 'alerts'", today)}
    plan = W.plan_deliveries(watches, events, delivered, regions, today_alerts)
    ok_rows, per_key, failed, blocked = [], {}, 0, 0
    host_ok, budget = {}, W.SUBREQUEST_BUDGET
    for w, ev, reason in plan:
        host = (W.urlsplit(w["webhook_url"]).hostname or "").lower()
        try:
            W.validate_webhook_url(w["webhook_url"])  # https-only + literal/suffix checks again at send time
        except W.WatchError:
            blocked += 1
            continue
        if host not in host_ok:  # re-resolve at send time (DNS can change after signup); 2 subrequests per host
            if budget < 3:
                break
            budget -= 2
            host_ok[host] = await _host_is_public(w["webhook_url"], fetch_fn)
        if not host_ok[host]:
            blocked += 1
            continue
        if budget < 1:
            break
        budget -= 1
        body = W.dumps(W.payload(w, ev, reason, _now_iso()))
        ts = int(now if now is not None else time.time())
        headers = {"content-type": "application/json", "user-agent": "LanternWorks-PriceWatch/1",
                   "x-lantern-event-id": ev["event_id"], "x-lantern-watch-id": w["watch_id"],
                   "x-lantern-signature": W.sign(W.signing_secret(master, w["key_id"]), ts, body)}
        try:
            r = await fetch_fn(w["webhook_url"], method="POST", headers=headers, body=body, redirect="manual")
            good = 200 <= int(r.status) < 300
        except Exception:
            good = False
        if good:
            ok_rows.append((w["watch_id"], ev["event_id"], today))
            per_key[w["key_id"]] = per_key.get(w["key_id"], 0) + 1
        else:
            failed += 1
    for i in range(0, len(ok_rows), MAX_BIND // 3):
        chunk = ok_rows[i:i + MAX_BIND // 3]
        await _run(db, "INSERT OR IGNORE INTO watch_deliveries(watch_id, event_id, day) VALUES " + ",".join(["(?, ?, ?)"] * len(chunk)),
                   *[x for row in chunk for x in row])
    items = list(per_key.items())
    for i in range(0, len(items), MAX_BIND // 4):
        chunk = items[i:i + MAX_BIND // 4]
        await _run(db, "INSERT INTO watch_key_counters(key_id, day, metric, n) VALUES " + ",".join(["(?, ?, 'alerts', ?)"] * len(chunk)) +
                   " ON CONFLICT(key_id, day, metric) DO UPDATE SET n = n + excluded.n", *[x for k, n in chunk for x in (k, today, n)])
    if ok_rows or failed:
        await _run(db, "INSERT INTO watch_metrics(day, metric, n) VALUES (?, 'alerts_delivered', ?), (?, 'alerts_failed', ?) "
                       "ON CONFLICT(day, metric) DO UPDATE SET n = n + excluded.n", today, len(ok_rows), today, failed)
    return {"sent": len(ok_rows), "failed": failed, "blocked_private": blocked, "planned": len(plan), "events": len(events), "watches": len(watches)}


async def stats(env) -> dict:
    db = env.WATCH_DB
    try:
        active = await _first(db, "SELECT COUNT(*) AS n FROM watches w JOIN watch_keys k ON k.key_id = w.key_id WHERE k.disabled = 0")
        rows = await _all(db, "SELECT day, metric, n FROM watch_metrics WHERE metric = 'alerts_delivered' ORDER BY day DESC LIMIT 90")
    except Exception:
        return {"active_watches": None, "alerts_delivered_total": None, "alerts_delivered_by_day": []}
    return {"active_watches": (active or {}).get("n", 0), "alerts_delivered_total": sum(r["n"] for r in rows),
            "alerts_delivered_by_day": [{"day": r["day"], "n": r["n"]} for r in rows]}
