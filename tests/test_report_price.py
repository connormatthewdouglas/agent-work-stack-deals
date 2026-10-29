"""T40: static wrong-price report flow (prefilled GitHub issue form; no server)."""
import re, sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import report_price_page as rp  # noqa: E402


def test_issue_template_ids_match_page_fields():
    tpl = (ROOT / ".github" / "ISSUE_TEMPLATE" / rp.TEMPLATE).read_text(encoding="utf-8")
    ids = set(re.findall(r"^\s+id: (\w+)", tpl, re.M))
    assert set(rp.FIELDS) <= ids
    for need in ("vendor", "gpu", "shown_price", "observed_price", "source_url"):
        assert need in ids


def test_issue_url_prefills():
    u = rp.issue_url(vendor="RunPod", gpu="H100 SXM 80 GB · On-demand", shown_price="2.69", observed_price="2.99/hr", source_url="https://x")
    q = parse_qs(urlparse(u).query)
    assert q["template"] == [rp.TEMPLATE] and q["vendor"] == ["RunPod"] and q["shown_price"] == ["2.69"]


def test_page_built_reads_live_feed_no_baked_prices():
    s = (ROOT / rp.PATH / "index.html").read_text(encoding="utf-8")
    assert "/api/v1/gpu-prices.json" in s and "issues/new" in s and "Frosty" not in s and "Connor" not in s
    body = s.split("<h1>", 1)[1]
    assert not re.search(r"\$\d", body)
    assert "/report-price/" in (ROOT / "sitemap.xml").read_text(encoding="utf-8")
