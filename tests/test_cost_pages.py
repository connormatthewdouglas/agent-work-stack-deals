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
    # 0.3.27: unlabelled A100 80GB now has 4+ vendors (Thunder, Jarvislabs, Civo, E2E) so it is its own compared table, never mixed with SXM/PCIe
    sec = s.split("<h2>A100 80GB</h2>")[1].split("</table>")[0]
    assert "Thunder Compute" in sec and "Civo" in sec and "SXM" not in sec and "Hyperstack A100 NVLink 80GB" in s
    assert "Hyperstack H100 NVLink 80GB" in _page("h100", 100)


def test_ovh_marked_ex_tax_and_index_page_linked():
    assert "OVHcloud (US) (excl. tax/VAT)" in _page("l40s", 100)
    assert (ROOT / "cost/index.html").is_file() and "/cost/</loc>" in (ROOT / "sitemap.xml").read_text()
    assert 'href="https://thelanternworks.com/cost/"' in (ROOT / "gpu/index.html").read_text()


def test_rtx4090_has_cheapest_line_with_3_plus_vendors():
    import json
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    ok = {r["advertiser"] for r in feed["rates"] if r["gpu"] == "RTX 4090" and r["tier_class"] == "on-demand"
          and not r["interruptible"] and r["availability"].get("in_stock") is not False}
    assert len(ok) >= 3
    for h in (10, 100, 730):
        sec = _page("rtx-4090", h).split("<h2>RTX 4090 24GB</h2>")[1].split("</p>")[0]
        assert "Cheapest RTX 4090 24GB among tracked providers:" in sec and "No &#x27;cheapest" not in sec



def test_h1_scoped_cheapest_and_page_lowest():
    a = _page("a100", 100)
    assert "Cheapest among tracked providers" not in a
    assert "Cheapest A100 SXM 80GB among tracked providers: CloudRift at $105.00" in a
    assert ("Lowest on-demand A100 on this page (not marked out of stock): Jarvislabs A100 40GB (variant not stated) at "
            "$8.90 / $89.00 / $649.70") in a
    for slug in ("h100", "l40s"):
        assert "on this page (not marked out of stock)" in _page(slug, 10)
    assert "CloudRift L40S 48GB at $6.30" in _page("l40s", 10)


def test_h2_availability_wording_all_pages():
    for slug in ("h100", "a100", "l40s", "rtx-4090"):
        for h in (10, 100, 730):
            assert "Not an availability claim, except rows marked out of stock when checked." in _page(slug, h)


def test_i1_rtx4090_page_lowest_line_from_feed():
    for h in (10, 100, 730):
        s = _page("rtx-4090", h)
        assert "only 2" not in s and "No &#x27;cheapest" not in s
    assert ("Lowest on-demand RTX 4090 on this page (not marked out of stock): Nova Cloud and RunC.AI (tie) RTX 4090 24GB at "
            "$4.20 / $42.00 / $306.60 (10 / 100 / 730 h)") in _page("rtx-4090", 100)
    assert "Lowest in-stock" not in "".join(_page(g, 100) for g in ("a100", "h100", "l40s", "rtx-4090"))
    assert "static page label" in (ROOT / "gpu/rtx-4090/index.html").read_text() if (ROOT / "gpu/rtx-4090/index.html").exists() else True


def test_j_site_wording():
    for g in ("a100", "h100"):
        for h in (10, 100, 730):
            s = _page(g, h)
            assert "only in-stock vendor" not in s
    assert "only vendor not marked out of stock for their exact" in _page("h100", 100) + _page("a100", 100)
    inst = (ROOT / "install/index.html").read_text()
    from core.deals import VERSION
    assert inst.count("version 0.3.23") == inst.count("history: tested on version 0.3.23") and f"current version {VERSION}" in inst
    cheap = (ROOT / "gpu/cheapest-rtx-4090-rental/index.html").read_text()
    assert "Nova Cloud and RunC.AI (tie) RTX 4090" in cheap
    exp = "Where a status is shown, it is a snapshot from the time in the row, not a guarantee."
    for p in ("gpu/price-comparison/index.html", "gpu/cheapest-rtx-4090-rental/index.html", "tools/gpu-cost-calculator/index.html"):
        t = (ROOT / p).read_text()
        assert "separate later check" not in t and "separate, later check" not in t
    assert exp in (ROOT / "gpu/price-comparison/index.html").read_text()
    assert exp in (ROOT / "lanternworks/index.html").read_text()
    import glob
    specs = [open(f).read() for f in glob.glob(str(ROOT / "gpu/*/index.html"))]
    assert any("vendor-labelled" in t and exp in t for t in specs)


def test_j3_page_ties_match_mcp_rule():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import gpu_pages as gp
    class G:
        esc = staticmethod(lambda s: s)
    base = {"gpu": "X", "tier_class": "on-demand", "hourly_equiv_usd": 0.42}
    rows = [{**base, "advertiser": "B"}, {**base, "advertiser": "A"}, {**base, "advertiser": "C", "hourly_equiv_usd": 0.5}]
    assert gp._tied_names(G, rows, rows[0]) == "A and B (tie)"
    assert gp._tied_names(G, rows[2:], rows[2]) == "C"


def test_j5_explainer_not_doubled():
    import glob
    for f in glob.glob(str(ROOT / "gpu/*/index.html")):
        assert "Where a status is shown, Where" not in open(f).read()


def test_0327_new_h100_a100_rows_live_and_sourced():
    import json
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    want = {("Jarvislabs", "H100"), ("Civo", "H100"), ("Oblivus", "H100"), ("E2E Networks", "H100"),
            ("Jarvislabs", "A100"), ("Civo", "A100"), ("Oblivus", "A100"), ("E2E Networks", "A100"), ("CloudRift", "A100")}
    got = {(r["advertiser"], r["gpu"].split()[0]) for r in feed["rates"]}
    assert want <= got
    for r in feed["rates"]:
        if r["advertiser"] in {"Jarvislabs", "Civo", "Oblivus", "E2E Networks"}:
            assert r["region"] and not r["interruptible"] and r["tier_class"] == "on-demand"
            if r["advertiser"] != "Oblivus":
                assert r["availability"]["in_stock"] is None
    ob = [r for r in feed["rates"] if r["advertiser"] == "Oblivus"]
    assert ob and all(r["availability"]["in_stock"] is (int(r["availability"]["stock_level"]) > 0) for r in ob)
    for r in ob:  # J6: quote and stock count from the same capture
        a = r["availability"]
        assert a["same_capture_as_price"] and a["checked_at"] == r["verified_at"]
        assert f"Available Stock {a['stock_level']} " in r["evidence"]["quote"] and "(count shown on the vendor page, changes often)" in a["detail"]
    for slug in ("h100", "a100"):
        s = _page(slug, 100)
        for v in ("Jarvislabs", "Civo", "Oblivus", "E2E Networks"):
            assert v in s
    assert "Massed Compute" not in _page("h100", 100)


def test_0327_old_note_cleared_and_tie_rule_shared():
    old = "Stock changes within minutes"
    for f in ("api/v1/gpu-prices.json", "api/v1/gpu/a100.json", "api/v1/gpu/h100.json", "api/v1/gpu/rtx-4090.json",
              "tools/gpu-cost-calculator/index.html"):
        assert old not in (ROOT / f).read_text(), f
    from core import gpu_availability as ga
    assert ga.NOTE == ga.STOCK_EXPLAINER and ga.NOTE.startswith("Where a status is shown")
    import core.deals as d, scripts.gpu_pages as gp
    assert gp.tie_label is d.tie_label
    rows = [{"advertiser": "A", "gpu": "H100", "tier": "On-demand", "hourly_equiv_usd": 2.0, "availability": {}},
            {"advertiser": "B", "gpu": "H100", "tier": "On-demand", "hourly_equiv_usd": 2.0, "availability": {}}]
    assert d.tie_label(rows, rows[0]) == "A and B (tie)"


def test_j7_regions_cite_supporting_urls():
    import json
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    reg = {r["advertiser"]: r["region"] for r in feed["rates"] if r["advertiser"] in {"E2E Networks", "Civo", "Jarvislabs", "Oblivus"}}
    assert "https://www.e2enetworks.com/pricing.md" in reg["E2E Networks"] and "INR" not in reg["E2E Networks"]
    assert "https://www.civo.com/docs/overview/regions" in reg["Civo"] and "MON1" in reg["Oblivus"] and "India" in reg["Jarvislabs"]


def test_j8_cheapest_a100_summary_names_memory_sizes():
    s = (ROOT / "gpu/cheapest-a100-rental/index.html").read_text()
    assert ("cheapest <strong>on-demand</strong> among tracked providers: Jarvislabs A100 40GB (On-demand) at $89.00 \u2014 memory sizes differ; "
            "cheapest A100 80GB among tracked providers: Thunder Compute at $109.00") in s


def test_index_a100_is_80gb_only():
    import json
    idx = json.loads((ROOT / "api/v1/gpu-price-index.json").read_text())
    assert idx["series_vram_gb"]["A100"] == 80
    import sys; sys.path.insert(0, str(ROOT / "scripts")); import gpu_index
    assert gpu_index.series_of({"gpu": "A100", "vram_gb": 40}) is None and gpu_index.series_of({"gpu": "A100", "vram_gb": 80}) == "A100"
    assert gpu_index.series_of({"gpu": "A100", "vram_gb": None}) is None
    assert "A100 series is 80 GB only" in (ROOT / "docs/GPU-INDEX-METHODOLOGY.md").read_text()
