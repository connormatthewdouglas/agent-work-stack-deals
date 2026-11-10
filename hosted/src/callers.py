"""Anonymized distinct-caller counting for the hosted worker (Frosty approved 2026-11-10).

Per UTC day, a random salt is created in D1 (caller_salts) on first use and deleted once the day is over, so hashes
from different days cannot be linked. Each counted request stores only sha256(salt | ip | user-agent) beside the
coarse buckets the T51 counters already use. The raw IP and user agent are never stored, logged or returned, and
neither is the salt. House traffic (src_class=house, or a house ref tag) is not counted at all. No secret is needed.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

RETENTION_DAYS = 120  # same as hits
HOUSE_REF_RE = re.compile(r"^(ci|qa|test|smoke|house-[a-z0-9_-]*|t\d+(-[a-z0-9_-]*)?)$")
_salt = {}  # isolate cache: {day: salt}; holds at most today's salt


def today():
    return datetime.now(timezone.utc).date().isoformat()


def is_house(ref, src_class):
    return src_class == "house" or bool(HOUSE_REF_RE.match(ref or ""))


def caller_hash(salt, ip, ua):
    return hashlib.sha256(f"{salt}\n{ip or ''}\n{ua or ''}".encode()).hexdigest()


async def _day_salt(db, day):
    if day in _salt:
        return _salt[day]
    await db.prepare("DELETE FROM caller_salts WHERE day < ?").bind(day).run()  # yesterday's salt is gone for good
    await db.prepare("INSERT OR IGNORE INTO caller_salts(day, salt) VALUES (?, ?)").bind(day, secrets.token_hex(32)).run()
    rows = (await db.prepare("SELECT salt FROM caller_salts WHERE day = ?").bind(day).all()).results
    salt = rows[0]["salt"] if isinstance(rows[0], dict) else rows[0].salt
    _salt.clear()
    _salt[day] = salt
    return salt


async def record(db, kind, ref, ua_class, src_class, ip, ua, day=None):
    """Count one request. Never raises; does nothing for house traffic or before the migration is applied."""
    if is_house(ref, src_class):
        return
    day = day or today()
    try:
        h = caller_hash(await _day_salt(db, day), ip, ua)
        await db.prepare("INSERT OR IGNORE INTO callers(day, kind, ref, ua_class, src_class, h) VALUES (?, ?, ?, ?, ?, ?)"
                         ).bind(day, kind, ref, ua_class, src_class, h).run()
    except Exception:
        pass  # counting never breaks a request


def _get(r, k):
    return r[k] if isinstance(r, dict) else getattr(r, k)


async def stats(db, day=None):
    """Daily distinct-caller counts (no hashes, no salt). Empty lists before the migration is applied."""
    out = {"callers_daily": [], "callers": []}
    try:
        cut = (datetime.fromisoformat(day or today()).date() - timedelta(days=RETENTION_DAYS)).isoformat()
        await db.prepare("DELETE FROM callers WHERE day < ?").bind(cut).run()
        await db.prepare("DELETE FROM caller_salts WHERE day < ?").bind(day or today()).run()
        rows = (await db.prepare("SELECT day, COUNT(DISTINCT h) AS c FROM callers GROUP BY day ORDER BY day DESC LIMIT 400").all()).results
        out["callers_daily"] = [{"day": _get(r, "day"), "distinct_callers": _get(r, "c")} for r in rows]
        rows = (await db.prepare("SELECT day, kind, ref, ua_class, src_class, COUNT(DISTINCT h) AS c FROM callers "
                                 "GROUP BY day, kind, ref, ua_class, src_class ORDER BY day DESC, kind, ref, ua_class, src_class LIMIT 5000").all()).results
        out["callers"] = [{"day": _get(r, "day"), "kind": _get(r, "kind"), "ref": _get(r, "ref"), "ua_class": _get(r, "ua_class"),
                           "src_class": _get(r, "src_class"), "distinct_callers": _get(r, "c")} for r in rows]
    except Exception:
        pass
    return out
