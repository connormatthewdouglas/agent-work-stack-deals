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


def test_nov2_spread_paragraph_recomputes_from_cited_feed():
    """Pulse's rule: H100 SXM (form_factor SXM, any name), single GPU, on-demand, non-interruptible, vendors not held_stale."""
    import json, statistics
    feed = json.loads((ROOT / "tests/fixtures/gpu-prices-2026-11-02.json").read_text())
    assert feed["feed_updated_at"] == "2026-11-02T12:59:30Z"
    held = set(feed["held_stale_vendors"])
    rows = [r for r in feed["rates"] if (r.get("canonical_model") or r["gpu"]).startswith("H100") and r.get("form_factor") == "SXM"
            and r["tier_class"] == "on-demand" and (r.get("gpu_count") or 1) == 1 and not r.get("interruptible")
            and r["advertiser"] not in held]
    cost = sorted(round(r["hourly_equiv_usd"] * 100, 2) for r in rows)
    md = (ROOT / "data/reports/gpu-report-2026-11-02.md").read_text()
    para = md[md.index("For an H100 SXM 80GB on-demand"):].split("\n\n")[0]
    assert f"Across the {len(rows)} tracked rates" in para
    assert f"**${statistics.median(cost):.2f}** median" in para
    assert f"**${cost[0]:.2f}** at Civo" in para and f"**${cost[-1]:.2f}** at Verda" in para
    assert f"**${cost[-1] - cost[0]:.2f}** of difference" in para
    # Gauge rel053: literal values too, so the fixture and the report can't drift together
    assert len(rows) == 9 and "Across the 9 tracked rates" in para
    assert statistics.median(cost) == 399.00 and "**$399.00** median" in para


MOVED = ROOT / "reports" / "gpu-prices-that-moved-2026-11-20"
MOVED_MD = ROOT / "data/reports/gpu-prices-that-moved-2026-11-20.md"


def test_moved_report_is_listed_first_and_linked():
    t = (ROOT / "reports" / "index.html").read_text(encoding="utf-8")
    a = t.find("/reports/gpu-prices-that-moved-2026-11-20/")
    b = t.find("/reports/gpu-report-2026-11-02/")
    assert a != -1 and b != -1 and a < b
    sm = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    assert "reports/gpu-prices-that-moved-2026-11-20/</loc>" in sm
    ll = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "/reports/gpu-prices-that-moved-2026-11-20/" in ll


def test_moved_report_copy_chart_and_no_private_links():
    t = (MOVED / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://thelanternworks.com/reports/gpu-prices-that-moved-2026-11-20/" />' in t
    assert '<img src="moved-chart.svg"' in t
    assert "moves.json" in t
    assert (MOVED / "moved-chart.svg").is_file()
    assert (MOVED / "moves.json").is_file()
    assert "creativecommons.org/licenses/by/4.0/" in t and "CC BY 4.0" in t
    assert "may earn a commission" in t
    assert "None of the five rows above carries a referral link" in t
    assert "2026-11-22T03:09:50Z" in t
    assert "Frosty" not in t and "Connor" not in t
    assert not re.search(r"github\.com|connormatthewdouglas|/workspace/", t, re.I)
    # top-5 figures in the rendered page
    assert "$12.2900" in t and "$13.0500" in t and "+6.2%" in t
    assert "Verda (formerly DataCrunch)" in t
    assert "A100 SXM 40GB" in t and "A100 SXM 80GB" in t


def test_moved_report_recomputes_from_cited_live_fixture():
    import json, sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import gpu_moved_report as g
    fx = json.loads((ROOT / "tests/fixtures/gpu-moved-2026-11-20.json").read_text(encoding="utf-8"))
    fig = g.figures(fx["current"], fx["history"], fx["start"], fx["end"])
    assert fig["feed_updated_at"] == "2026-11-22T03:09:50Z"
    assert fig["n_moved"] == 24
    assert fig["top5"][0]["gpu"] == "B300" and fig["top5"][0]["pct"] == 6.2
    assert fig["top5"][0]["old"] == 12.29 and fig["top5"][0]["new"] == 13.05
    assert all(r["vendor"] == "Verda (formerly DataCrunch)" for r in fig["rows"])
    assert all(r["new"] > r["old"] for r in fig["rows"])
    assert min(r["pct"] for r in fig["rows"]) == 2.5
    assert max(r["pct"] for r in fig["rows"]) == 6.2
    assert all(r.get("referral") is None for r in fig["top5"])
    saved = json.loads((ROOT / "data/reports/gpu-prices-that-moved-2026-11-20/figures.json").read_text(encoding="utf-8"))
    slim = {k: fig[k] for k in ("feed_updated_at", "start", "end", "n_moved", "held_vendors", "top5")}
    assert saved == slim
    md = MOVED_MD.read_text(encoding="utf-8")
    html = (MOVED / "index.html").read_text(encoding="utf-8")
    for r in fig["top5"]:
        for tok in (g._pct(r["pct"]), g._usd(r["old"]), g._usd(r["new"]), r["vendor"], r["source_url"]):
            assert tok in md and tok in html
    assert fig["feed_updated_at"] in md and fig["feed_updated_at"] in html
