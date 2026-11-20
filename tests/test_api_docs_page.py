"""Public /api/ docs page exists and states live-checked API facts."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_seo_pages as g  # noqa: E402


def test_api_docs_page_exists_and_covers_public_api():
    path = ROOT / "api" / "index.html"
    assert path.is_file()
    s = path.read_text(encoding="utf-8")
    assert "Lantern Works" in s
    assert "Frosty" not in s
    assert "Connor" not in s
    assert "/api/v1/gpu-prices.json" in s
    assert "https://lantern-works-mcp.lantern-works.workers.dev/mcp" in s
    assert "Streamable HTTP" in s
    assert "No API key is required" in s
    assert "Access-Control-Allow-Origin: *" in s
    assert "no published rate limit" in s
    assert "CC BY 4.0" in s
    assert 'href="https://thelanternworks.com/methodology/"' in s
    assert 'href="https://thelanternworks.com/privacy/"' in s
    assert 'href="https://thelanternworks.com/disclosure/"' in s
    assert "<loc>https://thelanternworks.com/api/</loc>" in (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    # Docs live at /api/index.html beside, not instead of, the JSON feeds.
    assert (ROOT / "api" / "v1" / "gpu-prices.json").is_file()


def test_redeem_url_plain_words_do_not_say_the_the():
    assert g.plain_words("Sign up via the redeem_url for proxies.") == "Sign up via the sign-up link for proxies."
    assert g.plain_words("Open the redeem_url link and get a free API key.") == "Open the sign-up link and get a free API key."
    assert "the the" not in g.plain_words("Start on the free plan via the redeem_url affiliate link.")
    assert "sign-up link link" not in g.plain_words("Open the redeem_url link and get a free API key.")


def test_trueproxies_disclosure_names_vendor_once():
    html = (ROOT / "deals" / "trueproxies-001" / "index.html").read_text(encoding="utf-8")
    assert "Lantern Works may earn a commission if you sign up through this TrueProxies link." in html
    assert "this link from TrueProxies" not in html
    assert "; we may earn a commission from TrueProxies." not in html
