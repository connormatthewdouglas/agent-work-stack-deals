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


# Fixture-only amounts for a later move of the same Month-label chart line.
# Not live vendor prices; the page under test is built from these.
MOVED_ON, MOVED_1MO, MOVED_3MO = "0.80", "0.70", "0.60"
MOVED_LINE = (
    f"NVIDIA RTX 5090 32 GB VRAM On-Demand ${MOVED_ON} "
    f"1 Month ${MOVED_1MO} 3 Month ${MOVED_3MO}"
)
MOVED_PAGE = (
    "NVIDIA RTX PRO 6000 96 GB VRAM On-Demand $1.95 1 Month $1.76 3 Month $1.66 "
    "Request " + MOVED_LINE + " Request NVIDIA RTX 4090 24 GB VRAM On-Demand $0.45 1 Month $0.41 3 Month $0.38"
)
STAMP = "2026-11-19T01:36:00+00:00"
NOW = datetime(2026, 11, 25, 14, 32, 32, tzinfo=timezone.utc)


def _full_rec(tier: str, price: float, quote: str = NEW) -> dict:
    rec = _rec(tier, price)
    rec.update({
        "vram_gb": 32,
        "billing_unit": "hourly",
        "interruptible": False,
        "quote": quote,
        "checked_at": STAMP,
        "verified_at": STAMP,
        "quote_id": None,
    })
    rec["evidence"] = {"source_url": URL, "quote": quote, "checked_at": STAMP}
    return rec


class _Fake:
    def __init__(self, html: str, at: datetime):
        self.html = html
        self.at = at
        self.calls: list[str] = []
        self.fetched_at = {}

    def get(self, url: str):
        self.calls.append(url)
        if url != URL:
            raise AssertionError(f"test fetcher must not hit the network; unexpected URL {url}")
        self.fetched_at[url] = self.at
        return 200, f"<html><body><p>{self.html}</p></body></html>"


def test_month_label_line_price_move_updates_each_tier_uniquely():
    """The same chart line, unique On-Demand / 1 Month / 3 Month figures, moves."""
    recs = [
        _full_rec("On-demand", 0.65),
        _full_rec('1 Month (reserved, "1 mo")', 0.59),
        _full_rec('3 Month (reserved, "3 mo")', 0.55),
    ]
    for rec in recs:
        got, quote, msg = R.parse_listed(rec, MOVED_PAGE)
        expect = { "On-demand": MOVED_ON, '1 Month (reserved, "1 mo")': MOVED_1MO, '3 Month (reserved, "3 mo")': MOVED_3MO }[rec["tier"]]
        assert got == expect and msg == "parsed", (rec["tier"], got, msg)
        assert MOVED_LINE in quote


def test_refresh_recites_moved_chart_prices_and_keeps_quote_ids():
    recs = [
        _full_rec("On-demand", 0.65),
        _full_rec('1 Month (reserved, "1 mo")', 0.59),
        _full_rec('3 Month (reserved, "3 mo")', 0.55),
    ]
    vendor_stamp = "2026-11-10T18:30:05+00:00"
    doc = {
        "vendor": "CloudRift",
        "deal_id": None,
        "source_url": URL,
        "checked_at": vendor_stamp,
        "records": recs,
    }
    fake = _Fake(MOVED_PAGE, NOW)
    rep = R.refresh([doc], fake, NOW)
    assert [r["result"] for r in rep] == ["changed", "changed", "changed"]
    expect = [float(MOVED_ON), float(MOVED_1MO), float(MOVED_3MO)]
    for rec, price in zip(recs, expect):
        assert rec["price_usd"] == rec["hourly_usd"] == price
        assert MOVED_LINE in rec["quote"] and MOVED_LINE in rec["evidence"]["quote"]
        assert rec["verified_at"] == rec["checked_at"] == rec["evidence"]["checked_at"] == "2026-11-25T14:32:32+00:00"
        assert rec.get("quote_id") is None
        assert "stale" not in rec
    assert fake.calls and all(u == URL for u in fake.calls)
    assert doc["checked_at"] == "2026-11-25T14:32:32+00:00"
