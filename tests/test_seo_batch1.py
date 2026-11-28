"""SEO batch 1: weekly cheapest-H100/L40S/A100 pages and the LoRA fine-tune cost page."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from seo_batch1_compute import build_figures, fmt_usd_mul  # noqa: E402
from seo_batch1_pages import PAGE_SPECS, page_markdown  # noqa: E402

FAMILY_PAGES = {
    "H100": ROOT / "reports" / "cheapest-h100-week-of-2026-11-23" / "index.html",
    "L40S": ROOT / "reports" / "cheapest-l40s-week-of-2026-11-23" / "index.html",
    "A100": ROOT / "reports" / "cheapest-a100-week-of-2026-11-23" / "index.html",
}
COST_PAGE = ROOT / "cost" / "fine-tune-7b-8b-lora" / "index.html"
FORBIDDEN = re.compile(
    r"github\.com/connor|connormatthewdouglas|Frosty Condor|Connor Douglas|/workspace/|/home/",
    re.I,
)
HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/mcp"


def _figs():
    return build_figures()


def test_pages_exist_with_canonical_slugs_and_titles():
    figs = _figs()
    week = figs["week_label"]
    expected = {
        "H100": f"Cheapest H100 rental this week ({week})",
        "L40S": f"Cheapest L40S rental this week ({week})",
        "A100": f"Cheapest A100 rental this week ({week})",
    }
    for fam, path in FAMILY_PAGES.items():
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        title = expected[fam]
        slug = figs["slugs"][fam]
        assert f'<link rel="canonical" href="https://thelanternworks.com{slug}" />' in text
        assert f"<h1>{title}</h1>" in text
        assert f"<title>{title} | Lantern Works</title>" in text
    assert COST_PAGE.is_file()
    cost = COST_PAGE.read_text(encoding="utf-8")
    title = "Cost to fine-tune a 7B or 8B model (LoRA, e.g. Llama 3.1 8B)"
    assert '<link rel="canonical" href="https://thelanternworks.com/cost/fine-tune-7b-8b-lora/" />' in cost
    assert f"<h1>{title}</h1>" in cost
    assert f"<title>{title} | Lantern Works</title>" in cost


def test_figures_recompute_from_live_feed_and_appear_on_pages():
    figs = _figs()
    for fam, path in FAMILY_PAGES.items():
        text = path.read_text(encoding="utf-8")
        data = figs["families"][fam]
        od = data["cheapest_on_demand_single"]
        assert figs["feed_updated_at_et"] in text
        assert f"{data['rate_count']} ranked {fam} rates" in text
        assert f"{data['vendor_count']} vendors" in text
        assert f"{od['price']}/GPU-hr" in text
        assert od["vendor"] in text
        assert od["verified_et"] in text
        assert od["source_url"] in text
        assert fmt_usd_mul(od["price_usd"], 100) in text
        assert "cheapest among tracked providers" in text.lower()
        assert "GPU-hour price only" in text
        assert "CC BY 4.0" in text
        assert "America/New_York" in text
        assert figs["live_pages"][fam] in text
        if data["cheapest_spot_single"]:
            spot = data["cheapest_spot_single"]
            assert f"{spot['price']}/GPU-hr" in text
            assert spot["vendor"] in text
            assert spot["verified_et"] in text
            assert spot["source_url"] in text
        if fam == "H100":
            sxm = data["extras"]["cheapest_on_demand_sxm"]
            assert sxm["price"] + "/GPU-hr" in text
            assert sxm["vendor"] in text
            assert "In all 6 daily snapshots" in text
        if fam == "A100":
            od80 = data["extras"]["cheapest_on_demand_80gb"]
            assert od80["price"] + "/GPU-hr" in text
            assert od80["vendor"] in text
            assert "40 GB" in text
        if fam == "L40S":
            n_od = len(data["by_bucket"]["on-demand"]["single"])
            assert f"{n_od} single-GPU on-demand rates" in text
        for r in data["rows"]:
            if r["price"] is None:
                continue
            assert r["vendor"] in text, f"{fam} missing vendor {r['vendor']}"
            assert r["price"] in text, f"{fam} missing price {r['price']} for {r['vendor']}"
            assert r["verified_et"] in text
            assert r["source_url"] in text
            if not r["single_gpu"]:
                assert str(r["min_gpus"]) in text
        for c in data["changes"]:
            assert c["date"] in text
            assert c["vendor"] in text
            if c["from_price"]:
                assert c["from_price"] in text
            if c["to_price"]:
                assert c["to_price"] in text
            if c.get("change_pct") is not None:
                rendered = f"{c['change_pct']:+g}%"
                assert rendered in text, f"{fam} missing {rendered}"


def test_cost_page_cells_recompute():
    figs = _figs()
    text = COST_PAGE.read_text(encoding="utf-8")
    assert "job-cost calculator" in text
    assert "Hours are examples, not a measured" in text
    assert "GPU-hour price only" in text
    assert figs["feed_updated_at_et"] in text
    calc = figs["calculator"]
    for col in calc["columns"]:
        assert col["rate"] in text
        assert col["vendor"] in text
        assert col["verified_et"] in text
        assert col["source_url"] in text
        for h in calc["hours"]:
            display = calc["cells"][col["key"]][str(h)]["display"]
            assert display in text
            assert display == fmt_usd_mul(col["rate_usd"], h)
    for h in calc["hours"]:
        assert f"{h} hours" in text
    assert calc["cells"]["h100_pcie_hyperstack"]["8"]["display"] in text


def test_install_block_and_example_calls():
    figs = _figs()
    mcp = figs["mcp"]
    for fam, path in FAMILY_PAGES.items():
        text = path.read_text(encoding="utf-8")
        assert mcp["hosted_add"] in text
        assert mcp["uvx_add"] in text
        assert HOSTED in text
        assert "uvx lantern-works-deals-mcp" in text
        assert "https://thelanternworks.com/install/" in text
        assert "compare_gpu_prices" in text
        assert f'"gpu": "{fam}"' in text
        assert '"on_demand_only": true' in text
    cost = COST_PAGE.read_text(encoding="utf-8")
    assert mcp["hosted_add"] in cost
    assert mcp["uvx_add"] in cost
    assert HOSTED in cost
    assert "uvx lantern-works-deals-mcp" in cost
    assert "estimate_job_cost" in cost
    assert '"gpu_family": "H100"' in cost
    assert '"gpus_per_job": 1' in cost
    assert '"job_hours": 8' in cost
    assert '"allow_interruptible": false' in cost


def test_no_owner_name_or_private_paths():
    for path in list(FAMILY_PAGES.values()) + [COST_PAGE]:
        text = path.read_text(encoding="utf-8")
        assert not FORBIDDEN.search(text), path
        assert "Frosty" not in text and "Connor" not in text


def test_sitemap_entries_use_content_date_lastmod():
    sm = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    figs = _figs()
    day = figs["feed_updated_at"][:10]
    assert day <= "2026-11-28"
    for loc in (
        "https://thelanternworks.com/reports/cheapest-h100-week-of-2026-11-23/",
        "https://thelanternworks.com/reports/cheapest-l40s-week-of-2026-11-23/",
        "https://thelanternworks.com/reports/cheapest-a100-week-of-2026-11-23/",
        "https://thelanternworks.com/cost/fine-tune-7b-8b-lora/",
    ):
        m = re.search(re.escape(f"<loc>{loc}</loc>") + r"\s*(?:<lastmod>(.*?)</lastmod>)?", sm)
        assert m, f"missing sitemap loc {loc}"
        lastmod = m.group(1)
        assert lastmod, f"missing lastmod for {loc}"
        assert lastmod == day, f"{loc} lastmod {lastmod} != feed day {day}"
        assert lastmod <= day
        # no future dates relative to the feed clock
        assert lastmod <= figs["feed_updated_at"][:10]


def test_rental_pages_and_indexes_link_here():
    mapping = {
        "H100": "cheapest-h100-week-of-2026-11-23",
        "L40S": "cheapest-l40s-week-of-2026-11-23",
        "A100": "cheapest-a100-week-of-2026-11-23",
    }
    for fam, slug in mapping.items():
        page = (ROOT / "gpu" / f"{fam.lower()}-rental-price" / "index.html").read_text(encoding="utf-8")
        assert f"/reports/{slug}/" in page, fam
        assert "/cost/fine-tune-7b-8b-lora/" in page, fam
    reports = (ROOT / "reports" / "index.html").read_text(encoding="utf-8")
    for slug in mapping.values():
        assert f"/reports/{slug}/" in reports
    # Newer weekly snapshots list ahead of the Nov 20 moved-prices report.
    assert reports.find("/reports/cheapest-h100-week-of-2026-11-23/") < reports.find(
        "/reports/gpu-prices-that-moved-2026-11-20/"
    )
    cost_idx = (ROOT / "cost" / "index.html").read_text(encoding="utf-8")
    assert "/cost/fine-tune-7b-8b-lora/" in cost_idx
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
    for slug in mapping.values():
        assert f"/reports/{slug}/" in llms


def test_markdown_builder_matches_html_figures():
    """In-memory markdown (same figures as HTML) still contains every computed rate."""
    figs = _figs()
    for key in PAGE_SPECS:
        md = page_markdown(key, figs)
        if key == "cost":
            for col in figs["calculator"]["columns"]:
                assert col["rate"] in md
                for h in figs["calculator"]["hours"]:
                    assert figs["calculator"]["cells"][col["key"]][str(h)]["display"] in md
        else:
            od = figs["families"][key]["cheapest_on_demand_single"]
            assert f"{od['price']}/GPU-hr" in md
            assert od["vendor"] in md
        assert HOSTED in md
        assert "uvx lantern-works-deals-mcp" in md
        assert not FORBIDDEN.search(md)
