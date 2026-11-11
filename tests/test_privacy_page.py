"""Public /privacy/ page is generated and describes the hosted daily-salted hash."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_privacy_page_exists_and_mentions_hash():
    path = ROOT / "privacy" / "index.html"
    assert path.is_file()
    s = path.read_text(encoding="utf-8")
    assert "SHA-256" in s or "sha256" in s.lower()
    assert "hash" in s.lower()
    assert "daily-salted" in s.lower() or "daily salted" in s.lower() or "salt" in s.lower()
    assert "IP" in s and "user agent" in s.lower()
    assert "Frosty" not in s
    assert "/privacy/" in (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    # footer link on the shared shell
    assert 'href="https://thelanternworks.com/privacy/">Privacy</a>' in s.split("<footer>")[1]
