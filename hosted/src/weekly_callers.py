"""Privacy-safe weekly repeat-caller IDs for the hosted MCP worker (Frosty approved via Bjorn).

On the MCP initialize handshake, if CALLER_ID_SECRET is set, store only (iso_week, hash, days_seen):

    id = HMAC-SHA256(key = secret + ISO week, msg = clientInfo.name | clientInfo.version | network prefix)

truncated to 16 hex characters. The prefix is IPv4 /24 or IPv6 /48 from CF-Connecting-IP.
The raw IP, the prefix and the client name are never stored or logged. A missing secret is a
no-op and never fails the request. House, CI, known bots, GitHub Actions, and MCP Registry
health checks are excluded using the same classification as the existing stats counters.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from datetime import datetime, timedelta, timezone

from callers import HOUSE_REF_RE, is_house

SECRET = "CALLER_ID_SECRET"
ID_LEN = 16
RETENTION_WEEKS = 18  # ~126 days, in line with the 120-day hits/callers window
REGISTRY_REF = "mcp-registry"
REGISTRY_NAME_RE = re.compile(r"mcp[\s_-]*registry", re.I)


def iso_week(now=None) -> str:
    d = (now or datetime.now(timezone.utc)).date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def network_prefix(ip):
    raw = (ip or "").strip()
    if not raw:
        return None
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    n = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network((addr, n), strict=False).network_address)


def caller_id(secret, week, name, version, prefix) -> str:
    key = f"{secret}{week}".encode()
    msg = f"{name or ''}|{version or ''}|{prefix or ''}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:ID_LEN]


def excluded(ref, ua_class, src_class, client_info=None) -> bool:
    """Reuse house/bot/CI classification; also drop MCP Registry health checks and GitHub Actions."""
    if src_class in ("house", "github-actions") or ua_class in ("house", "ci", "known-bot"):
        return True
    if is_house(ref, src_class):
        return True
    if (ref or "") == REGISTRY_REF or bool(HOUSE_REF_RE.match(ref or "")):
        return True
    name = str((client_info or {}).get("name") or "")
    if REGISTRY_NAME_RE.search(name):
        return True
    return False


def _row(r) -> dict:
    """Plain mutable dict copy. Worker D1 rows can look like dicts but reject item assignment."""
    if hasattr(r, "to_py"):
        r = r.to_py()
    return dict(r)


def _secret(env):
    s = getattr(env, SECRET, None)
    return (str(s) if s is not None else "").strip() or None


def _days(seen: str) -> list[str]:
    return [d for d in (seen or "").split(",") if d]


async def record(env, client_info, ip, ref, ua_class, src_class, now=None):
    """Count one initialize handshake. Never raises; no-op without a secret or before the migration."""
    try:
        secret = _secret(env)
        if not secret:
            return
        if excluded(ref, ua_class, src_class, client_info):
            return
        prefix = network_prefix(ip)
        if prefix is None:
            return
        now = now or datetime.now(timezone.utc)
        week = iso_week(now)
        day = now.date().isoformat()
        info = client_info or {}
        h = caller_id(secret, week, info.get("name"), info.get("version"), prefix)
        db = env.DB
        res = (await db.prepare(
            "SELECT iso_week, h, days_seen FROM weekly_callers WHERE iso_week = ? AND h = ?"
        ).bind(week, h).all()).results
        if res:
            row = _row(res[0])
            days = _days(row.get("days_seen"))
            if day in days:
                return
            days.append(day)
            days.sort()
            await db.prepare(
                "UPDATE weekly_callers SET days_seen = ? WHERE iso_week = ? AND h = ?"
            ).bind(",".join(days), week, h).run()
        else:
            await db.prepare(
                "INSERT INTO weekly_callers(iso_week, h, days_seen) VALUES (?, ?, ?)"
            ).bind(week, h, day).run()
    except Exception:
        pass  # counting never breaks a request


async def stats(db, now=None):
    """Per-ISO-week distinct_callers and callers_3plus_days. Empty before the migration is applied."""
    out = {"weekly_callers": []}
    try:
        now = now or datetime.now(timezone.utc)
        cut = iso_week(now - timedelta(weeks=RETENTION_WEEKS))
        await db.prepare("DELETE FROM weekly_callers WHERE iso_week < ?").bind(cut).run()
        rows = (await db.prepare(
            "SELECT iso_week, COUNT(*) AS distinct_callers, "
            "SUM(CASE WHEN (LENGTH(days_seen) - LENGTH(REPLACE(days_seen, ',', '')) + 1) >= 3 "
            "THEN 1 ELSE 0 END) AS callers_3plus_days "
            "FROM weekly_callers GROUP BY iso_week ORDER BY iso_week DESC LIMIT 52"
        ).all()).results
        out["weekly_callers"] = []
        for r in rows:
            row = _row(r)
            out["weekly_callers"].append({
                "iso_week": row["iso_week"],
                "distinct_callers": int(row["distinct_callers"]),
                "callers_3plus_days": int(row["callers_3plus_days"] or 0),
            })
    except Exception:
        pass
    return out
