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




# ---- T136 (plan Task 7): every provider-naming item carries a tagged /go/ link; one referral line per result ----
import re as _re
from core import golinks

CALLS = {
    "compare_gpu_prices": {"gpu": "H100"},
    "get_price_changes": {"limit": 20},
    "estimate_job_cost": {"gpu_family": "H100", "job_hours": 10},
    "optimize_stack": {"scrape_pages": 1000, "proxy_gb": 5, "emails_sent": 1000},
    "optimize_agent_stack": {"description": "scrapes 20k JS pages via 5 GB residential proxies, 100 GPU hours on an H100"},
    "search_deals": {"query": "proxy"},
}


def _provider_dicts(o, skip=("receipt",)):
    if isinstance(o, dict):
        if any(isinstance(o.get(k), str) and o[k].strip() for k in golinks.PROVIDER_KEYS):
            yield o
        for k, v in o.items():
            if k not in skip:
                yield from _provider_dicts(v, skip)
    elif isinstance(o, list):
        for v in o:
            yield from _provider_dicts(v, skip)


def _targets():
    """Python mirror of collector vendorMap over the committed feeds: which /go/ ids resolve."""
    gpu, deals = json.loads(GPU.read_text()), json.loads(FEED.read_text())
    ids = {d["id"] for d in deals["deals"] if d.get("id") and str(d.get("redeem_url", "")).startswith("https://") and not d.get("example")}
    slugs = {golinks.vendor_slug(r.get("advertiser")) for r in gpu.get("rates", []) if str(r.get("source_url", "")).startswith("https://")}
    slugs |= {golinks.vendor_slug(v.get("vendor")) for v in gpu.get("vendors", []) if str(v.get("source_url", "")).startswith("https://")}
    per = {}
    for d in deals["deals"]:
        if d.get("id") in ids:
            per.setdefault(golinks.vendor_slug(d.get("advertiser")), []).append(d["id"])
    slugs |= {s for s, v in per.items() if len(v) == 1}
    return ids, slugs


@pytest.mark.parametrize("mode", ["brief", "full"])
@pytest.mark.parametrize("tool", sorted(CALLS))
def test_every_provider_has_tagged_go_link_and_disclosure(srv, tool, mode):
    r = call(srv, tool, {**CALLS[tool], "mode": mode})
    assert r["ok"] is True
    rows = list(_provider_dicts(r))
    assert rows, f"{tool} named no provider"
    ids, slugs = _targets()
    for row in rows:
        t = row.get("tracked_url")
        assert t and t.startswith(golinks.GO_BASE) and "src=" in t, (tool, mode, row)
        if "/go/v/" in t:
            assert _re.search(r"/go/v/([a-z0-9-]+)\?", t).group(1) in slugs, t
        else:
            assert _re.search(r"/go/([a-z0-9-]+)\?", t).group(1) in ids, t
    assert r["referral_disclosure"] == golinks.REFERRAL_DISCLOSURE and "\n" not in r["referral_disclosure"]


def test_receipts_untouched_and_links_never_rank(srv):
    r = call(srv, "estimate_job_cost", {"gpu_family": "H100", "job_hours": 10, "mode": "full"})
    assert all("tracked_url" not in l for l in r["receipt"]["lines"])
    r2 = call(srv, "compare_gpu_prices", {"gpu": "H100", "mode": "full"})
    assert [x["rank"] for x in r2["results"]] == sorted(x["rank"] for x in r2["results"])


def test_error_envelope_has_no_links(srv):
    r = call(srv, "get_deal", {"id": "deal-does-not-exist"})
    assert r["ok"] is False and set(r) == {"ok", "error"}


def test_go_link_rules():
    assert golinks.go_link({"deal_id": "deal-abc-001", "advertiser": "A"}) == golinks.GO_BASE + "deal-abc-001?src=mcp"
    assert golinks.go_link({"id": "deal-x", "advertiser": "A"}) == golinks.GO_BASE + "deal-x?src=mcp"
    assert golinks.go_link({"rate_id": "r_1", "vendor": "Vast.ai"}) == golinks.GO_BASE + "v/vast-ai?src=mcp"
    assert golinks.vendor_slug("SiliconFlow (硅基流动, China site)") == "siliconflow-china-site"  # same as collector vendorSlug
    assert golinks.go_link({"vendor": "  "}) is None


def test_schema_and_plugin_manifest_list_referral_disclosure():
    from core import contract
    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    for name in contract.SPEC:
        assert contract.output_schema(name)["properties"]["referral_disclosure"]["type"] == "string"
    for t in plugin["tools"]:
        if t["name"] in contract.SPEC and "outputSchema" in t:
            assert t["outputSchema"]["properties"]["referral_disclosure"] == contract.REFERRAL_DISCLOSURE_SCHEMA, t["name"]
