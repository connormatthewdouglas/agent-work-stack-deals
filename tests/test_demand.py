"""P8: daily aggregate demand counters (hosted/src/demand.py) on a sqlite-backed fake D1."""
import asyncio
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hosted" / "src"))
import demand as D  # noqa: E402


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
        base = (ROOT / "hosted" / "schema.sql").read_text()
        if not migrate:
            base = "\n".join(l for l in base.splitlines() if "demand" not in l)
        self.c.executescript(base)
        if migrate:  # the migration applies cleanly on top of the schema (additive, idempotent)
            self.c.executescript((ROOT / "hosted" / "migrations" / "0005_demand.sql").read_text())

    def prepare(self, sql):
        return _Stmt(self.c, sql)


def run(c):
    return asyncio.run(c)


@pytest.mark.parametrize("raw,fam", [
    ("H100", "H100"), ("h100 sxm", "H100"), ("NVIDIA H100 80GB PCIe", "H100"), ("H100 NVL", "H100"), ("A100", "A100"),
    ("a10g", "A10"), ("L40S", "L40S"), ("L4", "L4"), ("RTX 4090", "RTX 4090"), ("4090", "RTX 4090"), ("RTX PRO 6000", "RTX PRO 6000"),
    ("RTX 6000 Ada", "RTX 6000 Ada"), ("MI300X", "MI300X"), ("B200", "B200"), (None, "any"), ("", "any"),
    ("H100 please email me at someone@example.com", "other"), ("my-secret-cluster", "other"), ("A100'; DROP TABLE demand;--", "other"),
    (123, "other"), ("x" * 5000, "other")])
def test_gpu_family_buckets_free_text_to_other(raw, fam):
    assert D.gpu_family(raw) == fam


@pytest.mark.parametrize("raw,g", [("US", "north-america"), ("us-east-1", "north-america"), ("US-NE-1", "north-america"),
                                   ("EU", "europe"), ("eu-west-2", "europe"), ("ap-southeast-1", "asia-pacific"), ("JP", "asia-pacific"),
                                   (None, "any"), ("my office in Springfield", "other"), ("zz-9", "other")])
def test_region_group(raw, g):
    assert D.region_group(raw) == g


def test_record_stores_only_bucketed_aggregates():
    db = FakeD1()
    out = {"ok": True, "results": [{"advertiser": "Hyperstack", "tier_class": "on-demand", "hourly_usd": 2.5}]}
    secret = "ZZ-secret-free-text-42"
    for _ in range(3):
        run(D.record(db, "compare_gpu_prices", {"gpu": "h100 sxm", "region": "us-east-1", "note": secret}, out, "lobehub", "mcp:claude", "other", day="2026-11-10"))
    run(D.record(db, "compare_gpu_prices", {"gpu": secret, "region": secret}, {"ok": False, "error": {"code": "x", "message": secret}},
                 "none", "other", "other", day="2026-11-10"))
    # excluded: house src, house refs, known bots, non-GPU tools
    run(D.record(db, "compare_gpu_prices", {"gpu": "A100"}, out, "none", "house", "house", day="2026-11-10"))
    run(D.record(db, "compare_gpu_prices", {"gpu": "A100"}, out, "house-t139", "other", "other", day="2026-11-10"))
    run(D.record(db, "compare_gpu_prices", {"gpu": "A100"}, out, "t41", "other", "other", day="2026-11-10"))
    run(D.record(db, "compare_gpu_prices", {"gpu": "A100"}, out, "none", "known-bot", "other", day="2026-11-10"))
    run(D.record(db, "search_deals", {"query": secret}, {"ok": True}, "none", "other", "other", day="2026-11-10"))
    rows = run(D.stats(db, day="2026-11-10"))["demand_daily"]
    assert sorted((r["gpu_family"], r["region_group"], r["price_tier"], r["cheapest_provider"], r["n"]) for r in rows) == [
        ("H100", "north-america", "on-demand", "Hyperstack", 3), ("other", "other", "none", "none", 1)]
    dump = json.dumps(rows) + json.dumps([list(r) for r in db.c.execute("SELECT * FROM demand").fetchall()])
    assert secret not in dump and "lobehub" not in dump and "claude" not in dump  # no args, refs or client ids stored
    cols = [r[1] for r in db.c.execute("PRAGMA table_info(demand)").fetchall()]
    assert cols == ["day", "tool", "gpu_family", "region_group", "price_tier", "cheapest_provider", "n"]


def test_estimate_and_agent_stack_dims():
    est = {"ok": True, "results": [{"vendor": "Hyperstack", "tier": "On-demand", "rank": 1}]}
    assert D.dims("estimate_job_cost", {"gpu_family": "H100", "region": "EU"}, est) == ("estimate_job_cost", "H100", "europe", "on-demand", "Hyperstack")
    assert D.dims("estimate_job_cost", {"gpu": "a100"}, {"ok": True, "results": []})[1:] == ("A100", "any", "none", "none")
    st = {"ok": True, "lines": [{"component": "gpu", "choice": {"vendor": "RunPod"}}]}
    assert D.dims("optimize_agent_stack", {"description": "free text never read", "gpu_model": "RTX 4090"}, st)[1:] == ("RTX 4090", "any", "unknown", "RunPod")


def test_never_raises_before_migration_and_stats_empty():
    db = FakeD1(migrate=False)
    run(D.record(db, "compare_gpu_prices", {"gpu": "H100"}, {"ok": True}, "none", "other", "other"))
    assert run(D.stats(db)) == {"demand_daily": []}


def test_retention_drops_old_days():
    db = FakeD1()
    run(D.record(db, "compare_gpu_prices", {"gpu": "H100"}, {"ok": True}, "none", "other", "other", day="2026-06-01"))
    run(D.record(db, "compare_gpu_prices", {"gpu": "H100"}, {"ok": True}, "none", "other", "other", day="2026-11-10"))
    assert [r["day"] for r in run(D.stats(db, day="2026-11-10"))["demand_daily"]] == ["2026-11-10"]


def test_house_rule_matches_callers():
    import callers as C
    assert D.HOUSE_REF_RE.pattern == C.HOUSE_REF_RE.pattern


def test_entry_wires_demand_after_counting():
    src = (ROOT / "hosted" / "src" / "entry.py").read_text()
    assert "import demand" in src and "await demand.record(env.DB, name, args, out, ref, *cls)" in src
    assert "**await demand.stats(self.env.DB)" in src
