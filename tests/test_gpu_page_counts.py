"""Gauge Nov 1: H100 pages list every H100 rate in the feed (all forms, NVL included); counts derive from the feed."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from core.gpu import family_of  # noqa: E402
import gpu_pages  # noqa: E402


def _feed():
    return json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]


def _h100():
    return [r for r in _feed() if r["gpu"].startswith("H100")]


def _cheapest_nvl():
    nvl = [r for r in _h100() if r.get("form_class") == "NVL" and r.get("tier_class") != "reserved"]
    return min(nvl, key=lambda r: (r["hourly_equiv_usd"], r["advertiser"])) if nvl else None


def _nvl_line(html):
    c = _cheapest_nvl()
    if c is None:
        return
    m = re.search(r"H100 NVL</strong>: ([^<(]+?) \(.*?\) at \$([0-9.]+)/", html)
    assert m, "no H100 NVL line"
    assert m.group(1).strip() == c["advertiser"] and float(m.group(2)) == c["hourly_equiv_usd"], (m.groups(), c["advertiser"], c["hourly_equiv_usd"])


def test_cheapest_h100_page_count_and_nvl_line():
    n = len(_h100())
    html = (ROOT / "gpu/cheapest-h100-rental/index.html").read_text()
    m = re.search(r"(\d+) offers from \d+ vendors", html)
    assert m and int(m.group(1)) == n, (m and m.group(0), n)
    _nvl_line(html)


def test_h100_rental_price_page_count_and_nvl_line():
    n = len(_h100())
    html = (ROOT / "gpu/h100-rental-price/index.html").read_text()
    assert html.count('data-label="$/GPU-hr"') == n
    m = re.search(r"(\d+) offers from \d+ vendors", html)
    assert m and int(m.group(1)) == n, (m and m.group(0), n)
    _nvl_line(html)


def test_price_comparison_h100_plus_nvl_equals_feed():
    rates = _feed()
    html = (ROOT / "gpu/price-comparison/index.html").read_text()
    row = lambda name: int(re.search(r">" + re.escape(name) + r"</a>(?: <em>[^<]*</em>)?</td><td>(\d+)</td>|<td>" + re.escape(name) + r"(?: <em>[^<]*</em>)?</td><td>(\d+)</td>", html).group(0).rsplit("<td>", 1)[1].split("<")[0])
    h, nvl = row("H100"), row("H100 NVL")
    assert h == sum(family_of(r["gpu"]) == "h100" for r in rates)
    assert nvl == sum(family_of(r["gpu"]) == "h100-nvl" for r in rates)
    assert h + nvl == len(_h100())
    assert f"H100 ({h}) excludes the H100 NVL, listed separately ({nvl})" in html


def test_model_json_row_count():
    j = json.loads((ROOT / "api/v1/gpu/h100.json").read_text())
    rows = j.get("rates") or j.get("rows") or []
    assert j.get("row_count", len(rows)) == len(rows) == len(_h100())


def test_storage_egress_count_matches_published_extras():
    # 62 on Nov 1 (60 + the 2 RunPod H100 NVL rows); derived: every rate of a vendor whose extras are published
    from core.gpu import load_vendor_files, _published_extras
    pub = {d["vendor"] for d in load_vendor_files(ROOT / "data/gpu_pricing") if _published_extras(d)}
    rates = _feed()
    assert sum("storage" in r or "egress" in r for r in rates) == sum(r["advertiser"] in pub for r in rates)
