import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cost_pages  # noqa: E402

FEED = json.loads((ROOT / "api/v1/gpu-prices.json").read_text(encoding="utf-8"))


def test_twelve_pages_in_sitemap():
    sm = (ROOT / "sitemap.xml").read_text()
    for slug in cost_pages.GPUS:
        for h in cost_pages.HOURS:
            assert (ROOT / f"cost/{slug}-{h}-hours/index.html").is_file()
            assert f"/cost/{slug}-{h}-hours/" in sm


def test_eligibility_fails_closed():
    held = {h["vendor"] for h in FEED["held_stale"]}
    for fam in cost_pages.GPUS.values():
        for (gpu, vram), rows in cost_pages.eligible(FEED, fam).items():
            for r in rows:
                assert r["tier_class"] == "on-demand" and not r["interruptible"] and (r.get("min_gpus") or 1) == 1
                assert r["advertiser"] not in held and r["billing_unit"] in ("hourly", "per-second")
                assert r["gpu"] == gpu and r["vram_gb"] == vram


def test_pages_math_and_exclusions():
    for p in (ROOT / "cost").glob("*/index.html"):
        s = p.read_text(encoding="utf-8")
        assert "TensorDock" not in s and "Clore" not in s and "Compute subtotal only" in s
        h = int(re.search(r"-(\d+)-hours", str(p)).group(1))
        for rate, sub in re.findall(r'\$/GPU-hr">\$([\d.]+)</td><td data-label="\d+ h subtotal"><strong>\$([\d,.]+)', s):
            assert abs(round(float(rate) * h, 2) - float(sub.replace(",", ""))) < 0.006


def _page(slug, h):
    return (ROOT / f"cost/{slug}-{h}-hours/index.html").read_text(encoding="utf-8")


def test_out_of_stock_ranked_last_and_excluded():
    s = _page("a100", 100)
    assert "stock is not checked here" not in s
    # A100 SXM 40GB: Verda $1.593 is out of stock, so Lambda $199.00 is the only in-stock row and comes first
    sec = s.split("Other variants (not compared)")[1].split("</ul>")[0]
    assert "Lambda A100 SXM 40GB" in sec and "$199.00 for 100 h" in sec
    assert sec.index("Lambda A100 SXM 40GB") < sec.index("Verda (formerly DataCrunch) A100 SXM 40GB")
    assert "out of stock when checked at" in sec.split("Verda (formerly DataCrunch) A100 SXM 40GB")[1].split("</li>")[0]
    h = _page("h100", 100).split("<h2>H100 SXM 80GB</h2>")[1].split("</table>")[0]
    assert h.rindex("<tr>") < h.index("Verda") and "$474.60" not in h.split("</p>")[0]


def test_unlabelled_and_nvlink_variants_named_not_mixed():
    s = _page("a100", 100)
    assert "Other variants (not compared)" in s and "Thunder Compute A100 80GB" in s and "Hyperstack A100 NVLink 80GB" in s
    assert "Hyperstack H100 NVLink 80GB" in _page("h100", 100)


def test_ovh_marked_ex_tax_and_index_page_linked():
    assert "OVHcloud (US) (excl. tax/VAT)" in _page("l40s", 100)
    assert (ROOT / "cost/index.html").is_file() and "/cost/</loc>" in (ROOT / "sitemap.xml").read_text()
    assert 'href="https://thelanternworks.com/cost/"' in (ROOT / "gpu/index.html").read_text()


def test_rtx4090_explains_missing_cheapest_line():
    s = _page("rtx-4090", 100)
    sec = s.split("<h2>RTX 4090 24GB</h2>")[1].split("</p>")[0]
    assert "Cheapest among tracked providers" not in sec and "No 'cheapest' line: only 2 in-stock vendors" in sec
