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


def test_api_docs_page_covers_p70_expiry_and_p71_alerts():
    s = (ROOT / "api" / "index.html").read_text(encoding="utf-8")
    assert 'id="availability-expiry"' in s
    assert "still valid at the exact expiry instant" in s
    assert "equals <code>availability_expires_at</code>" in s or "equals availability_expires_at" in s
    assert "no grace period" in s and "no clock-skew tolerance" in s
    assert "current UTC time" in s
    assert 'id="price-alerts"' in s
    assert "would_have_crossed" in s
    assert "not stored" in s
    assert "new evaluation of the current price" in s
    assert "not a delayed fire" in s
    assert "data_age_hours" in s
    assert "not from <code>feed_updated_at</code>" in s
    assert "Frosty" not in s and "Connor" not in s
    fa = (ROOT / "for-agents" / "index.html").read_text(encoding="utf-8")
    assert "still valid at the exact expiry instant" in fa
    assert "no clock-skew tolerance" in fa
    assert "find_available_gpus" in fa
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "including at the exact expiry instant" in llms
    assert "no clock-skew tolerance" in llms



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


def test_api_and_for_agents_document_job_days_and_tracked_url():
    api = (ROOT / "api" / "index.html").read_text(encoding="utf-8")
    fa = (ROOT / "for-agents" / "index.html").read_text(encoding="utf-8")
    for s in (api, fa):
        assert 'id="estimate-job-cost"' in s
        assert "job_days" in s and "tracked_url" in s
        assert "wall-clock" in s
        assert "job_hours = job_days" in s or "job_hours = job_days" in s.replace("&times;", "×")
        assert "invalid_argument" in s
        assert "job_hours" in s and "job_days" in s
        assert "20,000" in s or "20000" in s
        assert "834" in s
        assert "not a reservation" in s
        assert "/go/" in s and "src=mcp" in s
        assert "lantern-works-telemetry.lantern-works.workers.dev/go/" in s
        assert "not from the caller" in s
        assert "receipt" in s.lower()
        assert "Frosty" not in s and "Connor" not in s
    assert 'href="https://thelanternworks.com/for-agents/#estimate-job-cost"' in api
    assert 'href="https://thelanternworks.com/api/#estimate-job-cost"' in fa


def test_api_and_for_agents_document_rent_here():
    api = (ROOT / "api" / "index.html").read_text(encoding="utf-8")
    fa = (ROOT / "for-agents" / "index.html").read_text(encoding="utf-8")
    for s in (api, fa):
        assert 'id="rent-here"' in s
        assert "rent_here" in s and "rent_url" in s and "tracked_url" in s
        assert "top 3" in s
        for name in ("compare_gpu_prices", "find_available_gpus", "estimate_job_cost"):
            assert f"<code>{name}</code>" in s
        assert "referral_disclosure" in s
        assert "src=mcp" in s and "/go/" in s
        assert "Frosty" not in s and "Connor" not in s
    assert 'href="https://thelanternworks.com/for-agents/#rent-here"' in api
    assert 'href="https://thelanternworks.com/api/#rent-here"' in fa

