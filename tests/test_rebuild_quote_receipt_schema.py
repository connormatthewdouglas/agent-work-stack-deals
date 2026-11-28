"""rebuild_quote receipt argument: advertised schema is an object; object and JSON string both work.

Deterministic except for using the same local estimate_job_cost receipt as T48
(no live network). Invalid JSON and non-objects stay invalid_argument.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "mcp_server")]

from core import contract  # noqa: E402
import server  # noqa: E402

f = lambda t: getattr(t, "fn", t)  # noqa: E731


def _receipt():
    return f(server.estimate_job_cost)("H100", 9, job_hours=3)["receipt"]


def _mcp_rebuild(receipt):
    """Call rebuild_quote the way stdio/hosted do: check_args, then the tool."""
    args = {"receipt": receipt}
    fn = server.rebuild_quote
    bad = contract.check_args(fn, args)
    if bad is not None:
        return bad
    return f(fn)(args["receipt"])


def _fastmcp_rebuild(receipt):
    res = asyncio.run(server.mcp.call_tool("rebuild_quote", {"receipt": receipt}))
    content = res[0] if isinstance(res, tuple) else res
    return json.loads(content[0].text)


def test_advertised_schema_says_receipt_is_an_object():
    stdio = {t.name: t for t in asyncio.run(server.mcp.list_tools())}["rebuild_quote"]
    assert stdio.inputSchema["properties"]["receipt"]["type"] == "object"

    code = """
import sys, types, json, importlib.util
sys.path.insert(0, %r); sys.path.insert(0, %r)
w = types.ModuleType("workers"); w.Response = w.WorkerEntrypoint = object; w.fetch = None; sys.modules["workers"] = w
spec = importlib.util.spec_from_file_location("hosted_entry", %r); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps(m._tool_list()))
""" % (str(ROOT), str(ROOT / "hosted" / "src"), str(ROOT / "hosted" / "src" / "entry.py"))
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-2000:]
    hosted = {x["name"]: x for x in json.loads(res.stdout.strip().splitlines()[-1])}["rebuild_quote"]
    assert hosted["inputSchema"]["properties"]["receipt"]["type"] == "object"
    assert hosted["inputSchema"]["properties"]["receipt"]["type"] != "string"


@pytest.mark.parametrize("call", [_mcp_rebuild, _fastmcp_rebuild])
def test_object_and_json_string_receipts_agree_on_mcp_path(call):
    receipt = _receipt()
    as_object = call(receipt)
    as_string = call(json.dumps(receipt))
    assert as_object["ok"] is True and as_string["ok"] is True
    assert as_object["quote_id"] == as_string["quote_id"] == receipt["quote_id"]
    assert as_object["receipt_intact"] is True and as_string["receipt_intact"] is True
    assert as_object["reproduced"] == as_string["reproduced"]


def test_invalid_json_and_non_object_are_clear_invalid_argument():
    bad_json = _mcp_rebuild("{not json")
    assert bad_json["ok"] is False and bad_json["error"]["code"] == "invalid_argument"
    assert "not valid JSON" in bad_json["error"]["message"]

    for payload in ("[]", "1", "null", "\"x\""):
        out = _mcp_rebuild(payload)
        assert out["ok"] is False and out["error"]["code"] == "invalid_argument", payload
        assert out["error"]["message"] == "receipt must be an object", payload

    not_a_receipt = _mcp_rebuild({"x": 1})
    assert not_a_receipt["ok"] is False and not_a_receipt["error"]["code"] == "invalid_argument"
    assert not_a_receipt["error"]["message"] == "receipt must be the 'receipt' object from a quoting tool"
