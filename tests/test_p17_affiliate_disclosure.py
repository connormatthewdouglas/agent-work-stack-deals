"""P17 / Brain #1200: disclosure sits next to affiliate links; InboxKit and Runable use plain URLs."""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.deals import PUBLIC_FIELDS, compare, get_deal, public_view, search

ROOT = Path(__file__).resolve().parents[1]
INBOXKIT_ID = "deal-inboxkit-001"
RUNABLE_ID = "deal-runable-001"
INBOXKIT_PLAIN = "https://www.inboxkit.com/pricing"
RUNABLE_PLAIN = "https://runable.com"
# Concatenated so this file does not itself contain the retired affiliate URLs as literals.
INBOXKIT_AFFILIATE = "https://inboxkit.com" + "?fpr=lanternworks"
RUNABLE_AFFILIATE = "https://runable.link" + "/lantern-works"
CTA_RE = re.compile(
    r'<a class="cta" rel="nofollow sponsored" href="(?P<href>[^"]+)" data-deal="(?P<id>[^"]+)">'
    r"Redeem / signup</a>"
    r"(?P<extra>(?: · code <code>[^<]+</code>| · <em>[^<]+</em>)*)"
    r'<br><small class="disclosure">(?P<disc>.*?)</small>',
    re.S,
)
COMMISSION = "Lantern Works may earn a commission if you sign up through this"
RANKING = ("does not change the price or ranking", "never changes the price or ranking")


def _deals(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["deals"]


def _by_id(path: Path, deal_id: str) -> dict:
    return next(d for d in _deals(path) if d["id"] == deal_id)


def test_inboxkit_and_runable_are_plain_non_affiliate_listings():
    expected = {
        INBOXKIT_ID: (INBOXKIT_PLAIN, "InboxKit — Google Workspace & Microsoft 365 mailbox infrastructure for cold email, with API & MCP"),
        RUNABLE_ID: (RUNABLE_PLAIN, "Runable — general-purpose AI agent"),
    }
    for path in (ROOT / "deals.json", ROOT / "api" / "v1" / "deals.json"):
        for deal_id, (plain, title) in expected.items():
            d = _by_id(path, deal_id)
            assert d["affiliate"] is False, (path, deal_id)
            assert d["redeem_url"] == plain, (path, deal_id, d["redeem_url"])
            assert d["title"] == title
            assert "(affiliate)" not in d["title"]
            assert "affiliate" not in (d.get("tags") or [])
            assert "disclosure" not in d and "plain_url" not in d, deal_id
            assert "firstpromoter" not in (d.get("tags") or [])


def test_retired_affiliate_urls_are_gone_from_live_surfaces():
    forbidden = (INBOXKIT_AFFILIATE, RUNABLE_AFFILIATE)
    skip_parts = {".git", ".venv", "venv-tests", "__pycache__", "node_modules"}
    hits = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(part in skip_parts for part in p.parts):
            continue
        if p.suffix.lower() not in {".json", ".html", ".md", ".py", ".txt", ".xml", ".js", ".csv"}:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for url in forbidden:
            if url in text:
                hits.append(f"{p.relative_to(ROOT)}: {url}")
    assert not hits, "retired affiliate URLs still present:\n" + "\n".join(hits[:20])


def test_every_affiliate_deal_page_has_disclosure_immediately_after_the_cta():
    deals = [d for d in _deals(ROOT / "deals.json") if d.get("affiliate")]
    assert deals
    missing, bad = [], []
    for d in deals:
        page = ROOT / "deals" / d["id"].removeprefix("deal-") / "index.html"
        if not page.is_file():
            missing.append(d["id"])
            continue
        html = page.read_text(encoding="utf-8")
        matches = list(CTA_RE.finditer(html))
        if len(matches) != 1 or matches[0].group("id") != d["id"] or matches[0].group("href") != d["redeem_url"].replace("&", "&amp;"):
            bad.append(d["id"] + " (cta/adjacency)")
            continue
        disc = matches[0].group("disc")
        if COMMISSION not in disc or not any(s in disc for s in RANKING):
            bad.append(d["id"] + " (wording)")
            continue
        if (d.get("advertiser") or "").strip().lower() == "trueproxies" and "this TrueProxies link" not in disc:
            bad.append(d["id"] + " (TrueProxies vendor name)")
            continue
        if d.get("plain_url"):
            if "go straight to the vendor" not in disc or d["plain_url"].replace("&", "&amp;") not in disc:
                bad.append(d["id"] + " (plain_url)")
    assert not missing, f"missing deal pages: {missing[:10]}"
    assert not bad, f"disclosure not immediately next to the affiliate CTA: {bad[:10]}"


def test_inboxkit_and_runable_pages_use_plain_links_without_affiliate_disclosure():
    for deal_id, plain in ((INBOXKIT_ID, INBOXKIT_PLAIN), (RUNABLE_ID, RUNABLE_PLAIN)):
        page = ROOT / "deals" / deal_id.removeprefix("deal-") / "index.html"
        html = page.read_text(encoding="utf-8")
        assert f'rel="noopener noreferrer" href="{plain}"' in html
        assert 'rel="nofollow sponsored"' not in html
        assert "Affiliate link:" not in html
        assert INBOXKIT_AFFILIATE not in html and RUNABLE_AFFILIATE not in html


def test_mcp_public_output_carries_disclosure_next_to_affiliate_links():
    assert "disclosure" in PUBLIC_FIELDS and "plain_url" in PUBLIC_FIELDS
    deals = _deals(ROOT / "api" / "v1" / "deals.json")
    aff = next(d for d in deals if d.get("affiliate") and d.get("disclosure") and d.get("plain_url"))
    view = public_view(aff)
    assert view["redeem_url"] == aff["redeem_url"]
    assert view["disclosure"] == aff["disclosure"]
    assert view["plain_url"] == aff["plain_url"]
    got = get_deal(deals, aff["id"])
    assert got["disclosure"] == aff["disclosure"] and got["plain_url"] == aff["plain_url"]
    found = next(r for r in search(deals, query=aff["advertiser"], limit=25)["results"] if r["id"] == aff["id"])
    assert found["redeem_url"] == aff["redeem_url"]
    assert found["disclosure"] == aff["disclosure"] and found["plain_url"] == aff["plain_url"]
    other = next(d["id"] for d in deals if d["id"] != aff["id"])
    row = next(d for d in compare(deals, [aff["id"], other])["deals"] if d["id"] == aff["id"])
    assert row["disclosure"] == aff["disclosure"] and row["plain_url"] == aff["plain_url"]
    for deal_id in (INBOXKIT_ID, RUNABLE_ID):
        g = get_deal(deals, deal_id)
        assert g["affiliate"] is False
        assert "disclosure" not in g and "plain_url" not in g
