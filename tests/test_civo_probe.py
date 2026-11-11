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
