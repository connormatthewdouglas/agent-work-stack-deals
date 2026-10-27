"""Opt-in telemetry client: off by default, minimal payload, failure-safe."""
import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp_server import telemetry  # noqa: E402


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("LANTERN_TELEMETRY", raising=False)
    monkeypatch.delenv("LANTERN_TELEMETRY_URL", raising=False)


def _no_network(monkeypatch):
    calls = []
    monkeypatch.setattr(telemetry.urllib.request, "urlopen", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("network")))
    return calls


def test_disabled_by_default_no_file_no_network(monkeypatch, tmp_path):
    calls = _no_network(monkeypatch)
    for v in (None, "0", "true", "yes", ""):
        if v is not None:
            monkeypatch.setenv("LANTERN_TELEMETRY", v)
        assert not telemetry.enabled()
        telemetry.record("search_deals", "9.9.9")
    assert calls == [] and not list(tmp_path.rglob("*"))


def test_default_url_empty_means_local_only(monkeypatch):
    calls = _no_network(monkeypatch)
    monkeypatch.setenv("LANTERN_TELEMETRY", "1")
    st = telemetry._state_path()
    st.parent.mkdir(parents=True)
    st.write_text(json.dumps({"counts": {"2000-01-01": {"get_deal|1": 3}}}))
    if telemetry.DEFAULT_URL == "":
        telemetry.record("get_deal", "1")
        time.sleep(0.2)
        assert calls == []


def test_payload_shape_only_tool_version_day_count():
    p = telemetry.build_payload({"2026-10-27": {"search_deals|0.3.3": 4, "evil|0.3.3": 1, "get_deal|0.3.3": 0}})
    assert p == {"events": [{"t": "search_deals", "v": "0.3.3", "d": "2026-10-27", "n": 4}]}
    for e in p["events"]:
        assert set(e) == {"t", "v", "d", "n"}


def test_counts_locally_and_state_has_no_ids(monkeypatch):
    monkeypatch.setenv("LANTERN_TELEMETRY", "1")
    monkeypatch.setenv("LANTERN_TELEMETRY_URL", "")
    for _ in range(3):
        telemetry.record("compare_gpu_prices", "0.3.3")
    st = json.loads(telemetry._state_path().read_text())
    assert set(st) == {"counts"}
    assert list(st["counts"].values()) == [{"compare_gpu_prices|0.3.3": 3}]


class _H(BaseHTTPRequestHandler):
    got = []

    def do_POST(self):
        _H.got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_sends_completed_days_once_per_day(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _H.got.clear()
    monkeypatch.setenv("LANTERN_TELEMETRY", "1")
    monkeypatch.setenv("LANTERN_TELEMETRY_URL", f"http://127.0.0.1:{srv.server_port}/v1/events")
    st = telemetry._state_path()
    st.parent.mkdir(parents=True)
    st.write_text(json.dumps({"counts": {"2000-01-01": {"get_deal|0.3.3": 2}}}))
    telemetry.record("get_deal", "0.3.3")
    for _ in range(50):
        if _H.got and "last_sent" in json.loads(st.read_text()):
            break
        time.sleep(0.05)
    telemetry.record("get_deal", "0.3.3")  # same day: no second send
    time.sleep(0.3)
    srv.shutdown()
    assert _H.got == [{"events": [{"t": "get_deal", "v": "0.3.3", "d": "2000-01-01", "n": 2}]}]
    left = json.loads(st.read_text())
    assert "2000-01-01" not in left["counts"] and list(left["counts"].values())[0]["get_deal|0.3.3"] == 2


def test_failure_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("LANTERN_TELEMETRY", "1")
    monkeypatch.setenv("LANTERN_TELEMETRY_URL", "http://127.0.0.1:9/nothing")
    assert telemetry.send({"events": []}, "http://127.0.0.1:9/x", timeout=0.5) is False
    t = time.time()
    telemetry.record("search_deals", "0.3.3")
    assert time.time() - t < 0.5
    bad = tmp_path / "f"
    bad.write_text("x")  # cache "dir" is a file -> write fails, must not raise
    monkeypatch.setenv("XDG_CACHE_HOME", str(bad))
    telemetry.record("search_deals", "0.3.3")
    telemetry._state_path().parent  # still callable
    monkeypatch.setattr(telemetry, "_today", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    telemetry.record("search_deals", "0.3.3")


def test_tools_still_expose_full_schemas():
    from mcp_server import server
    tools = asyncio.run(server.mcp.list_tools())
    by = {t.name: t for t in tools}
    assert set(by) == telemetry.TOOLS
    assert "gpu" in by["compare_gpu_prices"].inputSchema["properties"]
    assert "ids" in by["compare_deals"].inputSchema["properties"]
