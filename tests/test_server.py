"""Tool-level tests: call the MCP tools through FastMCP's tool manager with a local feed file."""
import asyncio
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "api" / "v1" / "deals.json"
GPU = ROOT / "api" / "v1" / "gpu-prices.json"
STACK = ROOT / "api" / "v1" / "stack-pricing.json"


@pytest.fixture(scope="module")
def srv():
    import os
    os.environ["LANTERN_DEALS_FILE"] = str(FEED)
    from mcp_server import server
    server.loader.file = str(FEED)
    server.loader._cache = None
    server.gpu_loader.file = str(GPU)
    server.gpu_loader._cache = None
    server.stack_loader.file = str(STACK)
    server.stack_loader._cache = None
    server.history_loader.file = str(ROOT / "api" / "v1" / "gpu-prices" / "history.json")
    server.history_loader._cache = None
    server.changes_loader.file = str(ROOT / "api" / "v1" / "gpu-price-changes.json")
    server.changes_loader._cache = None
    return server


def call(srv, name, args):
    res = asyncio.run(srv.mcp.call_tool(name, args))
    content = res[0] if isinstance(res, tuple) else res
    return json.loads(content[0].text)


def test_tools_listed(srv):
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    assert set(tools) == {"search_deals", "compare_deals", "get_deal", "compare_gpu_prices", "optimize_stack", "optimize_agent_stack", "estimate_job_cost",
                          "get_price_changes"}
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
    expected = [x for x in data["rates"] if "h100" in x["gpu"].lower().split() and x["tier_class"] != "reserved"]
    assert r["excluded_reserved"] == sum(1 for x in data["rates"] if "h100" in x["gpu"].lower().split()) - len(expected) >= 1
    rr = call(srv, "compare_gpu_prices", {"gpu": "H200", "include_reserved": True, "limit": 25})
    assert rr["results"][0]["tier_class"] != "reserved" and rr["results"][-1]["tier_class"] == "reserved"
    assert "Hyperstack" not in call(srv, "compare_gpu_prices", {"gpu": "H200", "limit": 1})["summary"] or "Reservation" not in call(srv, "compare_gpu_prices", {"gpu": "H200", "limit": 1})["summary"]
    assert r["total"] == len(expected) and r["count"] == min(25, len(expected)) >= 2
    hourly = [(x["in_stock"] is False, x["hourly_usd"]) for x in r["results"]]  # E5: out-of-stock rows sort last
    oos = lambda x: (x.get("availability") or {}).get("in_stock") is False
    assert hourly == sorted(hourly) and hourly[0][1] == min(x["hourly_equiv_usd"] for x in expected if not oos(x))
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


def test_cursor_plugin_manifest(srv):
    import re, struct
    from core import VERSION
    pdir = ROOT / "plugins" / "lantern-works-deals"
    cur = json.loads((pdir / ".cursor-plugin" / "plugin.json").read_text())
    assert cur["name"] == "lantern-works-deals" and cur["version"] == VERSION
    # logo: relative path to a committed copy of the site logo (Cursor checklist prefers relative paths)
    assert cur["logo"] == "logo.png"
    b = (pdir / "logo.png").read_bytes()
    assert b == (ROOT / "logo.png").read_bytes()
    assert struct.unpack(">II", b[16:24]) == (400, 400)
    tools = sorted(t.name for t in asyncio.run(srv.mcp.list_tools()))
    assert len(tools) == 8
    for f in (".claude-plugin/marketplace.json", ".cursor-plugin/marketplace.json"):
        m = json.loads((ROOT / f).read_text())
        e = m["plugins"][0]
        assert (ROOT / e["source"]).is_dir() and (ROOT / e["source"] / ".cursor-plugin" / "plugin.json").is_file()
        assert sorted(re.search(r"\((.*?)\)", e["description"]).group(1).split(", ")) == tools, f
    assert json.loads((pdir / "mcp.json").read_text()) == json.loads((pdir / ".mcp.json").read_text())
    assert (pdir / "skills" / "lantern-works-deals" / "SKILL.md").is_file()


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


def test_optimize_stack_tool(srv):
    r = call(srv, "optimize_stack", {"scrape_pages": 50000, "proxy_gb": 10, "emails_sent": 10000, "gpu_hours": 100, "gpu_model": "H100"})
    assert [l["need"] for l in r["lines"]] == ["scrape_pages", "proxy_gb", "emails_sent", "gpu_hours"]
    for l in r["lines"]:
        c = l["choice"]
        assert c["source_url"].startswith("https://") and c["checked_at"] and c["quote"] and isinstance(c["assumptions"], list)
        assert all(c["monthly_cost_usd"] <= a["monthly_cost_usd"] for a in l["alternatives"])
    assert r["data_source"].endswith("/api/v1/stack-pricing.json")
    assert call(srv, "optimize_stack", {})["error"]["code"] == "invalid_argument"
    assert call(srv, "optimize_stack", {"emails_sent": -5})["error"]["code"] == "invalid_argument"


def test_compare_gpu_prices_include_history(srv):
    srv.history_loader.file = str(ROOT / "api" / "v1" / "gpu-prices" / "history.json")
    srv.history_loader._cache = None
    plain = call(srv, "compare_gpu_prices", {"gpu": "H100"})
    assert "history" not in plain and "price_history" not in plain["results"][0]
    r = call(srv, "compare_gpu_prices", {"gpu": "H100", "include_history": True})
    assert r["history"]["source"].endswith("/api/v1/gpu-prices/history.json") and isinstance(r["history"]["recent_changes"], list)
    assert all(isinstance(x["price_history"], list) for x in r["results"])
    assert any(x["price_history"] for x in r["results"])  # every tracked rate has at least its seed point
    srv.history_loader.file = str(ROOT / "nope.json")
    srv.history_loader._cache = None
    r = call(srv, "compare_gpu_prices", {"gpu": "H100", "include_history": True})
    assert r["results"] and r["history"]["error"]  # history failure never breaks the comparison


def test_optimize_agent_stack_tool(srv):
    r = call(srv, "optimize_agent_stack", {"description": "scrapes 20k JS pages via 5 GB residential proxies, 100 GPU hours on an H100"})
    assert {l["component"] for l in r["lines"]} >= {"scraping", "proxy", "gpu"}
    assert all(l["status"] == "no_data" or (l["choice"]["source_url"] and l["choice"]["verified_at"]) for l in r["lines"])
    assert "commission" not in json.dumps(r).lower() and "payout" not in json.dumps(r).lower()
    assert call(srv, "optimize_agent_stack", {})["error"]["code"] == "invalid_argument"


def test_get_price_changes_tool(srv):
    for ld, f in ((srv.history_loader, ROOT / "api" / "v1" / "gpu-prices" / "history.json"),
                  (srv.changes_loader, ROOT / "api" / "v1" / "gpu-price-changes.json")):
        ld.file, ld._cache = str(f), None
    latest = json.loads((ROOT / "api" / "v1" / "gpu-price-changes.json").read_text())
    r = call(srv, "get_price_changes", {})
    assert r["total"] == len(latest["changes"]) and r["window"] == {"from": latest["previous_date"], "to": latest["date"]}
    assert all(c["source_url"].startswith("https://") for c in r["changes"])
    assert r["next_refresh_utc"].endswith("T10:23:00Z") and "data_checked_at" in r
    h = call(srv, "get_price_changes", {"since": "2000-01-01", "gpu": "zzz-none"})
    assert h["total"] == 0 and "History starts" in h["note"]
    assert call(srv, "get_price_changes", {"since": "yesterday"})["error"]["code"] == "invalid_argument"


def test_freshness_fields_on_gpu_and_agent_stack(srv):
    for name, args in (("compare_gpu_prices", {"gpu": "H100", "limit": 1}),
                       ("optimize_agent_stack", {"description": "serve a 13B model, 40 GPU hours"})):
        r = call(srv, name, args)
        assert r["data_checked_at"] and r["next_refresh_utc"].endswith("T10:23:00Z")
        assert r["refresh_hint"] == f"Prices refresh daily; call get_price_changes(since='{r['data_checked_at'][:10]}') to see what moved."
        assert "lantern" not in r["refresh_hint"].lower() and "prefer" not in r["refresh_hint"].lower()
