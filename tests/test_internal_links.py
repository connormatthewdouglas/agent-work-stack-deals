"""Internal-link check over the generated site output (gates deploy via the `tests` CI job)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import check_internal_links  # noqa: E402
from core.stack import deal_page_url  # noqa: E402


def test_no_broken_internal_links():
    bad = check_internal_links.check()
    assert not bad, "broken internal links:\n" + "\n".join(bad)


def test_gpu_hub_exists_and_in_sitemap():
    hub = (ROOT / "gpu" / "index.html").read_text(encoding="utf-8")
    for target in ("/tools/gpu-cost-calculator/", "/gpu/price-comparison/", "/gpu/cheapest-h100-rental/",
                   "/categories/gpu-compute/", "/api/v1/gpu-prices.json"):
        assert target in hub, target
    assert "<loc>https://thelanternworks.com/gpu/</loc>" in (ROOT / "sitemap.xml").read_text(encoding="utf-8")


def test_checker_flags_missing_target():
    assert check_internal_links.resolve("/gpu/")
    assert not check_internal_links.resolve("/definitely-not-a-page/")
    assert check_internal_links.internal_path("https://example.com/x", "index.html") is None


def test_deal_page_url_matches_generated_pages():
    url = deal_page_url("deal-exa-001")
    assert url == "https://thelanternworks.com/deals/exa-001/"
    assert (ROOT / "deals" / "exa-001" / "index.html").exists()
    assert deal_page_url(None) is None
