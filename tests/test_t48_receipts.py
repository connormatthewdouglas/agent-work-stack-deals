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


def _resign(r):
    import core.quote as q
    body = {k: v for k, v in r.items() if k != "receipt_sha256"}
    r["receipt_sha256"] = q._sha(body)
    return r


def test_genuine_receipt_provenance_verified_against_pinned_revision():
    out = f(server.rebuild_quote)(_job()["receipt"])
    assert out["reproduced"] is True and out["provenance_verified"] is True
    assert {x["status"] for x in out["provenance"]["lines"]} == {"verified"}


def test_forged_price_is_arithmetic_only(monkeypatch, tmp_path):
    monkeypatch.setenv("LANTERN_GPU_SNAPSHOT_DIR", str(tmp_path))  # no snapshot reachable offline
    r = copy.deepcopy(_job()["receipt"])
    l = r["lines"][0]; l["quoted_price_usd"] = 0.01
    l["subtotal_usd"] = round(0.01 * l["hours"] * l["gpus_billed"], 2)
    out = f(server.rebuild_quote)(_resign(r))
    assert out["receipt_intact"] is True  # unkeyed hash: self-consistent forgery
    assert out["reproduced"] == "arithmetic_only" and out["provenance_verified"] is False
    assert out["provenance"]["lines"][0]["status"] == "price_mismatch"


def test_fake_rate_id_is_arithmetic_only(monkeypatch, tmp_path):
    monkeypatch.setenv("LANTERN_GPU_SNAPSHOT_DIR", str(tmp_path))
    r = copy.deepcopy(_job()["receipt"]); r["lines"][0]["rate_id"] = "r_fake"
    out = f(server.rebuild_quote)(_resign(r))
    assert out["reproduced"] == "arithmetic_only" and out["provenance_verified"] is False
    assert out["provenance"]["lines"][0]["status"] == "unknown_rate_id"


def test_old_revision_checked_against_daily_snapshot(monkeypatch, tmp_path):
    import json
    import core.quote as q
    r = copy.deepcopy(_job()["receipt"]); l = r["lines"][0]
    r["feed_revision"] = {**r["feed_revision"], "gpu_rates_sha256": "0" * 64, "gpu_prices_feed_updated_at": "2026-10-30T12:00:00Z"}
    row = {"vendor": l["vendor"], "gpu": l["offer"], "tier": l["tier"], "vram_gb": l["vram_gb"], "gpu_count": 1,
           "billing_unit": "hourly", "hourly_usd": l["quoted_price_usd"], "price_usd": l["quoted_price_usd"]}
    assert q.rate_id(row) == l["rate_id"]
    (tmp_path / "2026-10-30.json").write_text(json.dumps({"rows": [row]}))
    monkeypatch.setenv("LANTERN_GPU_SNAPSHOT_DIR", str(tmp_path))
    r["lines"] = [l]
    out = f(server.rebuild_quote)(_resign(r))
    assert out["provenance"]["snapshot_checked"] and out["provenance"]["lines"][0]["status"] == "verified"
    l["quoted_price_usd"] = 0.01; l["subtotal_usd"] = round(0.01 * l["hours"] * l["gpus_billed"], 2)
    out = f(server.rebuild_quote)(_resign(r))
    assert out["reproduced"] == "arithmetic_only" and out["provenance"]["lines"][0]["status"] == "price_mismatch"


def test_manifest_tool_count_equals_server_tools():
    import json
    import re
    m = json.loads((ROOT / "mcp/tools.manifest.json").read_text())
    n = len(re.findall(r"^@mcp\.tool", (ROOT / "mcp_server/server.py").read_text(), re.M))
    assert n == 9
    assert m["mcp_server"]["tool_count"] == n == len(m["mcp_server"]["tools"])
    assert f"these {n} tools" in m["mcp_server"]["note"]
