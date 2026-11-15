"""Fixture tests for Civo statusText stock parsing and public commitment prices.

Gigawatt: the H100 product page payload has statusText "In stock" that the
probe previously missed (feed showed unknown). Only firm 'In stock' /
'Out of stock' map; anything else stays unknown.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
import civo_probe as C  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _table(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _row(gpu="Small H100 SXM", secondary="1 x NVIDIA H100 - 80GB",
         status="In stock", hourly="$$2.99", monthly="$$2,182.70",
         c6="$$2.79", c12="$$2.69", c24="$$2.59", c36="$$2.49"):
    status_cell = {"variant": "status", "statusText": status, "primaryText": hourly}
    if status is None:
        status_cell.pop("statusText")
    return {
        "blockType": "pricingTable",
        "caption": "test",
        "headerRow": [{"headerText": "Model"}, {"headerText": "Status"}],
        "rows": [{
            "rowVariant": "cells",
            "cells": [
                {"variant": "text", "primaryText": gpu, "secondaryText": secondary},
                status_cell,
                {"variant": "price", "hourlyPrice": hourly, "monthlyPrice": monthly},
                {"variant": "commitment",
                 "commitment6": {"hourlyPrice": c6, "monthlyPrice": "$$2,036.70"},
                 "commitment12": {"hourlyPrice": c12, "monthlyPrice": "$$1,963.70"},
                 "commitment24": {"hourlyPrice": c24, "monthlyPrice": "$$1,890.70"},
                 "commitment36": {"hourlyPrice": c36, "monthlyPrice": "$$1,817.70"}},
            ],
        }],
    }


@pytest.mark.parametrize("raw,expected", [
    ("In stock", True),
    ("in stock", True),
    ("IN STOCK", True),
    ("  In   stock  ", True),
    ("Out of stock", False),
    ("out of stock", False),
    ("OUT OF STOCK", False),
    ("  Out of stock ", False),
    ("Available", None),
    ("Sold out", None),
    ("In-stock", None),
    ("in-stock", None),
    ("Limited", None),
    ("unknown", None),
    ("", None),
    (None, None),
    (True, None),
    (1, None),
    ({}, None),
])
def test_status_text_mapping_unknown_stays_unknown(raw, expected):
    assert C.parse_status_text(raw) is expected


def test_live_h100_fixture_in_stock_and_commitment_ladder():
    rows = C.parse_civo_product_page(_table("civo-h100-pricing-table.json"))
    assert len(rows) == 1
    r = rows[0]
    assert r["gpu"] == "H100 SXM" and r["vram_gb"] == 80
    assert r["status_text"] == "In stock" and r["in_stock"] is True
    assert r["ondemand_hourly_usd"] == 2.99
    assert r["commitments"][6]["hourly_usd"] == 2.79
    assert r["commitments"][12]["hourly_usd"] == 2.69
    assert r["commitments"][24]["hourly_usd"] == 2.59
    assert r["commitments"][36]["hourly_usd"] == 2.49  # also public; not required in the feed


def test_live_h100_html_flight_payload_parses():
    html = (FIXTURES / "civo-h100-page.html").read_text(encoding="utf-8")
    rows = C.parse_civo_product_page(html)
    assert rows and rows[0]["in_stock"] is True and rows[0]["gpu"] == "H100 SXM"


def test_live_a100_fixture_both_sizes_in_stock():
    rows = { (r["gpu"], r["vram_gb"]): r for r in C.parse_civo_product_page(_table("civo-a100-pricing-table.json")) }
    assert set(rows) == {("A100", 40), ("A100", 80)}
    a40, a80 = rows[("A100", 40)], rows[("A100", 80)]
    assert a40["in_stock"] is True and a40["status_text"] == "In stock"
    assert a80["in_stock"] is True and a80["status_text"] == "In stock"
    assert a40["ondemand_hourly_usd"] == 1.09
    assert a80["ondemand_hourly_usd"] == 1.79
    assert a40["commitments"][6]["hourly_usd"] == 0.99
    assert a40["commitments"][12]["hourly_usd"] == 0.89
    assert a40["commitments"][24]["hourly_usd"] == 0.79
    assert a80["commitments"][6]["hourly_usd"] == 1.69
    assert a80["commitments"][12]["hourly_usd"] == 1.59
    assert a80["commitments"][24]["hourly_usd"] == 1.49


def test_out_of_stock_maps_false():
    rows = C.parse_civo_product_page(_row(status="Out of stock"))
    assert rows[0]["in_stock"] is False and rows[0]["status_text"] == "Out of stock"


def test_other_status_and_missing_status_stay_unknown():
    limited = C.parse_civo_product_page(_row(status="Limited availability"))
    missing = C.parse_civo_product_page(_row(status=None))
    assert limited[0]["status_text"] == "Limited availability" and limited[0]["in_stock"] is None
    assert missing[0]["status_text"] is None and missing[0]["in_stock"] is None


def test_multi_gpu_rows_are_skipped():
    rows = C.parse_civo_product_page(_row(
        gpu="Extra Large H100 SXM", secondary="8 x NVIDIA H100 - 80GB"))
    assert rows == []


def test_unmapped_gpu_is_not_emitted():
    rows = C.parse_civo_product_page(_row(
        gpu="Small L40S", secondary="1 x NVIDIA L40S - 48GB"))
    assert rows == []


def test_availability_rows_cover_ondemand_and_6_12_24_month_tiers():
    parsed = C.parse_civo_product_page(_table("civo-h100-pricing-table.json"))
    rows = C.availability_rows(parsed, "https://www.civo.com/ai/h100-gpu", "2026-11-11T21:51:06Z")
    keys = {(r["gpu_model"], r["vram_gb"], r["tier"], r["in_stock"]) for r in rows}
    assert keys == {
        ("H100 SXM", 80, "On-demand", True),
        ("H100 SXM", 80, "6-month commitment", True),
        ("H100 SXM", 80, "12-month commitment", True),
        ("H100 SXM", 80, "24-month commitment", True),
    }
    assert all(r["vendor"] == "Civo" and r["price_usd_hr"] is None for r in rows)
    assert all(r["source_url"] == "https://www.civo.com/ai/h100-gpu" for r in rows)


def test_commitment_price_matches_fixture_ladder():
    html = (FIXTURES / "civo-h100-page.html").read_text(encoding="utf-8")
    rec = {"gpu": "H100 SXM", "vram_gb": 80, "tier": "6-month commitment"}
    price, quote, msg = C.commitment_price(rec, html)
    assert price == "2.79" and "parsed" in msg and "6-month commitment $2.79" in quote
    rec12 = {**rec, "tier": "12-month commitment"}
    assert C.commitment_price(rec12, html)[0] == "2.69"
    rec24 = {**rec, "tier": "24-month commitment"}
    assert C.commitment_price(rec24, html)[0] == "2.59"


def test_commitment_price_missing_cell_stays_unreadable():
    rec = {"gpu": "H100 SXM", "vram_gb": 80, "tier": "24-month commitment"}
    price, quote, msg = C.commitment_price(rec, _row(c24=None, c36=None))
    assert price is None and quote is None and "not on product page" in msg


# Verbatim visible /pricing text through the 6-month hourly cell (same style as on-demand quotes).
_PRICING_QUOTE_H100_6MO = (
    "Small 1 x NVIDIA H100 - 80GB 184 GB 23 200GB NVMe FREE $2.99 per hour $2,182.70 per month "
    "$2.79 per hour"
)
_PRICING_HTML = (
    "<html><body>Small 1 x NVIDIA H100 - 80GB 184 GB 23 200GB NVMe FREE "
    "$2.99 per hour $2,182.70 per month $2.79 per hour $2,036.70 per month "
    "$2.69 per hour $1,963.70 per month $2.59 per hour $1,890.70 per month "
    "$2.49 per hour $1,817.70 per month</body></html>"
)


def test_refresh_rereads_civo_reserved_from_pricing_visible_ladder():
    """Reserved Civo rows are confirmed on /pricing visible text, not the product-page flight payload.

    The /ai/h100-gpu no-JS page only shows on-demand and 36-month cells; 6/12/24-month
    amounts live in script JSON and are invisible to the live source check. verified_at
    moves only on a successful /pricing parse. last_failed_check_at is left in place.
    """
    import refresh_gpu_prices as R
    from datetime import datetime, timezone

    now = datetime(2026, 11, 15, 23, 10, tzinfo=timezone.utc)
    rec = {
        "gpu": "H100 SXM", "vram_gb": 80, "tier": "6-month commitment",
        "hourly_usd": 2.79, "price_usd": 2.79, "billing_unit": "hourly",
        "source_url": "https://www.civo.com/pricing",
        "verified_at": "2026-11-11T21:51:06+00:00",
        "checked_at": "2026-11-11T21:51:06+00:00",
        "last_failed_check_at": "2026-11-15T22:51:14+00:00",
        "quote": _PRICING_QUOTE_H100_6MO,
        "evidence": {"source_url": "https://www.civo.com/pricing",
                     "quote": _PRICING_QUOTE_H100_6MO,
                     "checked_at": "2026-11-11T21:51:06+00:00"},
    }
    doc = {"vendor": "Civo", "checked_at": "2026-11-11T22:09:21+00:00", "records": [rec]}

    class Fetcher:
        def __init__(self):
            self.fetched_at = {}
        def get(self, url):
            self.fetched_at[url] = now
            if url == "https://www.civo.com/pricing":
                return 200, _PRICING_HTML
            raise AssertionError(f"reserved reread must not fetch {url}")

    rep = R.refresh([doc], Fetcher(), now)
    assert rep[0]["result"] == "unchanged"  # price still 2.79
    assert rec["verified_at"] == rec["checked_at"] == "2026-11-15T23:10:00+00:00"
    assert rec["source_url"] == "https://www.civo.com/pricing"
    assert rec["evidence"]["source_url"] == "https://www.civo.com/pricing"
    assert rec["quote"] == rec["evidence"]["quote"] == _PRICING_QUOTE_H100_6MO
    assert rec.get("last_failed_check_at") == "2026-11-15T22:51:14+00:00"  # not overwritten on success


def test_refresh_civo_reserved_miss_does_not_restamp():
    import refresh_gpu_prices as R
    from datetime import datetime, timezone

    now = datetime(2026, 11, 15, 23, 10, tzinfo=timezone.utc)
    rec = {
        "gpu": "H100 SXM", "vram_gb": 80, "tier": "6-month commitment",
        "hourly_usd": 2.79, "price_usd": 2.79, "billing_unit": "hourly",
        "source_url": "https://www.civo.com/pricing",
        "verified_at": "2026-11-11T21:51:06+00:00",
        "checked_at": "2026-11-11T21:51:06+00:00",
        "quote": "Small H100 SXM 1 x NVIDIA H100 - 80GB On demand $2.99; Commitment 6 months $2.79 per hour",
        "evidence": {"source_url": "https://www.civo.com/pricing",
                     "quote": "Small H100 SXM 1 x NVIDIA H100 - 80GB On demand $2.99; Commitment 6 months $2.79 per hour",
                     "checked_at": "2026-11-11T21:51:06+00:00"},
    }
    doc = {"vendor": "Civo", "records": [rec]}

    class Fetcher:
        def __init__(self):
            self.fetched_at = {}
        def get(self, url):
            self.fetched_at[url] = now
            # Product pages are not a listed-price fallback; a /pricing miss must not restamp.
            return 200, "<html><body>no prices</body></html>"

    R.refresh([doc], Fetcher(), now)
    assert rec["verified_at"] == rec["checked_at"] == "2026-11-11T21:51:06+00:00"
    assert rec["last_failed_check_at"] == "2026-11-15T23:10:00+00:00"
    assert rec["source_url"] == "https://www.civo.com/pricing"
