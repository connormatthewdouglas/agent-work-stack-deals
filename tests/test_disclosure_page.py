"""Public /disclosure/ page exists and names commissions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_disclosure_page_exists_and_mentions_commission():
    path = ROOT / "disclosure" / "index.html"
    assert path.is_file()
    s = path.read_text(encoding="utf-8")
    assert "commission" in s
    assert "Lantern Works" in s
    assert "Frosty" not in s
    assert "/disclosure/" in (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    assert "https://thelanternworks.com/methodology/#placement" in s
    assert "not offered" in s


def test_homepage_footer_links_disclosure_and_says_commission():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    footer = html.split("<footer>")[1]
    assert "commission" in footer
    assert 'href="https://thelanternworks.com/disclosure/"' in footer
