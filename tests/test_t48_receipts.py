"""T48 (0.4.0, additive): reopenable receipts on the quoting tools and rebuild_quote."""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "mcp_server")]
import server  # noqa: E402

f = lambda t: getattr(t, "fn", t)  # noqa: E731


def _job():
    return f(server.estimate_job_cost)("H100", 9, job_hours=3)


def test_existing_fields_unchanged_and_receipt_added():
    o = _job()
    for k in ("quote_id", "quote_basis", "results", "issued_at"):
        assert k in o
    r = o["receipt"]
    assert r["quote_id"] == o["quote_id"] and r["lines_are"] == "alternatives"
    l = r["lines"][0]
    for k in ("quoted_price_usd", "source_url", "evidence_quote", "verified_at", "rate_id", "subtotal_usd"):
        assert l[k] is not None, k
    fr = r["feed_revision"]
    assert fr["gpu_rates_sha256"] and fr["daily_snapshot_url"].endswith(".json")


def test_stack_tools_carry_receipt():
    a = f(server.optimize_stack)(gpu_hours=100, gpu_model="H100", search_queries=5000)
    assert a["receipt"]["lines_are"] == "components" and {l["kind"] for l in a["receipt"]["lines"]} == {"gpu_hour", "flat_monthly"}
    b = f(server.optimize_agent_stack)("rents 50 H100 hours, 3k search queries")
    assert b["receipt"]["lines"] and "description" not in b["receipt"]["inputs"]


def test_rebuild_reproduces_and_revalidates_same():
    o = _job()
    out = f(server.rebuild_quote)(o["receipt"])
    assert out["receipt_intact"] and out["reproduced"]
    assert all(x["matches"] for x in out["lines"])
    assert out["revalidation"]["revision"] == "same"
    assert {x["status"] for x in out["revalidation"]["lines"]} == {"unchanged"}


def test_rebuild_detects_tamper_and_price_change():
    r = _job()["receipt"]
    t = copy.deepcopy(r); t["lines"][0]["subtotal_usd"] += 1
    assert f(server.rebuild_quote)(t)["receipt_intact"] is False
    # an old receipt quoted at a different price: reproduces, but revalidates as price_changed
    import core.quote as q
    old = copy.deepcopy(r)
    l = old["lines"][0]; l["quoted_price_usd"] = round(l["quoted_price_usd"] + 0.5, 4)
    l["subtotal_usd"] = round(l["quoted_price_usd"] * l["hours"] * l["gpus_billed"], 2)
    body = {k: v for k, v in old.items() if k != "receipt_sha256"}; old["receipt_sha256"] = q._sha(body)
    out = f(server.rebuild_quote)(old)
    assert out["reproduced"] and out["revalidation"]["revision"] == "new"
    assert out["revalidation"]["lines"][0]["status"] == "price_changed"


def test_rebuild_rejects_non_receipt():
    assert f(server.rebuild_quote)({"x": 1})["error"]["code"] == "invalid_argument"
