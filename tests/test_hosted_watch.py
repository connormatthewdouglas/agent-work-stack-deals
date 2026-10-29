"""Hosted price watches: key/URL safety, signing, matching, never-twice dedupe, caps, and an end-to-end cron on a
sqlite-backed fake D1. The local stdio server must stay keyless (no watch tools)."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hosted" / "src"))

from core import gpu_history as H  # noqa: E402
import watch as W  # noqa: E402
import watch_store as S  # noqa: E402

MASTER = "test-master-not-a-real-secret"


# ---- fake D1 ---------------------------------------------------------------------------------------------------
class _Stmt:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()

    def bind(self, *a):
        self.args = a
        return self

    async def all(self):
        cur = self.db.execute(self.sql, self.args)
        return types.SimpleNamespace(results=[dict(r) for r in cur.fetchall()])

    async def run(self):
        self.db.execute(self.sql, self.args)
        self.db.commit()


class FakeD1:
    def __init__(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        self.c.executescript((ROOT / "hosted" / "watch_schema.sql").read_text())

    def prepare(self, sql):
        return _Stmt(self.c, sql)


def env():
    return types.SimpleNamespace(WATCH_DB=FakeD1(), WATCH_SIGNING_MASTER=MASTER)


def run(c):
    return asyncio.run(c)


# ---- synthetic feeds -------------------------------------------------------------------------------------------
def snap(day, prices):
    return {"date": day, "rows": [
        {"key": H.series_key(v, "H100", "On-demand", 80, 1), "vendor": v, "gpu": "H100", "tier": "On-demand",
         "vram_gb": 80, "gpu_count": 1, "billing_unit": "hourly", "price_usd": p, "hourly_usd": p, "status": "ranked",
         "verified_at": f"{day}T10:00:00+00:00", "source_url": "https://example.com/p"} for v, p in prices.items()]}


def prices_doc(prices, regions=None):
    return {"rates": [{"advertiser": v, "gpu": "H100", "tier": "On-demand", "tier_class": "on_demand", "hourly_equiv_usd": p,
                       "billing_unit": "hourly", "vram_gb": 80, "gpu_count": 1,
                       **({"availability": {"available_regions": regions[v]}} if regions and v in regions else {})}
                      for v, p in prices.items()]}


DAY1 = {"Acme": 2.50, "Bolt": 2.10}
DAY2 = {"Acme": 1.90, "Bolt": 2.05}   # Acme crosses below 2.00; Bolt moves down but stays above


def feeds_for(snaps, prices, latest=None):
    hist = H.build_history(snaps)
    lat = latest or {"date": snaps[-1]["date"], "changes": []}

    async def f():
        return prices, hist, lat
    return f


class Poster:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    async def __call__(self, url, method, headers, body, redirect):
        assert method == "POST" and redirect == "manual"
        self.calls.append((url, headers, body))
        return types.SimpleNamespace(status=self.status)


def signup(e, url="https://hooks.example.com/lw"):
    out = run(S.call("create_watch_key", {"webhook_url": url}, e, None, feeds_for([snap("2026-11-01", DAY1)], prices_doc(DAY1))))
    assert out["ok"], out
    return out


# ---- unit ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url", ["http://hooks.example.com/x", "https://localhost/x", "https://127.0.0.1/x", "https://10.0.0.5/x",
                                 "https://192.168.1.1/x", "https://169.254.169.254/latest", "https://[::1]/x", "https://[::ffff:10.0.0.1]/x",
                                 "https://0x7f000001/x", "https://2130706433/x", "https://printer.local/x", "https://intranet/x",
                                 "https://user:pw@hooks.example.com/x", "https://hooks.example.com:8443/x", "", None, "ftp://x.com"])
def test_webhook_url_blocked(url):
    with pytest.raises(W.WatchError):
        W.validate_webhook_url(url)


def test_webhook_url_ok():
    assert W.validate_webhook_url("https://webhook.site/abc-123") == "https://webhook.site/abc-123"


def test_sign_verify_roundtrip_and_tamper():
    sec = W.signing_secret(MASTER, "abcdef012345")
    assert sec.startswith("whsec_") and sec != W.signing_secret(MASTER, "abcdef012346")
    h = W.sign(sec, 1000, '{"a":1}')
    assert W.verify(sec, h, '{"a":1}', 1000)
    assert not W.verify(sec, h, '{"a":2}', 1000)
    assert not W.verify(sec, h, '{"a":1}', 1000 + 301)
    assert not W.verify("whsec_other", h, '{"a":1}', 1000)


def test_keys_hashed_and_checked():
    kid, key = W.new_key()
    assert W.parse_key(key) == kid and W.check_key(key, W.key_hash(key)) and not W.check_key(key + "x", W.key_hash(key))
    with pytest.raises(W.WatchError):
        W.parse_key("nope")


def test_normalize_watch_validation():
    assert W.normalize_watch("H100", 2)["kinds"] == ["down"]
    for bad in [("", 2), ("H100", -1), ("H100", "x"), ("H100", 2, None, ["sideways"])]:
        with pytest.raises(W.WatchError):
            W.normalize_watch(*bad)


# ---- end to end ------------------------------------------------------------------------------------------------
def test_end_to_end_crossing_fires_once_signed():
    e = env()
    key = signup(e)
    api, secret = key["api_key"], key["webhook_signing_secret"]
    f1 = feeds_for([snap("2026-11-01", DAY1)], prices_doc(DAY1))
    w = run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 2.0}, e, api, f1))  # bearer auth
    assert w["ok"] and w["current_matches"] == []
    stored = e.WATCH_DB.c.execute("SELECT key_hash, webhook_url FROM watch_keys").fetchone()
    assert stored["key_hash"] != api and api not in json.dumps(dict(stored)) and secret not in json.dumps(dict(stored))

    f2 = feeds_for([snap("2026-11-01", DAY1), snap("2026-11-02", DAY2)], prices_doc(DAY2))
    p = Poster()
    r = run(S.run_cron(e, f2, p, now=5000))
    assert r["sent"] == 1 and len(p.calls) == 1
    url, hdr, body = p.calls[0]
    doc = json.loads(body)
    assert doc["reason"] == "crossed_below_max" and doc["change"]["vendor"] == "Acme" and hdr["x-lantern-event-id"] == doc["event_id"]
    assert W.verify(secret, hdr["x-lantern-signature"], body, 5000)

    # second run (retry cron, next day) never re-sends the same event
    p2 = Poster()
    assert run(S.run_cron(e, f2, p2))["sent"] == 0 and p2.calls == []
    lst = run(S.call("list_watches", {"api_key": api}, e, None, f2))
    assert lst["count"] == 1 and lst["alerts_delivered"] == 1
    st = run(S.stats(e))
    assert st["active_watches"] == 1 and st["alerts_delivered_total"] == 1


def test_failed_post_is_retried_then_once():
    e = env()
    api = signup(e)["api_key"]
    f1 = feeds_for([snap("2026-11-01", DAY1)], prices_doc(DAY1))
    run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 2.0, "api_key": api}, e, None, f1))
    f2 = feeds_for([snap("2026-11-01", DAY1), snap("2026-11-02", DAY2)], prices_doc(DAY2))
    assert run(S.run_cron(e, f2, Poster(500)))["sent"] == 0
    ok = Poster()
    assert run(S.run_cron(e, f2, ok))["sent"] == 1
    assert run(S.run_cron(e, f2, Poster()))["sent"] == 0


def test_events_before_watch_creation_not_alerted():
    e = env()
    api = signup(e)["api_key"]
    f2 = feeds_for([snap("2026-11-01", DAY1), snap("2026-11-02", DAY2)], prices_doc(DAY2))
    w = run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 2.0, "api_key": api}, e, None, f2))
    assert [m["vendor"] for m in w["current_matches"]] == ["Acme"]  # reported, not alerted
    assert run(S.run_cron(e, f2, Poster()))["sent"] == 0


def test_kinds_and_region():
    e = env()
    api = signup(e)["api_key"]
    f1 = feeds_for([snap("2026-11-01", DAY1)], prices_doc(DAY1))
    run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 2.2, "api_key": api}, e, None, f1))               # Bolt 2.10->2.05 down under max
    run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 3, "region": "eu", "api_key": api}, e, None, f1))  # only Bolt publishes EU
    run(S.call("watch_price", {"gpu": "A100", "max_hourly_usd": 9, "api_key": api}, e, None, f1))                 # other gpu: nothing
    f2 = feeds_for([snap("2026-11-01", DAY1), snap("2026-11-02", DAY2)], prices_doc(DAY2, {"Bolt": ["EU", "US"]}))
    p = Poster()
    run(S.run_cron(e, f2, p))
    got = sorted((json.loads(b)["watch"]["max_hourly_usd"], json.loads(b)["change"]["vendor"], json.loads(b)["reason"]) for _, _, b in p.calls)
    assert got == [(2.2, "Acme", "crossed_below_max"), (2.2, "Bolt", "price_change_at_or_below_max"), (3.0, "Bolt", "price_change_at_or_below_max")]


def test_auth_and_ownership():
    e = env()
    a, b = signup(e)["api_key"], signup(e)["api_key"]
    f1 = feeds_for([snap("2026-11-01", DAY1)], prices_doc(DAY1))
    wid = run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 2, "api_key": a}, e, None, f1))["watch"]["watch_id"]
    assert run(S.call("list_watches", {}, e, None, f1))["error"]["code"] == "unauthorized"
    assert run(S.call("list_watches", {"api_key": a[:-1] + ("A" if a[-1] != "A" else "B")}, e, None, f1))["error"]["code"] == "unauthorized"
    assert run(S.call("delete_watch", {"watch_id": wid, "api_key": b}, e, None, f1))["error"]["code"] == "not_found"
    assert run(S.call("delete_watch", {"watch_id": wid, "api_key": a}, e, None, f1))["ok"]
    assert run(S.call("list_watches", {"api_key": a}, e, None, f1))["count"] == 0


def test_caps():
    e = env()
    api = signup(e)["api_key"]
    f1 = feeds_for([snap("2026-11-01", DAY1)], prices_doc(DAY1))
    for _ in range(W.MAX_WATCHES_PER_KEY):
        assert run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 2, "api_key": api}, e, None, f1))["ok"]
    assert run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 2, "api_key": api}, e, None, f1))["error"]["code"] == "rate_limited"
    f2 = feeds_for([snap("2026-11-01", DAY1), snap("2026-11-02", DAY2)], prices_doc(DAY2))
    p = Poster()
    assert run(S.run_cron(e, f2, p))["sent"] == 20  # 20 watches x 1 event, under the 40 POST/run budget
    plan = W.plan_deliveries([{"watch_id": f"w{i}", "key_id": "k", "gpu": "H100", "region": None, "max_hourly_usd": 2, "kinds": ["down"],
                               "baseline_seq": 0, "baseline_day": ""} for i in range(10)],
                             [{"event_id": "e1", "seq": 1, "gpu": "H100", "to_hourly_usd": 1, "from_hourly_usd": 3, "direction": "down"}],
                             set(), {}, {"k": W.MAX_ALERTS_PER_KEY_PER_DAY - 3})
    assert len(plan) == 3


def test_signup_rejects_bad_url_and_needs_master():
    e = env()
    f = feeds_for([snap("2026-11-01", DAY1)], prices_doc(DAY1))
    assert run(S.call("create_watch_key", {"webhook_url": "https://10.1.2.3/h"}, e, None, f))["ok"] is False
    e.WATCH_SIGNING_MASTER = None
    assert run(S.call("create_watch_key", {"webhook_url": "https://hooks.example.com/h"}, e, None, f))["error"]["code"] == "watch_unavailable"


def test_tool_names_no_collision_and_stdio_keyless():
    from mcp_server import server
    src = (ROOT / "mcp_server" / "server.py").read_text()
    for n in S.NAMES:
        assert f"def {n}(" not in src and not hasattr(server, n)
    assert "api_key" not in src
    for t in S.tool_list():
        assert t["outputSchema"]["required"] == ["ok"]
