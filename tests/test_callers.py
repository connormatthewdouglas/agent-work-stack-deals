"""Anonymized distinct-caller counting (hosted/src/callers.py) on a sqlite-backed fake D1."""
import asyncio
import json
import re
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hosted" / "src"))
import callers as C  # noqa: E402

IP, UA = "203.0.113.77", "python-httpx/0.27 secret-ua-marker"


class _Stmt:
    def __init__(self, c, sql):
        self.c, self.sql, self.args = c, sql, ()

    def bind(self, *a):
        self.args = a
        return self

    async def all(self):
        return types.SimpleNamespace(results=[dict(r) for r in self.c.execute(self.sql, self.args).fetchall()])

    async def run(self):
        self.c.execute(self.sql, self.args)
        self.c.commit()


class FakeD1:
    def __init__(self, migrate=True):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        self.c.executescript((ROOT / "hosted" / "schema.sql").read_text())
        if migrate:  # the migration must apply cleanly on top of the existing schema (additive, idempotent)
            self.c.executescript((ROOT / "hosted" / "migrations" / "0004_stats_callers.sql").read_text())

    def prepare(self, sql):
        return _Stmt(self.c, sql)

    def dump(self):
        out = []
        for (t,) in self.c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            out += [tuple(r) for r in self.c.execute(f"SELECT * FROM {t}").fetchall()]
        return json.dumps(out)


@pytest.fixture(autouse=True)
def _fresh_cache():
    C._salt.clear()


def rec(db, day, ref="install", uac="mcp:python-sdk", src="other", ip=IP, ua=UA, kind="mcp"):
    asyncio.run(C.record(db, kind, ref, uac, src, ip, ua, day=day))


def test_no_raw_ip_or_ua_in_storage():
    db = FakeD1()
    rec(db, "2026-11-10")
    rec(db, "2026-11-10", kind="feed")
    d = db.dump()
    assert IP not in d and "secret-ua-marker" not in d and "python-httpx" not in d
    assert re.search(r'"[0-9a-f]{64}"', d)  # only the hash
    src = (ROOT / "hosted/src/callers.py").read_text()
    assert "print(" not in src and "console" not in src and "logging" not in src


def test_hash_stable_within_day_changes_across_days_and_old_salt_deleted():
    db = FakeD1()
    rec(db, "2026-11-10")
    rec(db, "2026-11-10")
    C._salt.clear()  # another isolate must reuse the same day salt from D1
    rec(db, "2026-11-10")
    h1 = {r[0] for r in db.c.execute("SELECT h FROM callers WHERE day='2026-11-10'")}
    assert len(h1) == 1
    salt1 = db.c.execute("SELECT salt FROM caller_salts WHERE day='2026-11-10'").fetchone()[0]
    rec(db, "2026-11-11")
    h2 = {r[0] for r in db.c.execute("SELECT h FROM callers WHERE day='2026-11-11'")}
    assert len(h2) == 1 and h1 != h2
    assert [r[0] for r in db.c.execute("SELECT day FROM caller_salts")] == ["2026-11-11"]  # past salt gone: unlinkable
    assert C.caller_hash(salt1, IP, UA) in h1 and C.caller_hash("other", IP, UA) not in h1


def test_distinct_counting_and_stats_shape():
    db = FakeD1()
    for ip in ("198.51.100.1", "198.51.100.2", "198.51.100.1"):
        rec(db, "2026-11-10", ip=ip)
    rec(db, "2026-11-10", ip="198.51.100.1", kind="feed", ref="none", uac="other")
    rec(db, "2026-11-09", ip="198.51.100.9")
    s = asyncio.run(C.stats(db, day="2026-11-10"))
    assert set(s) == {"callers_daily", "callers"}
    assert s["callers_daily"] == [{"day": "2026-11-10", "distinct_callers": 2}, {"day": "2026-11-09", "distinct_callers": 1}]
    row = next(r for r in s["callers"] if r["day"] == "2026-11-10" and r["kind"] == "mcp")
    assert row == {"day": "2026-11-10", "kind": "mcp", "ref": "install", "ua_class": "mcp:python-sdk", "src_class": "other", "distinct_callers": 2}
    assert all(set(r) == {"day", "kind", "ref", "ua_class", "src_class", "distinct_callers"} for r in s["callers"])
    assert "salt" not in json.dumps(s) and not re.search(r"[0-9a-f]{64}", json.dumps(s))


def test_house_traffic_excluded():
    db = FakeD1()
    rec(db, "2026-11-10", uac="house", src="house")
    rec(db, "2026-11-10", uac="ci", src="house")
    for ref in ("ci", "qa", "test", "smoke", "house-x", "t80", "t41-12"):
        rec(db, "2026-11-10", ref=ref)
    assert db.c.execute("SELECT COUNT(*) FROM callers").fetchone()[0] == 0
    assert db.c.execute("SELECT COUNT(*) FROM caller_salts").fetchone()[0] == 0
    assert not C.is_house("install-test", "other") and not C.is_house("mcp-registry", "other")


def test_noop_without_migration():
    db = FakeD1(migrate=False)
    db.c.execute("DROP TABLE callers")
    db.c.execute("DROP TABLE caller_salts")
    rec(db, "2026-11-10")  # must not raise
    assert asyncio.run(C.stats(db, day="2026-11-10")) == {"callers_daily": [], "callers": []}


def test_stats_json_keeps_existing_fields_and_adds_callers():
    src = (ROOT / "hosted/src/entry.py").read_text()
    blk = src[src.index('if path == "/stats.json"'):src.index('if path == "/internal/watch-events"')]
    for k in ('"schema"', '"note"', '"rows"', '"watches"', '"hits_note"', '"hits"', '"callers_note"', "callers.stats("):
        assert k in blk
    assert src.count("callers.record(") == 2
