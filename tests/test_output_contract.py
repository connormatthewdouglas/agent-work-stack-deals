"""T36: typed outputSchema on every tool, ok/error envelope with stable codes, brief/full modes."""
import asyncio
import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import contract  # noqa: E402
from mcp_server import server as s  # noqa: E402

TOOLS = ["compare_gpu_prices", "get_price_changes", "optimize_stack", "optimize_agent_stack", "search_deals",
         "compare_deals", "get_deal"]


def _ids():
    return [d["id"] for d in s.search_deals(limit=2)["results"]]


def _calls():
    ids = _ids()
    return {
        "compare_gpu_prices": dict(gpu="H100", limit=3),
        "get_price_changes": dict(),
        "optimize_stack": dict(scrape_pages=1000, gpu_hours=10),
        "optimize_agent_stack": dict(description="scraping 1000 pages and 10 H100 gpu hours, budget $500/mo"),
        "search_deals": dict(limit=2),
        "compare_deals": dict(ids=ids),
        "get_deal": dict(id=ids[0]),
    }


def _validate(tool, out):
    jsonschema.validate(json.loads(json.dumps(out)), contract.output_schema(tool))


def test_tools_list_exposes_output_schema_for_all_7():
    listed = {t.name: t for t in asyncio.run(s.mcp.list_tools())}
    assert set(TOOLS) <= set(listed)
    for name in TOOLS:
        assert listed[name].outputSchema == contract.output_schema(name), name
        assert "mode" in listed[name].inputSchema["properties"], name
        jsonschema.Draft202012Validator.check_schema(listed[name].outputSchema)


@pytest.mark.parametrize("mode", ["full", "brief"])
def test_every_tool_validates_in_both_modes(mode):
    for tool, kw in _calls().items():
        out = getattr(s, tool)(**kw, mode=mode)
        assert out["ok"] is True and out["mode"] == mode and "error" not in out, (tool, out.get("error"))
        _validate(tool, out)


WALL_CLOCK_RETRIEVAL_FIELDS = ("last_successful_retrieval_at", "last_refresh_attempt_at", "cache_age_s")


def test_full_mode_is_default_and_unchanged_plus_envelope():
    for tool, kw in _calls().items():
        default, full = getattr(s, tool)(**kw), getattr(s, tool)(**kw, mode="full")
        for o in (default, full):
            o.pop("next_refresh_utc", None)
            o.pop("issued_at", None)  # T39: wall-clock time of the receipt (not part of quote_id)
            for f_ in (o.get("retrieval") or {}).get("feeds") or []:  # drop only wall-clock stamps (a call can straddle
                for k in WALL_CLOCK_RETRIEVAL_FIELDS:                     # a second boundary); status/feeds still compared
                    f_.pop(k, None)
        if s.default_mode(tool) == "full":
            assert default == full, tool
        assert default["mode"] == s.default_mode(tool)


def test_t72_compare_gpu_prices_defaults_to_brief_full_is_explicit():
    kw = _calls()["compare_gpu_prices"]
    default, brief, full = s.compare_gpu_prices(**kw), s.compare_gpu_prices(**kw, mode="brief"), s.compare_gpu_prices(**kw, mode="full")
    assert default["mode"] == "brief" and set(default) == set(brief)
    assert full["mode"] == "full" and set(brief) <= set(full) and len(json.dumps(default)) < len(json.dumps(full)) * 0.4  # 0.4x already covers the restored form-factor note + pick source_url/tier (~450 chars, ~0.03x full; brief ~0.30x), so no further raise; additive-only rule (strat2). Brief rows also carry referral_url/label disclosure (strat2) and audit fields; still well under half
    assert s.default_mode("compare_gpu_prices") == "brief"
    assert all(s.default_mode(t) == "full" for t in _calls() if t != "compare_gpu_prices")


def test_brief_is_a_subset():
    for tool, kw in _calls().items():
        full, brief = getattr(s, tool)(**kw, mode="full"), getattr(s, tool)(**kw, mode="brief")
        assert set(brief) <= set(full) and len(json.dumps(brief)) < len(json.dumps(full)), tool


ERROR_CASES = [
    ("compare_gpu_prices", dict(gpu="ZZZ"), "not_found"),
    ("compare_gpu_prices", dict(gpu="H100", limit=0), "invalid_argument"),
    ("get_deal", dict(id="nope"), "not_found"),
    ("search_deals", dict(limit=0), "invalid_argument"),
    ("search_deals", dict(cursor="garbage!"), "invalid_cursor"),
    ("optimize_agent_stack", dict(description=""), "invalid_argument"),
    ("optimize_stack", dict(), "invalid_argument"),
    ("compare_deals", dict(ids=[]), "invalid_argument"),
    ("get_price_changes", dict(since="not-a-date"), "invalid_argument"),
    ("get_deal", dict(id="x", mode="tiny"), "invalid_argument"),
]


@pytest.mark.parametrize("tool,kw,code", ERROR_CASES)
def test_error_paths_are_typed(tool, kw, code):
    out = getattr(s, tool)(**kw)
    assert out["ok"] is False and set(out) == {"ok", "error"}, out
    assert out["error"]["code"] == code and out["error"]["code"] in contract.ERROR_CODES and out["error"]["message"]
    _validate(tool, out)


def test_unexpected_exception_becomes_internal_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(s.gpu_loader, "load", boom)
    out = s.compare_gpu_prices(gpu="H100")
    assert out == {"ok": False, "error": {"code": "internal_error", "message": "RuntimeError"}}


def test_hosted_worker_tools_list_has_output_schema():
    """The hosted entry.py exposes the same outputSchema via its own tools/list (fresh interpreter, like the worker)."""
    import subprocess
    code = """
import sys, types, json, importlib.util
sys.path.insert(0, %r); sys.path.insert(0, %r)
w = types.ModuleType("workers"); w.Response = w.WorkerEntrypoint = object; w.fetch = None; sys.modules["workers"] = w
spec = importlib.util.spec_from_file_location("hosted_entry", %r); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps(m._tool_list()))
""" % (str(ROOT), str(ROOT / "hosted" / "src"), str(ROOT / "hosted" / "src" / "entry.py"))
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-2000:]
    listed = {t["name"]: t for t in json.loads(res.stdout.strip().splitlines()[-1])}
    for name in TOOLS:
        assert listed[name]["outputSchema"] == contract.output_schema(name), name
        assert "mode" in listed[name]["inputSchema"]["properties"], name
    for name in ("create_watch_key", "watch_price", "list_watches", "delete_watch"):  # hosted-only opt-in tools
        assert name not in TOOLS and listed[name]["outputSchema"]["required"] == ["ok"], name


def test_real_mcp_client_roundtrip_validates_structured_content():
    """Through the real MCP SDK (which validates structuredContent against outputSchema), both modes and errors."""
    from mcp.shared.memory import create_connected_server_and_client_session

    async def run():
        async with create_connected_server_and_client_session(s.mcp._mcp_server) as cl:
            outs = []
            for name, args in (("compare_gpu_prices", {"gpu": "H100", "limit": 2, "mode": "brief"}),
                               ("optimize_agent_stack", {"description": "10 H100 gpu hours"}),
                               ("get_deal", {"id": "nope"})):
                r = await cl.call_tool(name, args)
                outs.append((name, r.structuredContent))
            return outs

    (n1, a), (n2, b), (n3, c) = asyncio.run(run())
    assert a and a["ok"] is True and a["mode"] == "brief"
    assert b and b["ok"] is True and b["mode"] == "full"
    assert c == {"ok": False, "error": {"code": "not_found", "message": "No deal with id 'nope'"}}


def test_t72_brief_compare_keeps_counts_scope_and_refresh():
    from core.contract import SPEC
    top, row = SPEC["compare_gpu_prices"][3], SPEC["compare_gpu_prices"][4]
    for k in ("scope", "total", "excluded_non_on_demand", "excluded_reserved", "next_refresh_utc", "data_checked_at", "refresh_hint"):
        assert k in top
    for k in ("tier", "tier_class", "price_status", "in_stock"):
        assert k in row
