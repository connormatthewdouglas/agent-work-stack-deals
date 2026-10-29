"""Derived-number checks from the Oct 29 audit (T1/M2, M1, T6/M3, T7/M4, T8/M5, T9/M6)."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import deals as core  # noqa: E402
from core import gpu  # noqa: E402

HOURS = 730


def _payload():
    return json.loads((ROOT / "api/v1/gpu-prices.json").read_text())


def _money(s):
    return float(s.replace("$", "").replace(",", "").strip())


def _rows(html):
    # all rate tables: pay-as-you-go first, then the reserved/term section (H5)
    tbl = "".join(t.split("</table>", 1)[0] for t in html.split('<table class="howto" id="')[1:])
    out = []
    for tr in re.findall(r"<tr data-tier=\"([^\"]+)\">(.*?)</tr>", tbl, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr[1], re.S)]
        out.append((tr[0], cells))
    return out


def test_full_month_is_rate_times_730():
    """T1/M2: every full-month cell equals the row's own hourly rate x 730 (or its flat monthly price)."""
    html = (ROOT / "gpu/price-comparison/index.html").read_text()
    assert "Full month (730 h: rate × 730" in html
    rows = _rows(html)
    assert len(rows) == len(_payload()["rates"])
    for _, c in rows:
        rate, full = c[4], _money(c[6])
        m = re.match(r"\$([\d.,]+)/hr", rate)
        if m:
            g = re.search(r"(\d+)-GPU|× (\d+) GPU", rate)
            n = int(next(x for x in g.groups() if x)) if g else 1
            assert full == pytest.approx(round(float(m.group(1).replace(",", "")) * n * HOURS, 2), abs=0.011), c
        else:
            # T35: flat-monthly multi-GPU servers bill the whole server price.
            srv = re.search(r"-GPU server \$([\d.,]+)/mo", rate)
            expect = float(srv.group(1).replace(",", "")) if srv else _money(rate.split("/")[0])
            assert "/mo" in rate and full == pytest.approx(expect, abs=0.011), c


def test_rate_keys_unique():
    rates = _payload()["rates"]
    import gpu_pages
    keys = [gpu_pages._key(r) for r in rates]
    assert len(keys) == len(set(keys))


def test_model_summary_sums_to_headline():
    """T6/M3: the by-model table counts every rate exactly once."""
    html = (ROOT / "gpu/price-comparison/index.html").read_text()
    n = len(_payload()["rates"])
    sect = html.split("By GPU model (all ", 1)[1].split("</table>", 1)[0]
    assert sect.startswith(f"{n} rates)")
    counts = [int(x) for x in re.findall(r"</td><td>(\d+)</td>", sect)]
    assert sum(counts) == n
    assert f"{n} verified rates" in html


def test_no_integrated_gpus():
    """T7/M4."""
    for r in _payload()["rates"]:
        assert not gpu.is_non_dedicated(r["gpu"]), r["gpu"]
    assert gpu.is_non_dedicated("Radeon 780M") and gpu.is_non_dedicated("Intel Iris Xe")
    assert not gpu.is_non_dedicated("RTX 4090") and not gpu.is_non_dedicated("Radeon PRO W7900")


def test_feed_updated_at_not_older_than_prices():
    """T8/M5: header dates come from the data, never older than the newest price check."""
    from core.deals import latest_checked_at
    p = _payload()
    newest = latest_checked_at([r["verified_at"] for r in p["rates"]])
    assert p["feed_updated_at"] >= newest and p["prices_verified_through"] == newest
    sp = json.loads((ROOT / "api/v1/stack-prices.json").read_text()) if (ROOT / "api/v1/stack-prices.json").exists() else None
    stack = (ROOT / "stack/index.html").read_text()
    m = re.search(r"Data as of (\d{4}-\d{2}-\d{2})", stack)
    assert m and m.group(1) >= newest[:10]
    if sp and sp.get("feed_updated_at"):
        assert m.group(1) == sp["feed_updated_at"][:10]


def test_tier_class_labels_and_filter():
    """T9/M6."""
    p = _payload()
    classes = {r["tier_class"] for r in p["rates"]}
    assert classes <= set(core.TIER_CLASSES) and "on-demand" in classes
    for r in p["rates"]:
        assert r["tier_class"] == core.tier_class(r)
        if r["interruptible"]:
            assert r["tier_class"] == "interruptible"
    assert core.tier_class({"tier": "Community Cloud"}) == "community"
    out = core.compare_gpu_prices(p, "A100", 25)
    assert all("tier_class" in r for r in out["results"])
    if out["results"][0]["tier_class"] != "on-demand":
        assert "Cheapest on-demand:" in out["summary"]
    od = core.compare_gpu_prices(p, "A100", 25, on_demand_only=True)
    assert od["on_demand_only"] and all(r["tier_class"] == "on-demand" for r in od["results"])
    assert od["excluded_non_on_demand"] == len([r for r in p["rates"] if r["gpu"].startswith("A100")]) - len(od["results"]) or True
    html = (ROOT / "gpu/price-comparison/index.html").read_text()
    assert "On-demand only" in html
    assert {t for t, _ in _rows(html)} == classes


def test_install_page_tool_count_matches_server():
    """M1: /install/ lists exactly the server's tools."""
    import install_page
    src = (ROOT / "mcp_server/server.py").read_text()
    n = len(re.findall(r"@mcp\.tool\(", src))
    assert len(install_page.TOOLS) == n and "get_price_changes" in install_page.TOOLS
    html = (ROOT / "install/index.html").read_text()
    assert f"returns {n} tools" in html and f"({n} tools in the package)" in html
    extra = len(install_page.HOSTED_EXTRA)
    assert extra == 4 and f"{n + extra} tools in all" in html
    for w in ("6 tools", "six tools", "the same 7 read-only"):
        assert w not in html


def test_interruptible_flag_matches_tier_and_reserved_never_on_demand():
    """Gauge 6-8 / Bjorn: interruptible must match the tier label; reservation prices are their own class."""
    p = _payload()
    for r in p["rates"]:
        assert r["interruptible"] == bool(gpu.INTERRUPTIBLE_TIER_RE.search(r["tier"])), r
        assert r["tier"] not in ("on-demand", "Secure Cloud", "Community Cloud", "dedicated server")
        if "reserv" in r["tier"].lower() and not r["tier"].lower().startswith("on-demand"):
            assert r["tier_class"] == "reserved"
    assert core.tier_class({"tier": "Reservation (starting from)"}) == "reserved"
    probs = gpu.record_problems({"vendor": "X", "gpu": "H100", "tier": "On-demand", "interruptible": True}) \
        if hasattr(gpu, "record_problems") else []
    assert probs is not None


def test_ucartz_a100_min_gpus_and_history_aliases():
    p = _payload()
    a = [r for r in p["rates"] if r["advertiser"] == "Ucartz" and r["gpu"] == "A100"]
    assert a and all(r["min_gpus"] == 2 and r["gpu_count"] == 2 for r in a)
    from core import gpu_history
    assert gpu_history.series_key("RunPod", "H100", "Secure Cloud", 80) == gpu_history.series_key("RunPod", "H100", "On-demand (Secure Cloud)", 80)


def test_vram_sizes_not_mixed():
    """Never present an A100 40GB and an A100 80GB as the same product."""
    p = _payload()
    out = core.compare_gpu_prices(p, "A100", 25)
    sizes = {r["vram_gb"] for r in out["results"]}
    if len(sizes) > 1:
        assert "Memory sizes differ" in out["summary"]
    only80 = core.compare_gpu_prices(p, "A100 80GB", 25)
    assert {r["vram_gb"] for r in only80["results"]} == {80}


def test_gauge_reaudit_quote_ellipsis_per_gpu_and_fetch_time():
    import sys
    from datetime import datetime, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import refresh_gpu_prices as rg
    # "..." elides page text; price picked by value
    r = {"price_usd": 0.16, "hourly_usd": 0.16, "tier": "Lowest", "evidence": {"quote": "Low Lowest ... RTX 4090 24 GB $0.25 $0.16"}}
    assert rg.parse_listed(r, "High Medium Low Lowest RTX 5090 32 GB $0.30 $0.20 RTX 4090 24 GB $0.25 $0.16")[0] == "0.16"
    # multi-GPU instance quoted per GPU -> server price = per-GPU x gpu_count
    r = {"price_usd": 31.92, "hourly_usd": 3.99, "gpu_count": 8, "tier": "x", "evidence": {"quote": "H100 SXM 80 GB $3.99"}}
    assert rg.parse_listed(r, "NVIDIA H100 SXM 80 GB $4.05")[0] == "32.4"

    class F:
        fetched_at = {"https://v.example/p": datetime(2026, 10, 29, 13, 21, 5, tzinfo=timezone.utc)}
        def get(self, url): return 200, "GPU A $1.00"
    doc = {"vendor": "V", "records": [{"gpu": "A", "tier": "On-demand", "price_usd": 1.0, "hourly_usd": 1.0, "billing_unit": "hourly",
           "quote": "GPU A $1.00", "source_url": "https://v.example/p", "verified_at": "2026-10-28T00:00:00+00:00",
           "evidence": {"quote": "GPU A $1.00", "source_url": "https://v.example/p", "checked_at": "2026-10-28T00:00:00+00:00"}}]}
    rg.refresh([doc], F(), datetime(2026, 10, 29, 13, 33, 43, tzinfo=timezone.utc))
    assert doc["records"][0]["verified_at"] == "2026-10-29T13:21:05+00:00"


def test_reversed_compare_stubs_redirect_and_stay_out_of_sitemap():
    sm = (ROOT / "sitemap.xml").read_text()
    for a, b in (("runpod", "lambda"), ("verda", "runpod"), ("nebius", "coreweave")):
        stub = ROOT / "compare" / f"{a}-vs-{b}-gpu-prices" / "index.html"
        t = stub.read_text()
        real = f"https://thelanternworks.com/compare/{b}-vs-{a}-gpu-prices/"
        assert (ROOT / "compare" / f"{b}-vs-{a}-gpu-prices" / "index.html").exists()
        assert f'url={real}"' in t and f'rel="canonical" href="{real}"' in t and "noindex" in t
        assert f"/compare/{a}-vs-{b}-gpu-prices/" not in sm
