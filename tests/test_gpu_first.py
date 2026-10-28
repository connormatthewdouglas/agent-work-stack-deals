"""GPU-first homepage, /deals/ directory, price-changes feeds, one live rate count, stack optimizer default view."""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core.gpu import build_rates, live_rate_count  # noqa: E402


def _deals():
    return [d for d in json.loads((ROOT / "deals.json").read_text())["deals"] if not d.get("example")]


def _live():
    return live_rate_count(_deals())


def test_live_count_matches_api():
    assert _live() == len(json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())["rates"])


def test_homepage_leads_with_gpu_spread_and_install():
    t = (ROOT / "index.html").read_text()
    h1 = re.search(r"<h1>(.*?)</h1>", t).group(1)
    assert h1 == "GPU price comparison for agents, checked daily"
    for fam in ("h100", "a100", "rtx-4090"):
        assert f'data-fam="{fam}"' in t
    assert 'href="https://thelanternworks.com/gpu/"' in t
    assert "uvx lantern-works-deals-mcp" in t and "pip install lantern-works-deals-mcp" in t
    assert '<article class="deal"' not in t  # the directory lives at /deals/
    # spread numbers are the feed's numbers
    import home_page
    for s in home_page.spread(build_rates(_deals())["rates"]):
        row = re.search(rf'<tr data-fam="{s["slug"]}">(.*?)</tr>', t).group(1)
        assert f'${s["min"]:.2f}' in row and f'${s["max"]:.2f}' in row


def test_deals_directory_nav_footer_sitemap_and_old_links():
    d = (ROOT / "deals" / "index.html").read_text()
    assert '<link rel="canonical" href="https://thelanternworks.com/deals/"' in d
    home = (ROOT / "index.html").read_text()
    nav = home.split('<nav class="sitenav"')[1].split("</nav>")[0]
    assert 'href="https://thelanternworks.com/deals/"' in nav
    assert 'href="https://thelanternworks.com/deals/">Deals</a>' in home.split("<footer>")[1]
    assert 'location.replace("/deals/"' in home  # old /?q= and /#cat- links forward
    sm = (ROOT / "sitemap.xml").read_text()
    for u in ("/deals/", "/api/v1/gpu-price-changes.json", "/api/v1/gpu-price-changes.xml"):
        assert f"<loc>https://thelanternworks.com{u}</loc>" in sm, u
    import generate_seo_pages as gen
    for x in _deals():  # deal URLs unchanged
        assert (ROOT / "deals" / gen.slug_for(x["id"]) / "index.html").exists(), x["id"]


def test_price_changes_json_and_rss():
    from core.gpu_changes import build_changes
    doc = json.loads((ROOT / "api" / "v1" / "gpu-price-changes.json").read_text())
    fresh = build_changes()
    assert doc["changes"] == fresh["changes"] and doc["date"] == fresh["date"]
    assert sum(doc["counts"].values()) == len(doc["changes"])
    for c in doc["changes"]:
        assert c["change"] in ("down", "up", "new", "removed") and c["source_url"].startswith("http")
        if c["change"] in ("down", "up"):
            assert (c["new_hourly_usd"] < c["old_hourly_usd"]) == (c["change"] == "down")
    rss = ET.fromstring((ROOT / "api" / "v1" / "gpu-price-changes.xml").read_text())
    assert len(rss.findall("./channel/item")) == len(doc["changes"])
    assert "commission" not in json.dumps(doc).lower() and "payout" not in json.dumps(doc).lower()


def test_price_changes_diff_logic():
    from core.gpu_changes import build_changes
    row = lambda k, p, st="ranked": {"key": k, "vendor": k, "gpu": "H100", "tier": "on-demand", "gpu_count": 1,
                                      "hourly_usd": p, "status": st, "source_url": "https://x.example/p"}
    a = {"date": "2026-01-01", "rows": [row("a", 2.0), row("b", 1.0), row("c", 3.0), row("d", 1.0, "held")]}
    b = {"date": "2026-01-02", "rows": [row("a", 1.5), row("b", 1.0), row("e", 4.0), row("d", 0.5)]}
    d = build_changes([b, a])
    assert d["previous_date"] == "2026-01-01" and d["counts"] == {"down": 1, "up": 0, "new": 2, "removed": 1}
    assert d["changes"][0]["key"] == "a" and d["changes"][0]["pct"] == -25.0


HARDCODED = re.compile(r"\b\d{2,4}\s+(?:live |verified |tracked |hourly |cited |GPU )*(?:GPU )?rates\b", re.I)


def test_no_hardcoded_rate_count_in_sources_or_docs():
    files = [p for p in (ROOT / "scripts").glob("*.py")] + [p for p in (ROOT / "core").glob("*.py")] + [
        ROOT / "README.md", ROOT / "mcp_server" / "README.md", ROOT / "mcp_server" / "server.json", ROOT / "SKILL.md",
        ROOT / ".claude-plugin" / "marketplace.json", ROOT / ".cursor-plugin" / "marketplace.json",
        ROOT / "plugins" / "lantern-works-deals" / ".claude-plugin" / "plugin.json",
        ROOT / "plugins" / "lantern-works-deals" / ".cursor-plugin" / "plugin.json"]
    bad = [(p.name, m.group(0)) for p in files if p.exists() for m in HARDCODED.finditer(p.read_text(encoding="utf-8"))]
    assert not bad, bad


def test_rendered_rate_counts_all_equal_live_count():
    live = _live()
    seen = 0
    for p in ROOT.rglob("*.html"):
        if ".git" in p.parts or "changelog" in p.parts:
            continue
        t = p.read_text(encoding="utf-8")
        for m in HARDCODED.finditer(re.sub(r"<[^>]+>", "", t)):
            seen += 1
            assert int(re.match(r"\d+", m.group(0)).group(0)) == live, (p, m.group(0))
        for v in re.findall(r"<span data-live-count>(\d+)</span>", t):
            seen += 1
            assert int(v) == live, p
    assert seen >= 3


def test_stack_optimizer_gpu_default_with_toggle():
    t = (ROOT / "tools" / "stack-optimizer" / "index.html").read_text()
    form = t.split('<form id="opt"')[1].split("</form>")[0]
    visible, more = form.split('<fieldset id="more"')
    assert 'id="n-gpu_hours"' in visible
    for k in ("scrape_pages", "proxy_gb", "emails_sent", "search_queries"):
        assert f'id="n-{k}"' in more and f'id="n-{k}"' not in visible
    assert " hidden " in more[:120] and 'id="showmore"' in visible
    assert '<details id="more-needs">' in t and "<details id=\"more-needs\" open" not in t


def test_mcp_tool_order_and_docs_lead_with_gpu():
    import asyncio
    from mcp_server import server
    names = [t.name for t in asyncio.run(server.mcp.list_tools())]
    assert names[0] == "compare_gpu_prices" and names[-3:] == ["search_deals", "compare_deals", "get_deal"]
    for f in ("README.md", "mcp_server/README.md"):
        t = (ROOT / f).read_text()
        rows = re.findall(r"^\| `(\w+)` \|", t, re.M)
        assert rows[0] == "compare_gpu_prices" and rows[-3:] == ["search_deals", "compare_deals", "get_deal"], f
        assert t.find("compare_gpu_prices") < t.find("search_deals"), f
    for f in (".claude-plugin/marketplace.json", ".cursor-plugin/marketplace.json"):
        d = json.loads((ROOT / f).read_text())["plugins"][0]["description"]
        assert d.find("compare_gpu_prices") < d.find("search_deals") and "Some result links are referral links" in d
    for f in ("plugins/lantern-works-deals/.claude-plugin/plugin.json", "plugins/lantern-works-deals/.cursor-plugin/plugin.json"):
        d = json.loads((ROOT / f).read_text())["description"]
        assert d.startswith("GPU rental price comparison") and "Some result links are referral links" in d
    assert "GPU" in json.loads((ROOT / "mcp_server" / "server.json").read_text())["description"].split(";")[0]


def test_install_page_headlines_price_monitor():
    t = (ROOT / "install" / "index.html").read_text()
    assert re.search(r"<h1>(.*?)</h1>", t).group(1) == "GPU price monitor for your agent"
    head = t.split("<h1>")[1][:2500]
    assert "/api/v1/gpu-price-changes.json" in head and "gpu-price-monitor" in head and "include_history" in head
