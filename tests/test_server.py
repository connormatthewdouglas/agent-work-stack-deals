"""Tool-level tests: call the MCP tools through FastMCP's tool manager with a local feed file."""
import asyncio
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "api" / "v1" / "deals.json"
GPU = ROOT / "api" / "v1" / "gpu-prices.json"


@pytest.fixture(scope="module")
def srv():
    import os
    os.environ["LANTERN_DEALS_FILE"] = str(FEED)
    from mcp_server import server
    server.loader.file = str(FEED)
    server.loader._cache = None
    server.gpu_loader.file = str(GPU)
    server.gpu_loader._cache = None
    return server


def call(srv, name, args):
    res = asyncio.run(srv.mcp.call_tool(name, args))
    content = res[0] if isinstance(res, tuple) else res
    return json.loads(content[0].text)


def test_tools_listed(srv):
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    assert set(tools) == {"search_deals", "compare_deals", "get_deal", "compare_gpu_prices"}
    assert all(t.annotations.readOnlyHint for t in tools.values())


def test_search_paging(srv):
    r = call(srv, "search_deals", {"limit": 3})
    assert r["count"] == 3 and r["next_cursor"]
    r2 = call(srv, "search_deals", {"limit": 3, "cursor": r["next_cursor"]})
    assert {x["id"] for x in r["results"]}.isdisjoint({x["id"] for x in r2["results"]})


def test_search_filter(srv):
    r = call(srv, "search_deals", {"category": "search", "offer_type": "free_tier"})
    assert r["results"] and all(x["category"] == "search" and x["offer_type"] == "free_tier" for x in r["results"])


def test_get_compare_and_errors(srv):
    ids = [x["id"] for x in call(srv, "search_deals", {"limit": 2})["results"]]
    assert call(srv, "get_deal", {"id": ids[0]})["id"] == ids[0]
    assert len(call(srv, "compare_deals", {"ids": ids})["deals"]) == 2
    assert call(srv, "get_deal", {"id": "nope"})["error"]["code"] == "not_found"
    assert call(srv, "compare_deals", {"ids": ids[:1]})["error"]["code"] == "invalid_argument"
    assert call(srv, "search_deals", {"cursor": "bad!"})["error"]["code"] == "invalid_cursor"


def test_no_commission_text_anywhere(srv):
    blob = json.dumps(call(srv, "search_deals", {"limit": 25})).lower()
    assert "commission_" not in blob and "payout_" not in blob


def test_compare_gpu_prices_same_data_sorted_sourced(srv):
    data = json.loads(GPU.read_text())
    r = call(srv, "compare_gpu_prices", {"gpu": "H100", "limit": 25})
    expected = [x for x in data["rates"] if "h100" in x["gpu"].lower().split()]
    assert r["total"] == len(expected) and r["count"] == min(25, len(expected)) >= 2
    hourly = [x["hourly_usd"] for x in r["results"]]
    assert hourly == sorted(hourly) and hourly[0] == min(x["hourly_equiv_usd"] for x in expected)
    for x in r["results"]:
        assert x["source_url"].startswith("https://") and x["checked_at"]
        src = next(y for y in expected if y["deal_id"] == x["deal_id"] and y["basis"] == x["basis"])
        assert src["hourly_equiv_usd"] == x["hourly_usd"] and src["verified_at"] == x["checked_at"]
    assert "cheapest among tracked providers" in r["summary"].lower()
    assert r["scope"] == "cheapest among tracked providers"
    assert "commission" not in json.dumps(r).lower() and "payout" not in json.dumps(r).lower()


def test_compare_gpu_prices_token_match_and_errors(srv):
    assert {x["gpu"] for x in call(srv, "compare_gpu_prices", {"gpu": "L40"})["results"]} == {"L40"}
    assert all("4090" in x["gpu"] for x in call(srv, "compare_gpu_prices", {"gpu": "rtx-4090"})["results"])
    nf = call(srv, "compare_gpu_prices", {"gpu": "TPU v5"})
    assert nf["error"]["code"] == "not_found" and "H100" in nf["error"]["message"]
    assert call(srv, "compare_gpu_prices", {"gpu": " "})["error"]["code"] == "invalid_argument"
    assert call(srv, "compare_gpu_prices", {"gpu": "H100", "limit": 0})["error"]["code"] == "invalid_argument"


def test_every_published_rate_has_source_and_date():
    for x in json.loads(GPU.read_text())["rates"]:
        assert x["source_url"] and x["verified_at"], x["deal_id"]


def test_versions_consistent_and_reported(srv):
    import tomllib
    from core import USER_AGENT, VERSION
    pyver = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    sj = json.loads((ROOT / "mcp_server" / "server.json").read_text())
    assert VERSION == pyver == sj["version"] == sj["packages"][0]["version"] == srv.__version__
    assert srv.mcp._mcp_server.create_initialization_options().server_version == VERSION
    assert USER_AGENT == f"lantern-works-deals-mcp/{VERSION}"
    plugin = json.loads((ROOT / "plugins" / "lantern-works-deals" / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["version"] == VERSION
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert [x["name"] for x in market["plugins"]] == [plugin["name"]]
    assert f"lantern-works-deals-mcp=={VERSION}" in (ROOT / "Dockerfile").read_text()


def test_user_agent_sent(monkeypatch):
    import urllib.request
    from core import USER_AGENT, FeedLoader, GpuPricesLoader
    seen = []

    class R:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.body

    def fake(req, timeout=None):
        seen.append(req.get_header("User-agent"))
        return R(b'{"deals": [], "rates": []}')
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.delenv("LANTERN_DEALS_FILE", raising=False)
    FeedLoader(file=None).load(); GpuPricesLoader(file=None).load()
    assert seen == [USER_AGENT, USER_AGENT]
