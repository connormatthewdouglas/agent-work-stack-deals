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
import spec_pages  # noqa: E402


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
    # Derive the expected /gpu/<model>-rental-price/ set from the current feed
    # (same qualifying_families rule the generator uses). Do not pin a live
    # count: a collector rebuild can add a page (e.g. L40 once a third vendor
    # qualifies) and must not fail this title-limit check, but a missing page
    # for a still-qualifying family is a regression.
    feeds = spec_pages.load_feeds()
    expected = {
        ROOT / "gpu" / f"{spec_pages.slug(fam)}-rental-price" / "index.html"
        for fam in spec_pages.qualifying_families(spec_pages.rankable(feeds["prices"]))
    }
    pages = list((ROOT / "gpu").glob("*-rental-price/index.html"))
    got = set(pages)
    assert expected, "feed produced no rental-price families"
    assert got == expected, (
        "missing pages "
        + str(sorted(p.relative_to(ROOT).as_posix() for p in expected - got))
        + "; unexpected pages "
        + str(sorted(p.relative_to(ROOT).as_posix() for p in got - expected))
    )
    for path in pages:
        t = path.read_text(encoding="utf-8")
        title = re.search(r"<title>(.*?)</title>", t).group(1)
        desc = re.search(r'name="description" content="(.*?)"', t).group(1)
        assert len(title) <= 60, (path, len(title), title)
        assert len(desc) <= 155, (path, len(desc), desc)
        assert title.startswith("Cheapest ") and "among tracked providers" in title
        assert "among tracked providers" in desc
        assert "$" not in title  # no price claims in titles
