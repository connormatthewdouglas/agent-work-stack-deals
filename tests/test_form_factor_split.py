import json, re
from pathlib import Path
from core import deals as core

ROOT = Path(__file__).resolve().parents[1]
FEED = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())


def test_mcp_cheapest_by_form_factor_is_additive():
    for gpu in ("H100", "A100"):
        out = core.compare_gpu_prices(FEED, gpu, limit=25)
        assert {"gpu", "summary", "count", "results"} <= set(out)
        cb = out.get("cheapest_by_form_factor")
        assert cb and len({x["form_factor"] for x in cb}) == len(cb) >= 2
        for x in cb:
            same = [r for r in out["results"] if (r.get("form_factor") or "not stated") == x["form_factor"] and r["tier_class"] != "reserved"]
            assert x["rate_id"] == same[0]["rate_id"]  # first in the normal ranking order for that form factor
    assert "cheapest_by_form_factor" not in core.compare_gpu_prices(FEED, "RTX 4090", limit=25)


def test_rental_pages_never_mix_sxm_and_pcie_in_one_table():
    for fam in ("h100", "a100"):
        html = (ROOT / f"gpu/{fam}-rental-price/index.html").read_text()
        for tbl in re.findall(r"<tbody>(.*?)</tbody>", html, re.S):
            variants = re.findall(r'data-label="Variant">([^<]*)<', tbl)
            assert not (any("SXM" in v for v in variants) and any("PCIe" in v for v in variants)), fam


def test_pair_pages_pair_within_form_factor():
    for f in ROOT.glob("compare/*-gpu-prices/index.html"):
        for row in re.findall(r"<tr><td data-label=\"GPU\">(.*?)</tr>", f.read_text(), re.S):
            cells = re.findall(r'<small>\(([^)]*)\)</small>', row)
            assert not ("SXM" in row and "PCIe" in row), f


def test_page_and_mcp_share_one_form_factor_rule():
    """Gauge strat2: the page and MCP pick the same row per form factor (one out-of-stock rule), with interruptible marked."""
    out = core.compare_gpu_prices(FEED, "H100", limit=25)
    picks = out["cheapest_by_form_factor"]
    assert all({"tier_class", "interruptible", "in_stock"} <= set(p) for p in picks)
    assert all(p["interruptible"] == (p["tier_class"] == "interruptible") for p in picks)
    assert "NVLink" in out["cheapest_by_form_factor_note"]
    page = re.sub(r"<[^>]+>", " ", (ROOT / "gpu/h100-rental-price/index.html").read_text())
    sec = page[page.index("by form factor"):][:3000]
    for p in picks:
        assert p["advertiser"] in sec and str(p["hourly_usd"]) in sec, p
    assert "NVLink names the" in sec
