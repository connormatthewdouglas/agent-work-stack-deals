"""CloudRift RTX 5090 prices on /pricing moved from $0.90 / $0.81 / $0.77 to $1.00 / $0.90 / $0.85.

Official GET 2026-11-28T05:50:06Z, robots Allow: /. Pinned clock and fixture; no network.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_gpu_prices as R  # noqa: E402
import check_gpu_sources as C  # noqa: E402

URL = "https://www.cloudrift.ai/pricing"
NOW = datetime(2026, 11, 28, 5, 50, 6, tzinfo=timezone.utc)
OLD = "NVIDIA RTX 5090 32 GB VRAM On-Demand $0.90 1 Month $0.81 3 Month $0.77"
NEW = "NVIDIA RTX 5090 32 GB VRAM On-Demand $1.00 1 Month $0.90 3 Month $0.85"
# Verbatim visible chart line from the official 2026-11-28T05:50:06Z pricing GET, with neighbors.
PAGE = (
    "NVIDIA RTX PRO 6000 96 GB VRAM On-Demand $1.95 1 Month $1.76 3 Month $1.66 Rent "
    + NEW
    + " Request NVIDIA RTX 4090 24 GB VRAM On-Demand $0.36 1 Month $0.32 3 Month $0.31 Rent"
)


def _rec(tier: str, price: float) -> dict:
    return {
        "vendor": "CloudRift",
        "gpu": "RTX 5090",
        "vram_gb": 32,
        "price_usd": price,
        "hourly_usd": price,
        "billing_unit": "hourly",
        "interruptible": False,
        "tier": tier,
        "quote": OLD,
        "source_url": URL,
        "checked_at": "2026-11-27T19:32:19+00:00",
        "verified_at": "2026-11-27T19:32:19+00:00",
        "evidence": {"source_url": URL, "quote": OLD, "checked_at": "2026-11-27T19:32:19+00:00"},
        "quote_id": None,
    }


def test_old_reserved_prices_are_gone_from_the_official_page():
    text = PAGE
    assert "0.81" not in text and "0.77" not in text
    missing = [t for t in C.price_tokens(OLD) if not C.price_found(t, OLD, text)]
    assert missing == ["0.81", "0.77"]


def test_parse_listed_recites_new_on_demand_and_reserved_prices():
    cases = [
        ("On-demand", 0.90, "1.00"),
        ('1 Month (reserved, "1 mo")', 0.81, "0.90"),
        ('3 Month (reserved, "3 mo")', 0.77, "0.85"),
    ]
    for tier, old, expect in cases:
        got, quote, msg = R.parse_listed(_rec(tier, old), PAGE)
        assert got == expect and msg == "parsed", (tier, got, msg)
        assert NEW in quote


def test_refresh_applies_the_sub_50_percent_recitation_and_preserves_quote_id():
    recs = [
        _rec("On-demand", 0.90),
        _rec('1 Month (reserved, "1 mo")', 0.81),
        _rec('3 Month (reserved, "3 mo")', 0.77),
    ]
    doc = {
        "vendor": "CloudRift",
        "deal_id": None,
        "source_url": URL,
        "checked_at": "2026-11-10T18:30:05+00:00",
        "records": recs,
    }

    class F:
        fetched_at = {URL: NOW}

        def get(self, url):
            assert url == URL
            return 200, f"<html><body><p>{PAGE}</p></body></html>"

    rep = R.refresh([doc], F(), NOW)
    expect = {"On-demand": 1.0, '1 Month (reserved, "1 mo")': 0.9, '3 Month (reserved, "3 mo")': 0.85}
    for row, rec in zip(rep, recs):
        assert row["result"] == "changed"
        assert rec["price_usd"] == expect[rec["tier"]]
        assert rec["quote"] == NEW
        assert rec["evidence"]["quote"] == NEW
        assert rec["checked_at"] == "2026-11-28T05:50:06+00:00"
        assert rec["verified_at"] == "2026-11-28T05:50:06+00:00"
        assert rec["quote_id"] is None
        assert rec["evidence"]["source_url"] == URL


def test_live_checks_find_the_new_quote_tokens():
    missing = [t for t in C.price_tokens(NEW) if not C.price_found(t, NEW, PAGE)]
    assert missing == []
