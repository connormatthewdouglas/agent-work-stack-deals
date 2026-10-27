"""Static homepage search/filter/compare markup and shared site navigation."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV = ["/ai-agent-tool-deals/", "/gpu/price-comparison/", "/tools/gpu-cost-calculator/", "/install/", "/for-agents/"]


def test_homepage_filters_are_progressive_and_cards_carry_public_attrs():
    t = (ROOT / "index.html").read_text()
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
        "for-agents", "install", "gpu/price-comparison", "tools/gpu-cost-calculator", "ai-agent-tool-deals",
        "compare/cheap-gpu-rental", "categories/proxies", "changelog")]
    for p in pages:
        t = p.read_text()
        nav = t.split('<nav class="sitenav"')[1].split("</nav>")[0]
        for href in NAV:
            assert href in nav, (p, href)
        assert nav.count('aria-current=') == 1, p
        assert 'id="content"' in t, p
