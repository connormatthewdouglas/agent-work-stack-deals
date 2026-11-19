"""CloudRift RTX 5090 chart relabelled 1 mo / 3 mo; same $0.65 / $0.59 / $0.55."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_gpu_prices as R  # noqa: E402

OLD = "RTX 5090 NVIDIA On\u2011Demand $0.65 1 mo $0.59 3 mo $0.55 32 GB VRAM"
# Verbatim visible text from https://www.cloudrift.ai/pricing (GET 2026-11-18, robots Allow: /).
NEW = "NVIDIA RTX 5090 32 GB VRAM On-Demand $0.65 1 Month $0.59 3 Month $0.55"
URL = "https://www.cloudrift.ai/pricing"
# Surrounding rows so the fixture looks like the live chart, not a lone sentence.
PAGE = (
    "NVIDIA RTX PRO 6000 96 GB VRAM On-Demand $1.95 1 Month $1.76 3 Month $1.66 "
    "Request " + NEW + " Request NVIDIA RTX 4090 24 GB VRAM On-Demand $0.45 1 Month $0.41 3 Month $0.38"
)


def _rec(tier: str, price: float) -> dict:
    return {
        "vendor": "CloudRift",
        "gpu": "RTX 5090",
        "tier": tier,
        "price_usd": price,
        "hourly_usd": price,
        "source_url": URL,
        "evidence": {"quote": OLD, "source_url": URL},
    }


def test_old_mo_quote_is_gone_without_the_new_sentence():
    rec = _rec("On-demand", 0.65)
    price, quote, msg = R.parse_listed(rec, "NVIDIA RTX 4090 24 GB VRAM On-Demand $0.45 1 Month $0.41 3 Month $0.38")
    assert price is None and "not found" in msg


def test_pricing_alternate_quote_parses_same_on_demand_and_reserved_prices():
    cases = [
        ("On-demand", 0.65, "0.65"),
        ('1 Month (reserved, "1 mo")', 0.59, "0.59"),
        ('3 Month (reserved, "3 mo")', 0.55, "0.55"),
    ]
    for tier, price, expect in cases:
        got, quote, msg = R.parse_listed(_rec(tier, price), PAGE)
        assert got == expect and msg == "parsed", (tier, got, msg)
        assert NEW in quote


def test_refresh_adopts_month_labels_when_price_is_unchanged():
    rec = _rec("On-demand", 0.65)
    rec.update({
        "vram_gb": 32,
        "billing_unit": "hourly",
        "interruptible": False,
        "quote": OLD,
        "checked_at": "2026-11-16T23:32:55+00:00",
        "verified_at": "2026-11-16T23:32:55+00:00",
    })
    rec["evidence"]["checked_at"] = "2026-11-16T23:32:55+00:00"
    doc = {
        "vendor": "CloudRift",
        "deal_id": None,
        "source_url": URL,
        "checked_at": "2026-11-10T18:30:05+00:00",
        "records": [rec],
    }

    class F:
        fetched_at = {}

        def get(self, url):
            self.fetched_at[url] = datetime(2026, 11, 19, 1, 36, 0, tzinfo=timezone.utc)
            return 200, f"<html><body><p>{PAGE}</p></body></html>"

    now = datetime(2026, 11, 19, 1, 36, 0, tzinfo=timezone.utc)
    rep = R.refresh([doc], F(), now)
    assert rep[0]["result"] == "unchanged" and rec["hourly_usd"] == 0.65
    assert rec["source_url"] == URL
    assert NEW in rec["quote"] and NEW in rec["evidence"]["quote"]
    assert rec["verified_at"].startswith("2026-11-19T01:36:00")
    # Subset re-read of one row does not move the vendor-level checked_at
    # unless every tried record verified; this doc has only the one row.
    assert doc["checked_at"].startswith("2026-11-19T01:36:00")
