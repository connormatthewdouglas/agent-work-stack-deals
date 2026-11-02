"""The no-install entry point must respect the MCP lifecycle and fail honestly."""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import first_quote as q


class Response(io.BytesIO):
    def __init__(self, message=None, *, body=None, status=200, headers=None):
        super().__init__(body if body is not None else json.dumps(message).encode())
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.status = status


def rpc(i, result):
    return {"jsonrpc": "2.0", "id": i, "result": result}


def test_cli_handshake_citations_receipt_and_internal_attribution(monkeypatch, capsys):
    calls = []
    responses = [
        Response(rpc(1, {"protocolVersion": q.PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": {"version": "test"}}),
                 headers={"Mcp-Session-Id": "session-1"}),
        Response(body=b"", status=202),
        Response(rpc(2, {"structuredContent": {"ok": True, "results": [{"source_url": "https://vendor.example/prices", "checked_at": "2026-11-02"}]}})),
        Response(rpc(3, {"structuredContent": {"ok": True, "receipt": {"schema": "test-receipt"}, "missing_costs": ["tax"]}})),
    ]

    def send(request, timeout):
        calls.append((request, json.loads(request.data)))
        assert timeout == 30
        return responses.pop(0)

    monkeypatch.setattr(q.urllib.request, "urlopen", send)
    assert q.main(["--qa", "--hours", "100", "--gpus", "4"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["comparison"]["results"][0]["source_url"] == "https://vendor.example/prices"
    assert output["job"]["receipt"] and output["job"]["missing_costs"]
    assert [c[1]["method"] for c in calls] == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
    assert "id" not in calls[1][1]
    for request, message in calls:
        assert "ref=house-first-quote" in request.full_url
        headers = {k.lower(): v for k, v in request.header_items()}
        assert headers["user-agent"] == "lantern-works-qa/1.0"
        assert headers["accept"] == "application/json, text/event-stream"
        if message["method"] != "initialize":
            assert headers["mcp-protocol-version"] == q.PROTOCOL and headers["mcp-session-id"] == "session-1"
    assert calls[2][1]["params"]["arguments"]["on_demand_only"] is True
    assert calls[2][1]["params"]["arguments"]["mode"] == "brief"
    job = calls[3][1]["params"]
    assert job["name"] == "estimate_job_cost"
    assert job["arguments"]["gpus_per_job"] == 4 and job["arguments"]["job_hours"] == 100
    assert job["arguments"]["mode"] == "full"  # brief omits the reusable receipt


def test_sse_skips_notifications_and_returns_matching_result():
    body = b': keepalive\n\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\ndata: {"jsonrpc":"2.0",\ndata: "id":2,"result":{"ok":true}}\n\n'
    assert q.read_response(Response(body=body, headers={"Content-Type": "text/event-stream"}), 2) == {"ok": True}


@pytest.mark.parametrize("message", [rpc(9, {}), {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602}}, []])
def test_invalid_or_error_rpc_is_not_a_quote(message):
    with pytest.raises(q.QuoteError):
        q.read_response(Response(message), 1)


@pytest.mark.parametrize("payload", [{"ok": False, "error": {"code": "feed_unavailable"}}, {"ok": True}])
def test_tool_error_flag_or_failure_is_not_a_quote(payload, monkeypatch):
    client = q.Client(q.ENDPOINT)
    monkeypatch.setattr(client, "post", lambda *a: {"isError": True, "structuredContent": payload})
    with pytest.raises(q.QuoteError):
        client.call("compare_gpu_prices", {})


def test_unsupported_negotiation_stops_before_call(monkeypatch):
    client = q.Client(q.ENDPOINT)
    methods = []
    def post(method, params):
        methods.append(method)
        return {"protocolVersion": "unknown"}
    monkeypatch.setattr(client, "post", post)
    with pytest.raises(q.QuoteError):
        client.initialize()
    assert methods == ["initialize"]


def test_untrusted_ref_is_rejected_and_old_ref_is_replaced():
    with pytest.raises(ValueError):
        q.endpoint_with_ref(q.ENDPOINT, 'hf&ref=qa')
    assert q.endpoint_with_ref(q.ENDPOINT + "?ref=old&x=1", "hf").endswith("?x=1&ref=hf")


@pytest.mark.parametrize("hours", ["nan", "inf", "0", "-2"])
def test_invalid_job_duration_never_calls_network(hours, monkeypatch):
    monkeypatch.setattr(q.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("network called"))
    with pytest.raises(SystemExit):
        q.main(["--hours", hours])
