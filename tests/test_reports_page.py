import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "reports" / "gpu-report-2026-11-02" / "index.html"


def test_report_page_canonical_disclosure_license_and_no_private_links():
    t = R.read_text()
    assert '<link rel="canonical" href="https://thelanternworks.com/reports/gpu-report-2026-11-02/" />' in t
    assert "Disclosure: some vendor links on Lantern Works are referral/affiliate links" in t
    assert "creativecommons.org/licenses/by/4.0/" in t and "CC BY 4.0" in t
    assert not re.search(r"github\.com|connormatthewdouglas|/workspace/", t, re.I)


def test_report_links_new_gpu_pages_and_is_listed():
    t = R.read_text()
    for s in ("b300", "mi300x", "l4"):
        assert (ROOT / "gpu" / f"{s}-rental-price" / "index.html").exists()
        assert f"/gpu/{s}-rental-price/" in t
    sm = (ROOT / "sitemap.xml").read_text()
    assert "https://thelanternworks.com/reports/</loc>" in sm and "reports/gpu-report-2026-11-02/</loc>" in sm
    ll = (ROOT / "llms.txt").read_text()
    assert "/reports/gpu-report-2026-11-02/" in ll and "/gpu/mi300x-rental-price/" in ll


def test_report_text_is_verbatim():
    md = (ROOT / "data/reports/gpu-report-2026-11-02.md").read_text()
    t = re.sub(r"<[^>]+>", "", R.read_text()).replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&")
    for line in ("Verda moved all 24 of its tracked rates up by 0.8% to 1.0%", "2 down, 27 up, 2 new, 1 removed."):
        assert line in md and line in t
