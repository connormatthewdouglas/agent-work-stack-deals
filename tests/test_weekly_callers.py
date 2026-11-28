"""Privacy-safe weekly repeat-caller IDs (hosted/src/weekly_callers.py) on a sqlite-backed fake D1."""
import asyncio
import json
import re
import sqlite3
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hosted" / "src"))
import weekly_callers as W  # noqa: E402

SECRET = "test-caller-id-secret"  # synthetic test fixture, not a real credential
NAME, VER = "cursor-mcp", "1.2.3"
IP = "203.0.113.77"
INFO = {"name": NAME, "version": VER}
MON = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)  # ISO 2026-W47
SUN = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)  # ISO 2026-W46


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
        if migrate:
            self.c.executescript((ROOT / "hosted" / "migrations" / "0007_weekly_callers.sql").read_text())

    def prepare(self, sql):
        return _Stmt(self.c, sql)

    def dump(self):
        out = []
        for (t,) in self.c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            out += [tuple(r) for r in self.c.execute(f"SELECT * FROM {t}").fetchall()]
        return json.dumps(out)


class Env:
    def __init__(self, db, secret=SECRET):
        self.DB = db
        if secret is not None:
            self.CALLER_ID_SECRET = secret


def rec(env, now=MON, ip=IP, info=INFO, ref="install", uac="mcp:cursor", src="other"):
    asyncio.run(W.record(env, info, ip, ref, uac, src, now=now))


def test_same_signals_same_id_within_week_different_across_weeks():
    week47, week46 = W.iso_week(MON), W.iso_week(SUN)
    assert week47 == "2026-W47" and week46 == "2026-W46"
    prefix = W.network_prefix(IP)
    a = W.caller_id(SECRET, week47, NAME, VER, prefix)
    b = W.caller_id(SECRET, week47, NAME, VER, prefix)
    c = W.caller_id(SECRET, week46, NAME, VER, prefix)
    assert a == b and a != c and re.fullmatch(r"[0-9a-f]{16}", a)
    # Same /24 (and same /48) must collide; a different prefix must not.
    assert W.network_prefix("203.0.113.10") == prefix == "203.0.113.0"
    assert W.caller_id(SECRET, week47, NAME, VER, W.network_prefix("203.0.113.10")) == a
    assert W.caller_id(SECRET, week47, NAME, VER, W.network_prefix("198.51.100.1")) != a
    v6 = W.network_prefix("2001:db8:1234:5678::1")
    assert v6 == W.network_prefix("2001:db8:1234:abcd::2")
    assert v6 != W.network_prefix("2001:db8:9999::1")
    db = FakeD1()
    env = Env(db)
    rec(env, MON, ip=IP)
    rec(env, MON.replace(hour=18), ip="203.0.113.10")  # same week, same /24
    rec(env, SUN, ip=IP)  # previous week
    rows = list(db.c.execute("SELECT iso_week, h, days_seen FROM weekly_callers ORDER BY iso_week"))
    assert len(rows) == 2
    assert {r[0] for r in rows} == {"2026-W46", "2026-W47"}
    assert rows[0][1] != rows[1][1]


def test_no_raw_ip_prefix_or_client_name_in_storage():
    db = FakeD1()
    rec(Env(db), MON, ip=IP, info={"name": "secret-client-marker", "version": "9.9.9"})
    d = db.dump()
    assert IP not in d and "203.0.113" not in d
    assert "secret-client-marker" not in d and NAME not in d
    rows = list(db.c.execute("SELECT iso_week, h, days_seen FROM weekly_callers"))
    assert len(rows) == 1 and rows[0][0] == "2026-W47"
    assert re.fullmatch(r"[0-9a-f]{16}", rows[0][1])
    src = (ROOT / "hosted/src/weekly_callers.py").read_text()
    assert "print(" not in src and "console" not in src and "logging" not in src


def test_exclusions():
    db = FakeD1()
    env = Env(db)
    rec(env, uac="house", src="house")
    rec(env, uac="ci", src="house")
    rec(env, uac="known-bot", src="other")
    rec(env, src="github-actions")
    rec(env, ref="mcp-registry")
    rec(env, ref="ci")
    rec(env, ref="qa")
    rec(env, info={"name": "MCP Registry", "version": "1.0"})
    rec(env, info={"name": "mcp-registry-probe", "version": "0"})
    assert db.c.execute("SELECT COUNT(*) FROM weekly_callers").fetchone()[0] == 0
    rec(env, ref="install", uac="mcp:cursor", src="other")
    assert db.c.execute("SELECT COUNT(*) FROM weekly_callers").fetchone()[0] == 1


def test_counts_distinct_and_3plus_days():
    db = FakeD1()
    env = Env(db)
    rec(env, datetime(2026, 11, 16, tzinfo=timezone.utc), ip="203.0.113.1")
    rec(env, datetime(2026, 11, 17, tzinfo=timezone.utc), ip="203.0.113.1")
    rec(env, datetime(2026, 11, 18, tzinfo=timezone.utc), ip="203.0.113.1")
    rec(env, datetime(2026, 11, 16, tzinfo=timezone.utc), ip="198.51.100.9")
    rec(env, datetime(2026, 11, 16, tzinfo=timezone.utc), ip="198.51.100.9")  # same day, no extra
    s = asyncio.run(W.stats(db, now=MON))
    assert s["weekly_callers"] == [
        {"iso_week": "2026-W47", "distinct_callers": 2, "callers_3plus_days": 1}
    ]
    days = db.c.execute("SELECT days_seen FROM weekly_callers WHERE h = ?", (
        W.caller_id(SECRET, "2026-W47", NAME, VER, W.network_prefix("203.0.113.1")),
    )).fetchone()[0]
    assert days == "2026-11-16,2026-11-17,2026-11-18"


def test_missing_secret_is_noop():
    db = FakeD1()
    rec(Env(db, secret=None))
    rec(Env(db, secret=""))
    assert db.c.execute("SELECT COUNT(*) FROM weekly_callers").fetchone()[0] == 0
    # still a no-op (and must not raise) before the migration is applied
    bare = FakeD1(migrate=False)
    bare.c.execute("DROP TABLE weekly_callers")
    rec(Env(bare, secret=SECRET))  # secret set, table missing
    assert asyncio.run(W.stats(bare, now=MON)) == {"weekly_callers": []}


def test_d1_rows_copied_before_any_use():
    class FrozenRow(dict):
        def __setitem__(self, k, v):
            raise TypeError("D1 row is frozen")

    row = FrozenRow(iso_week="2026-W47", h="abc", days_seen="2026-11-16")
    out = W._row(row)
    assert type(out) is dict
    out["days_seen"] = "2026-11-16,2026-11-17"
    assert row["days_seen"] == "2026-11-16"


def test_stats_json_and_initialize_hook():
    src = (ROOT / "hosted/src/entry.py").read_text()
    blk = src[src.index('if path == "/stats.json"'):src.index('if path == "/internal/watch-events"')]
    for k in ('"weekly_callers_note"', "weekly_callers.stats("):
        assert k in blk
    assert "weekly_callers.record(" in src
    assert "CALLER_ID_SECRET" in (ROOT / "hosted/wrangler.toml").read_text()
    assert "0007_weekly_callers.sql" in (ROOT / "hosted/migrations/0007_weekly_callers.sql").read_text()
