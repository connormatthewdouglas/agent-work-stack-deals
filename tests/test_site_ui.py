"""Static homepage search/filter/compare markup and shared site navigation."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV = ["/deals/", "/ai-agent-tool-deals/", "/gpu/price-comparison/", "/tools/gpu-cost-calculator/", "/install/", "/for-agents/"]


def test_homepage_filters_are_progressive_and_cards_carry_public_attrs():
    t = (ROOT / "deals" / "index.html").read_text()
    assert '<form id="filters" role="search"' in t and " hidden " in t.split('<form id="filters"')[1][:120]
    assert "<noscript>" in t and 'id="cmp-view"' in t
    cards = re.findall(r'<article class="deal"[^>]*>', t)
    assert len(cards) > 50
    for c in cards:
        for a in ("data-offer=", "data-price=", "data-free=", "data-verified=", "data-category="):
            assert a in c, c
    assert "commission" not in " ".join(cards).lower() and "payout" not in " ".join(cards).lower()


def test_site_nav_everywhere():
    pages = [ROOT / "index.html"] + [ROOT / p / "index.html" for p in (
        "deals", "for-agents", "install", "gpu/price-comparison", "tools/gpu-cost-calculator", "ai-agent-tool-deals",
        "compare/cheap-gpu-rental", "categories/proxies", "changelog")]
    for p in pages:
        t = p.read_text()
        nav = t.split('<nav class="sitenav"')[1].split("</nav>")[0]
        for href in NAV:
            assert href in nav, (p, href)
        assert nav.count('aria-current=') == 1, p
        assert 'id="content"' in t, p


def test_measurement_is_cookieless_and_aggregate():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import site_ui
    js = site_ui.TRACK_JS.lower()
    for bad in ("cookie", "localstorage", "sessionstorage", "fetch(", "xmlhttprequest", "sendbeacon", "f-q\").value"):
        assert bad not in js, bad
    home = (ROOT / "deals" / "index.html").read_text()
    assert "history.replacestate" not in home.lower()  # URL rewrites would count as extra page views
    ids = set(re.findall(r'data-deal="([^"]+)"', home))
    assert ids and all(re.fullmatch(r"[a-z0-9-]+", i) for i in ids)
    assert "Disallow: /e/" in (ROOT / "robots.txt").read_text()
    assert "cloudflareinsights" not in (ROOT / "404.html").read_text()


def test_homepage_lists_every_published_deal():
    import json
    feed = json.loads((ROOT / "deals.json").read_text())["deals"]
    home = (ROOT / "deals" / "index.html").read_text()
    assert len(re.findall(r'<article class="deal"', home)) == len([d for d in feed if not d.get("example")])
