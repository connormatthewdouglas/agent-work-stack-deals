"""CloudRift L40S prices moved from /pricing to /l40; same $0.69 / $0.62 / $0.59."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_gpu_prices as R  # noqa: E402

OLD = "L40S NVIDIA On\u2011Demand $0.69 1 mo $0.62 3 mo $0.59 48 GB VRAM"
# Verbatim visible text from https://www.cloudrift.ai/l40 (GET 2026-11-18, robots Allow: /).
NEW_PAGE = (
    "Can I rent L40S GPUs on CloudRift? Yes, on demand at $0.69 per GPU-hour, billed by the second, "
    "in instances of up to eight GPUs. Reserved terms bring it to $0.66/hr for 1 week, $0.62/hr for "
    "1 month, and $0.59/hr for 3 months. Check the Console for current availability."
)
URL = "https://www.cloudrift.ai/l40"


def _rec(tier: str, price: float) -> dict:
    return {
        "vendor": "CloudRift",
        "gpu": "L40S",
        "tier": tier,
        "price_usd": price,
        "hourly_usd": price,
        "source_url": URL,
        "evidence": {"quote": OLD, "source_url": URL},
    }


def test_old_pricing_table_quote_is_gone_without_alternate():
    rec = _rec("On-demand", 0.69)
    rec["source_url"] = "https://www.cloudrift.ai/pricing"
    rec["evidence"]["source_url"] = rec["source_url"]
    price, quote, msg = R.parse_listed(rec, NEW_PAGE)
    assert price is None and "not found" in msg


def test_l40_alternate_quote_parses_same_on_demand_and_reserved_prices():
    # The new sentence also lists a 1-week $0.66 term, so the old capture index
    # ($0.62 was the 2nd price) would be wrong unless parse_listed re-indexes.
    cases = [
        ('On-demand', 0.69, "0.69"),
        ('1 Month (reserved, "1 mo")', 0.62, "0.62"),
        ('3 Month (reserved, "3 mo")', 0.59, "0.59"),
    ]
    for tier, price, expect in cases:
        got, quote, msg = R.parse_listed(_rec(tier, price), NEW_PAGE)
        assert got == expect and msg == "parsed", (tier, got, msg)
        assert "$0.69" in quote and "$0.62" in quote and "$0.59" in quote
        assert "$0.66" in quote  # visible 1-week term stays in the cited sentence


def test_refresh_adopts_l40_sentence_when_price_is_unchanged():
    from datetime import datetime, timezone

    rec = _rec("On-demand", 0.69)
    rec.update({
        "vram_gb": 48,
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
        "source_url": "https://www.cloudrift.ai/pricing",
        "checked_at": "2026-11-10T18:30:05+00:00",
        "records": [rec],
    }

    class F:
        fetched_at = {}

        def get(self, url):
            self.fetched_at[url] = datetime(2026, 11, 18, 1, 33, 31, tzinfo=timezone.utc)
            return 200, f"<html><body><p>{NEW_PAGE}</p></body></html>"

    rep = R.refresh([doc], F(), datetime(2026, 11, 18, 1, 33, 31, tzinfo=timezone.utc))
    assert rep[0]["result"] == "unchanged" and rec["hourly_usd"] == 0.69
    assert rec["source_url"] == URL
    assert rec["quote"].startswith("Yes, on demand at $0.69 per GPU-hour")
    assert rec["evidence"]["quote"].startswith("Yes, on demand at $0.69 per GPU-hour")
    assert rec["evidence"]["source_url"] == URL
    assert rec["verified_at"].startswith("2026-11-18T01:33:31")
