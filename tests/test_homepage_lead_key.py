"""Homepage cheapest-H100 pick uses core.data_age.lead_key (fresh on-demand first)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import home_page  # noqa: E402


def _row(vendor, price, tier_class, hours_old, gpu="H100 SXM", tier=None):
    ts = (datetime(2026, 11, 10, 12, tzinfo=timezone.utc) - timedelta(hours=hours_old)).isoformat()
    return {
        "gpu": gpu, "advertiser": vendor, "tier": tier or tier_class, "tier_class": tier_class,
        "hourly_equiv_usd": price, "verified_at": ts, "checked_at": ts,
        "availability": {"in_stock": True},
    }


def test_homepage_h100_cheapest_is_fresh_on_demand_not_community(monkeypatch):
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-10T12:00:00+00:00")
    rates = [
        _row("RunPod", 1.99, "community", 2, tier="Community Cloud"),
        _row("Hyperstack", 2.50, "on-demand", 2, tier="On-Demand"),
        _row("OldCheap", 1.50, "on-demand", 60, tier="On-Demand"),  # degraded (> 48 h)
    ]
    rows = {s["slug"]: s for s in home_page.spread(rates)}
    h = rows["h100"]
    assert h["cheapest_vendor"] == "Hyperstack"
    assert h["cheapest_price"] == 2.50
    assert h["min"] == 2.50  # community $1.99 and degraded $1.50 are not the headline cheapest


def test_homepage_and_rental_price_titles_fit_search_limits():
    home = (ROOT / "index.html").read_text(encoding="utf-8")
    title = re.search(r"<title>(.*?)</title>", home).group(1)
    desc = re.search(r'name="description" content="(.*?)"', home).group(1)
    assert len(title) <= 60 and len(desc) <= 155
    assert "Cheapest" in title and "GPU" in title
    pages = list((ROOT / "gpu").glob("*-rental-price/index.html"))
    assert len(pages) == 12
    for path in pages:
        t = path.read_text(encoding="utf-8")
        title = re.search(r"<title>(.*?)</title>", t).group(1)
        desc = re.search(r'name="description" content="(.*?)"', t).group(1)
        assert len(title) <= 60, (path, len(title), title)
        assert len(desc) <= 155, (path, len(desc), desc)
        assert title.startswith("Cheapest ") and "among tracked providers" in title
        assert "among tracked providers" in desc
        assert "$" not in title  # no price claims in titles
