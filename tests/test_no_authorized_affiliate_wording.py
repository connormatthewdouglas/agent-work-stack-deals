"""T5 regression: feed instructions must use neutral referral disclosure, never 'authorized affiliate link'."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHRASE = re.compile(r"authorized affiliate link", re.I)


def test_no_authorized_affiliate_wording_in_feed_or_site():
    hits = []
    for p in ROOT.rglob("*"):
        if ".git" in p.parts or "tests" in p.parts or p.suffix not in (".json", ".html", ".md", ".py", ".txt", ".xml"):
            continue
        if PHRASE.search(p.read_text(encoding="utf-8", errors="ignore")):
            hits.append(str(p.relative_to(ROOT)))
    assert not hits, f"'authorized affiliate link' wording found in: {hits[:10]}"


def test_affiliate_deals_carry_disclosure_and_plain_url():
    """T5 option B: every affiliate deal in the feed/API has the disclosure field and a plain_url key."""
    import json
    from core.disclosure import DISCLOSURE, DISCLOSURE_NO_PLAIN
    for path in (ROOT / "deals.json", ROOT / "api" / "v1" / "deals.json"):
        for d in json.loads(path.read_text(encoding="utf-8"))["deals"]:
            if not d.get("affiliate"):
                assert "disclosure" not in d and "plain_url" not in d, d["id"]
                continue
            assert "plain_url" in d, d["id"]
            assert d["disclosure"] == (DISCLOSURE if d["plain_url"] else DISCLOSURE_NO_PLAIN), d["id"]
            if d["plain_url"]:
                assert d["plain_url"].startswith("https://") and d["plain_url"] != d["redeem_url"], d["id"]


def test_affiliate_pages_show_inline_disclosure_sponsored_and_plain_link():
    """T5 option A: affiliate deal pages show the inline disclosure beside a rel=sponsored link plus the plain link."""
    import json
    deals = json.loads((ROOT / "deals.json").read_text(encoding="utf-8"))["deals"]
    aff = [d for d in deals if d.get("affiliate") and d.get("plain_url")][:20]
    assert aff
    for d in aff:
        page = ROOT / "deals" / d["id"].removeprefix("deal-") / "index.html"
        if not page.exists():
            continue
        html = page.read_text(encoding="utf-8")
        assert 'rel="nofollow sponsored"' in html, d["id"]
        assert "Lantern Works may earn a commission if you sign up through this link" in html, d["id"]
        assert "go straight to the vendor" in html and d["plain_url"].replace("&", "&amp;") in html, d["id"]
