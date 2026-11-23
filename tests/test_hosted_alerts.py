"""F1 poll-only price alerts (Brain #1028): hashed tokens, rate_id / filter alerts, 30-day TTL + renew, limits, and the
stale rule (never fire on held_stale or rows older than 48 h; report skipped_stale). Sqlite-backed fake D1."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hosted" / "src"))

import alerts as A  # noqa: E402
import watch as W  # noqa: E402
import watch_store as S  # noqa: E402
from core.ids import rate_id  # noqa: E402

MASTER = "test-master-not-a-real-secret"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
IP = "203.0.113.7"


class JsNull:  # workerd D1 SQL NULL: falsy, not None, not a str
    def __bool__(self):
        return False


class _Stmt:
    def __init__(self, db, sql, nulls):
        self.db, self.sql, self.args, self.nulls = db, sql, (), nulls

    def bind(self, *a):
        self.args = a
        return self

    async def all(self):
        rows = [dict(r) for r in self.db.execute(self.sql, self.args).fetchall()]
        if self.nulls:
            rows = [{k: (JsNull() if v is None else v) for k, v in r.items()} for r in rows]
        return types.SimpleNamespace(results=rows)

    async def run(self):
        self.db.execute(self.sql, self.args)
        self.db.commit()


class FakeD1:
    def __init__(self, schema=True, nulls=False):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        self.nulls = nulls
        if schema:
            self.c.executescript((ROOT / "hosted" / "migrations" / "0008_price_alerts.sql").read_text())

    def prepare(self, sql):
        return _Stmt(self.c, sql, self.nulls)

    def dump(self) -> str:
        return json.dumps({t: [list(r) for r in self.c.execute(f"SELECT * FROM {t}")]
                           for (t,) in self.c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()})


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    now = {"t": NOW}
    monkeypatch.setattr(A, "_now", lambda: now["t"])
    return now


def run(c):
    return asyncio.run(c)


def env(**kw):
    return types.SimpleNamespace(WATCH_DB=FakeD1(**kw), WATCH_SIGNING_MASTER=MASTER)


def _row(vendor, price, hours_old=1.0, gpu="H100", vram=80, tier="On-demand"):
    ts = (NOW - timedelta(hours=hours_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"advertiser": vendor, "gpu": gpu, "vram_gb": vram, "tier": tier, "tier_class": "on-demand", "hourly_equiv_usd": price,
            "billing_unit": "hourly", "gpu_count": 1, "checked_at": ts, "verified_at": ts, "source_url": f"https://{vendor.lower()}.example/p",
            "availability": {"status": "unknown", "in_stock": None}}


def prices(rates, held=None):
    return {"rates": rates, "held_stale": held or [], "feed_updated_at": "2026-11-23T11:30:00Z", "prices_verified_through": "2026-11-23T11:00:00Z"}


def feed(doc):
    async def f():
        return doc
    return f


def call(name, args, e, doc, token=None, ip=IP):
    return run(A.call(name, args, e, token, feed(doc), ip))


ACME, BOLT = _row("Acme", 1.90), _row("Bolt", 2.40)
DOC = prices([ACME, BOLT])
ACME_ID = rate_id({**ACME, "vendor": "Acme"})


def valid(name, out):
    assert out["ok"] is True, out
    jsonschema.validate(out, A.SCHEMAS[name])


# ---- create / token / hashing ----------------------------------------------------------------------------------------
def test_create_mints_token_once_and_stores_only_a_hash():
    e = env()
    out = call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 2.0}, e, DOC)
    valid("create_alert", out)
    tok = out["alert_token"]
    assert A.TOKEN_RE.match(tok) and out["shown_once"]
    assert out["alert"]["expires_at"] == "2026-12-23T12:00:00Z" and out["alert"]["direction"] == "below"
    assert out["evaluation"]["status"] == "fired" and out["evaluation"]["fired"][0]["rate_id"] == ACME_ID
    dump = e.WATCH_DB.dump()
    assert tok not in dump and A.token_hash(tok) in dump          # hashed, never raw
    assert IP not in dump and "@" not in dump and "http" not in dump  # no raw IP, email or URL stored
    again = call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 1.0}, e, DOC, token=tok)
    valid("create_alert", again)
    assert "alert_token" not in again and again["alert"]["alert_id"] != out["alert"]["alert_id"]


def test_bad_inputs_and_unknown_rate_id():
    e = env()
    for args, code in (({"threshold_usd": 2.0}, "invalid_argument"), ({"gpu": "H100", "threshold_usd": 0}, "invalid_argument"),
                       ({"gpu": "H100", "threshold_usd": 2, "direction": "sideways"}, "invalid_argument"),
                       ({"rate_id": "nope", "threshold_usd": 2}, "invalid_argument"),
                       ({"rate_id": ACME_ID, "gpu": "H100", "threshold_usd": 2}, "invalid_argument"),
                       ({"rate_id": "r_000000000000", "threshold_usd": 2}, "not_found"),
                       ({"gpu": "Nonexistium", "threshold_usd": 2}, "not_found"),
                       ({"gpu": "H100", "threshold_usd": 2, "x": "y" * 5000}, "invalid_argument")):
        out = call("create_alert", args, e, DOC)
        assert out["ok"] is False and out["error"]["code"] == code, (args, out)
    assert call("create_alert", {"gpu": "H100", "threshold_usd": 2}, e, DOC, token="lwa_bad")["error"]["code"] == "unauthorized"


# ---- evaluation -------------------------------------------------------------------------------------------------------
def test_direction_filter_and_dedupe():
    e = env()
    t = call("create_alert", {"gpu": "H100", "vendor": "acme", "threshold_usd": 2.0}, e, DOC)["alert_token"]
    call("create_alert", {"gpu": "H100", "threshold_usd": 2.5, "direction": "above"}, e, DOC, token=t)
    assert call("create_alert", {"gpu": "H100", "vram_gb": 40, "threshold_usd": 9}, e, DOC, token=t)["error"]["code"] == "not_found"  # no 40GB H100
    call("create_alert", {"gpu": "H100", "vendor": "Nobody", "threshold_usd": 9}, e, DOC, token=t)
    out = call("check_alerts", {}, e, DOC, token=t)
    valid("check_alerts", out)
    a = {r["threshold_usd"]: r for r in out["alerts"]}
    assert a[2.0]["status"] == "fired" and a[2.0]["fired"][0]["vendor"] == "Acme" and a[2.0]["new"] is True
    assert a[2.5]["status"] == "not_triggered" and a[9.0]["status"] == "not_in_feed"   # vendor filter with no row
    assert out["fired_count"] == 1 and out["feed_updated_at"] == "2026-11-23T11:30:00Z"
    assert call("check_alerts", {}, e, DOC, token=t)["alerts"][0]["new"] is False        # same price: already reported
    cheaper = prices([_row("Acme", 1.50), BOLT])
    assert call("check_alerts", {}, e, cheaper, token=t)["alerts"][0]["new"] is True
    hi = call("check_alerts", {}, e, prices([ACME, _row("Bolt", 2.90)]), token=t)
    assert {r["threshold_usd"]: r for r in hi["alerts"]}[2.5]["fired"][0]["hourly_usd"] == 2.9


def test_never_fires_on_stale_or_held_stale_and_reports_skipped():
    e = env()
    held = [{"vendor": "Held", "reason": "Manual snapshot not re-verified for > 2 days", "checked_at": "2026-11-01T00:00:00Z", "source_url": "https://h.example",
             "records": [{"gpu": "H100", "vram_gb": 80, "hourly_usd": 0.5, "tier": "On-demand"}]}]
    old, edge = _row("Old", 0.8, hours_old=49), _row("Edge", 1.1, hours_old=47.5)
    doc = prices([old, edge], held)
    t = call("create_alert", {"gpu": "H100", "threshold_usd": 2.0}, e, doc)["alert_token"]
    out = call("check_alerts", {}, e, doc, token=t)
    valid("check_alerts", out)
    r = out["alerts"][0]
    assert [f["vendor"] for f in r["fired"]] == ["Edge"]                                  # 47.5 h still fires; 49 h and held do not
    sk = {s["vendor"]: s for s in r["skipped_stale"]}
    assert set(sk) == {"Old", "Held"} and all(s["would_have_crossed"] for s in sk.values())
    assert sk["Held"]["hold"] == "held_stale" and "not re-verified" in sk["Held"]["reason"] and sk["Old"]["hold"] == "older_than_48h"
    assert out["skipped_stale_count"] == 2 and "held_stale" in out["stale_rule"]
    only_stale = prices([old], held)
    r2 = call("check_alerts", {}, e, only_stale, token=t)["alerts"][0]
    assert r2["status"] == "skipped_stale" and r2["fired"] == [] and r2["new"] is False
    undated = {**_row("NoDate", 0.4), "checked_at": None, "verified_at": None}
    assert call("check_alerts", {}, e, prices([undated]), token=t)["alerts"][0]["status"] == "skipped_stale"
    rid = rate_id({**held[0]["records"][0], "vendor": "Held"})                            # a held rate_id is accepted but never fires
    t2 = call("create_alert", {"rate_id": rid, "threshold_usd": 1.0}, e, doc)
    assert t2["evaluation"]["status"] == "skipped_stale" and t2["evaluation"]["fired"] == []


# ---- expiry / renew / delete ------------------------------------------------------------------------------------------
def test_ttl_renew_expiry_and_purge(_clock):
    e = env()
    t = call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 2.0}, e, DOC)["alert_token"]
    _clock["t"] = NOW + timedelta(days=20)
    out = call("check_alerts", {"renew": True}, e, DOC, token=t)
    assert out["renewed"] == 1 and out["alerts"][0]["expires_at"] == (NOW + timedelta(days=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _clock["t"] = NOW + timedelta(days=51)
    out = call("check_alerts", {"renew": True}, e, DOC, token=t)
    assert out["alerts"][0]["status"] == "expired" and out["alerts"][0]["fired"] == [] and out["renewed"] == 0   # expired alerts are not renewed
    _clock["t"] = NOW + timedelta(days=58)
    assert call("check_alerts", {}, e, DOC, token=t)["alerts"] == []                                             # purged after 7 days


def test_delete_needs_the_owning_token():
    e = env()
    o = call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 2.0}, e, DOC)
    other = call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 2.0}, e, DOC)["alert_token"]
    aid = o["alert"]["alert_id"]
    assert call("delete_alert", {"alert_id": aid}, e, DOC, token=other)["error"]["code"] == "not_found"
    assert call("delete_alert", {"alert_id": aid}, e, DOC)["error"]["code"] == "unauthorized"
    valid("delete_alert", call("delete_alert", {"alert_id": aid}, e, DOC, token=o["alert_token"]))
    assert call("check_alerts", {}, e, DOC, token=o["alert_token"])["alerts"] == []


# ---- limits -----------------------------------------------------------------------------------------------------------
def test_limits(monkeypatch):
    e = env()
    first = call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 2.0}, e, DOC)
    t = first["alert_token"]
    for _ in range(A.MAX_ALERTS_PER_TOKEN - 1):
        assert call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 2.0}, e, DOC, token=t, ip="198.51.100.1")["ok"]
    over = call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 2.0}, e, DOC, token=t, ip="198.51.100.2")
    assert over["error"]["code"] == "rate_limited" and "per alert_token" in over["error"]["message"]
    monkeypatch.setattr(A, "MAX_CREATES_PER_IP_PER_DAY", 2)
    e2 = env()
    for _ in range(2):
        assert call("create_alert", {"gpu": "H100", "threshold_usd": 2}, e2, DOC, ip="192.0.2.9")["ok"]
    assert call("create_alert", {"gpu": "H100", "threshold_usd": 2}, e2, DOC, ip="192.0.2.9")["error"]["code"] == "rate_limited"
    assert call("create_alert", {"gpu": "H100", "threshold_usd": 2}, e2, DOC, ip="192.0.2.10")["ok"]   # another IP is unaffected
    monkeypatch.setattr(A, "MAX_CHECKS_PER_TOKEN_PER_HOUR", 2)
    t2 = call("create_alert", {"gpu": "H100", "threshold_usd": 2}, e2, DOC, ip="192.0.2.11")["alert_token"]
    assert call("check_alerts", {}, e2, DOC, token=t2)["ok"] and call("check_alerts", {}, e2, DOC, token=t2)["ok"]
    assert call("check_alerts", {}, e2, DOC, token=t2)["error"]["code"] == "rate_limited"
    monkeypatch.setattr(A, "MAX_CREATES_PER_DAY", 1)
    e3 = env()
    assert call("create_alert", {"gpu": "H100", "threshold_usd": 2}, e3, DOC, ip="192.0.2.20")["ok"]
    assert call("create_alert", {"gpu": "H100", "threshold_usd": 2}, e3, DOC, ip="192.0.2.21")["error"]["code"] == "rate_limited"


# ---- D1 quirks and deploy state ---------------------------------------------------------------------------------------
def test_d1_jsnull_rows_serialize():
    e = env(nulls=True)   # every SQL NULL arrives as a falsy JsNull object, as in workerd
    t = call("create_alert", {"gpu": "H100", "threshold_usd": 2.0}, e, DOC)["alert_token"]
    call("create_alert", {"rate_id": ACME_ID, "threshold_usd": 2.0}, e, DOC, token=t)
    out = call("check_alerts", {}, e, DOC, token=t)
    valid("check_alerts", out)
    json.dumps(out)                                                  # no JsNull leaks into the payload
    assert out["fired_count"] == 2


def test_unmigrated_db_and_missing_master_are_clean_errors():
    out = call("create_alert", {"gpu": "H100", "threshold_usd": 2}, types.SimpleNamespace(WATCH_DB=FakeD1(schema=False), WATCH_SIGNING_MASTER=MASTER), DOC)
    assert out["ok"] is False and out["error"]["code"] == "alerts_unavailable"
    out = call("create_alert", {"gpu": "H100", "threshold_usd": 2}, types.SimpleNamespace(WATCH_DB=FakeD1(), WATCH_SIGNING_MASTER=None), DOC)
    assert out["error"]["code"] == "alerts_unavailable"


def test_migration_matches_watch_schema_and_has_no_pii_columns():
    mig = (ROOT / "hosted" / "migrations" / "0008_price_alerts.sql").read_text()
    names = ("price_alert_tokens", "price_alerts", "price_alert_counters")
    assert all(f"CREATE TABLE IF NOT EXISTS {n}" in mig and f"CREATE TABLE IF NOT EXISTS {n}" in (ROOT / "hosted" / "watch_schema.sql").read_text() for n in names)
    cols = {r[1] for n in names for r in FakeD1().c.execute(f"PRAGMA table_info({n})")}
    assert not cols & {"email", "webhook_url", "ip", "ip_hash", "token", "api_key"}   # only token_hash; IP hash lives in a counter scope
    assert "--remote --file=migrations/0008_price_alerts.sql" in mig


def test_tools_are_hosted_only_and_listed():
    from mcp_server import server
    assert A.NAMES == {"create_alert", "check_alerts", "delete_alert"} and not (A.NAMES & S.NAMES)
    src = (ROOT / "mcp_server" / "server.py").read_text()
    for n in A.NAMES:
        assert f"def {n}(" not in src and not hasattr(server, n)
    for t in A.tool_list():
        assert t["outputSchema"]["required"][0] == "ok" and "webhook" not in t["description"].lower().replace("no webhook", "")
    import subprocess
    code = """
import sys, types, json, importlib.util
sys.path.insert(0, %r); sys.path.insert(0, %r)
w = types.ModuleType("workers"); w.Response = w.WorkerEntrypoint = object; w.fetch = None; sys.modules["workers"] = w
spec = importlib.util.spec_from_file_location("hosted_entry", %r); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps([t["name"] for t in m._tool_list()]))
""" % (str(ROOT), str(ROOT / "hosted" / "src"), str(ROOT / "hosted" / "src" / "entry.py"))
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-1500:]
    assert A.NAMES <= set(json.loads(res.stdout.strip().splitlines()[-1]))
