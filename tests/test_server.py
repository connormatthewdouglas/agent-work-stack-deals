"""Tool-level tests: call the MCP tools through FastMCP's tool manager with a local feed file."""
import asyncio
import json
from pathlib import Path

import pytest

FEED = Path(__file__).resolve().parents[1] / "api" / "v1" / "deals.json"


@pytest.fixture(scope="module")
def srv():
    import os
    os.environ["LANTERN_DEALS_FILE"] = str(FEED)
    from mcp_server import server
    server.loader.file = str(FEED)
    server.loader._cache = None
    return server


def call(srv, name, args):
    res = asyncio.run(srv.mcp.call_tool(name, args))
    content = res[0] if isinstance(res, tuple) else res
    return json.loads(content[0].text)


def test_tools_listed(srv):
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    assert set(tools) == {"search_deals", "compare_deals", "get_deal"}
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
