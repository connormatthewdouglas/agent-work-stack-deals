"""Focused tests for outside-feedback PR: per-row read time, in-stock median footnote, weekday break-even."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import gpu_pages as gp  # noqa: E402


NOW = datetime(2026, 11, 11, 21, 31, 38, tzinfo=timezone.utc)


def _esc(s):
    return escape(str(s or ""), quote=True)


def _gen():
    return SimpleNamespace(esc=_esc, BASE="https://thelanternworks.com",
                           slug_for=lambda deal_id: str(deal_id or "example"))


def _rate(**kw):
    row = {
        "advertiser": "Example Cloud",
        "gpu": "H100 SXM",
        "vram_gb": 80,
        "tier": "On-demand",
        "tier_class": "on-demand",
        "unit": "hour",
        "price_usd": 2.5,
        "hourly_equiv_usd": 2.5,
        "monthly_cost_usd": 250.0,
        "server_price_usd": 2.5,
        "gpu_count": 1,
        "min_gpus": 1,
        "price_status": "listed",
        "source_url": "https://example.invalid/pricing",
        "redeem_url": "https://example.invalid/pricing",
        "affiliate": False,
        "checked_at": "2026-11-11T18:31:38Z",
        "verified_at": "2026-11-11T18:31:38Z",
        "evidence": {"quote": "H100 $2.50/hr", "checked_at": "2026-11-11T18:31:38Z"},
        "availability": {"status": "in stock when checked", "in_stock": True, "checked_at": "2026-11-11T18:31:38Z"},
        "interruptible": False,
        "canonical_model": "H100",
        "form_factor": "SXM",
        "deal_id": "example-h100",
        "billing": "hourly",
        "billing_unit": "hourly",
    }
    row.update(kw)
    return row


def test_read_time_html_known_and_unknown():
    html = gp.read_time_html(_rate(), now=NOW)
    assert 'datetime="2026-11-11T18:31:38Z"' in html
    assert ">read 3h ago</time>" in html
    assert gp.read_time_html({"advertiser": "X"}, now=NOW) == "read time unknown"
    assert gp.read_time_html({"checked_at": "not-a-timestamp"}, now=NOW) == "read time unknown"


def test_read_time_html_never_fakes_future_ago():
    future = _rate(checked_at="2026-11-12T21:31:38Z", verified_at="2026-11-12T21:31:38Z")
    html = gp.read_time_html(future, now=NOW)
    assert "ago" not in html
    assert 'datetime="2026-11-12T21:31:38Z"' in html
    assert "read at 2026-11-12T21:31:38Z" in html


def test_table_one_includes_per_row_read_time(monkeypatch):
    monkeypatch.setattr(gp, "read_clock", lambda: NOW)
    row = _rate()
    html = gp._table_one(_gen(), [row], {gp._key(row): 1825.0})
    assert "<th>Read</th>" in html
    assert 'datetime="2026-11-11T18:31:38Z"' in html
    assert "read 3h ago" in html
    missing = _rate(checked_at=None, verified_at=None, evidence={"quote": "n/a"})
    html2 = gp._table_one(_gen(), [missing], {gp._key(missing): 1825.0})
    assert "read time unknown" in html2


def test_marketplace_median_footnote_matches_in_stock_code():
    # Truth check: Vast and Clore median helpers filter to in-stock / available listings.
    import inspect
    import refresh_gpu_prices
    import build_clore
    src = inspect.getsource(refresh_gpu_prices.market_stats)
    assert "not o.get(\"rented\")" in src and "o.get(\"rentable\", True)" in src
    clore_src = inspect.getsource(build_clore.build)
    assert "if rented: continue" in clore_src
    assert "median=round(statistics.median(av)" in clore_src

    mkt = _rate(
        price_status="marketplace",
        offer_count=12,
        lowest_offer_usd=1.1,
        price_basis="median per-GPU price of available on-demand host listings priced in USD",
        advertiser="Clore.ai",
    )
    listed = _rate()
    assert "from in-stock listings only" in gp._rate_str(mkt)
    assert "in-stock listings only" not in gp._rate_str(listed)
    assert gp.MARKETPLACE_MEDIAN_FOOTNOTE in gp.median_footnote_html([mkt])
    assert gp.median_footnote_html([listed]) == ""


def test_price_cell_marketplace_footnote():
    import spec_pages as sp
    mkt = _rate(price_status="marketplace", offer_count=12, lowest_offer_usd=1.1)
    assert "from in-stock listings only" in sp.price_cell(_gen(), mkt)
    assert "in-stock listings only" not in sp.price_cell(_gen(), _rate())


def test_no_stock_reading_rows_are_labelled_and_not_colour_only(monkeypatch):
    monkeypatch.setattr(gp, "read_clock", lambda: NOW)
    checked = _rate()
    unknown = _rate(
        advertiser="Quiet Cloud",
        gpu="H100 PCIe",
        availability={"status": "unknown", "in_stock": None, "note": "No availability signal"},
        checked_at="2026-11-11T17:31:38Z",
        verified_at="2026-11-11T17:31:38Z",
    )
    html = gp._table_one(
        _gen(),
        [checked, unknown],
        {gp._key(checked): 1825.0, gp._key(unknown): 1825.0},
    )
    assert 'class="stock-checked"' in html
    assert 'class="no-stock-reading"' in html
    assert "No stock reading" in html
    assert "stock-reading-label" in html
    assert "visually separated" in html
    # Order is unchanged: stock-checked row still first because that is how the caller ranked them.
    first = html.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    assert "Example Cloud" in first and "Quiet Cloud" not in first


def test_calculator_break_even_already_has_weekday_hours():
    """#160 already shows hours/weekday next to calendar % on the calculator; no other display exists."""
    src = (ROOT / "scripts" / "gpu_calculator.py").read_text(encoding="utf-8")
    assert "21.7 weekdays/month" in src
    assert "% of calendar time, which is" in src
    assert "hours/weekday" in src
    # No other generator or API doc shows a calendar % break-even without the weekday figure.
    hits = []
    for path in list((ROOT / "scripts").glob("*.py")) + list((ROOT / "docs").rglob("*")) + list((ROOT / "methodology").rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md", ".html"}:
            continue
        if path.name == "gpu_calculator.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "break-even" in text or "breaks even" in text:
            hits.append(str(path.relative_to(ROOT)))
    assert hits == [], hits
