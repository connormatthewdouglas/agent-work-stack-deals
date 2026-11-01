"""Gauge EOD Nov 1: G1 (held != unpriced), G3 (on-demand label), G4 (median count), G5 (batch rows), G6 (future timestamps), G7 (2 decimals)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from core.deals import usd  # noqa: E402

FEED = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())


def test_g7_usd():
    assert [usd(x) for x in (2.6, 0.555, 0.8045, 3, 1.99)] == ["$2.60", "$0.555", "$0.8045", "$3.00", "$1.99"]
    assert "$2.6/hr" not in (ROOT / "gpu/cheapest-h100-rental/index.html").read_text()


def test_g1_held_vendor_not_unpriced():
    held = {h["vendor"] for h in FEED["held_stale"]}
    assert not held & {u["advertiser"] for u in FEED["unpriced"]}


def test_g3_on_demand_label():
    html = (ROOT / "gpu/cheapest-h100-rental/index.html").read_text()
    assert "cheapest H100 94GB" not in html


def test_g4_median_count():
    med = [r for r in FEED["rates"] if r.get("offer_count") or "median" in str(r.get("price_basis") or "").lower()]
    home = (ROOT / "index.html").read_text()
    assert f"{len(med)} of those rows are marketplace medians" in home


def test_g5_batch_rows_labelled_and_held_after_48h():
    b = [r for r in FEED["rates"] if r.get("price_check") == "batch"]
    assert b and all(r["last_read"] and r["hold_after"] for r in b)
    now = datetime.now(timezone.utc)
    assert all(datetime.fromisoformat(r["hold_after"]) > now - timedelta(minutes=30) for r in b)


def test_g6_future_timestamp_fails():
    import validate_feed as vf
    vf.errors.clear()
    vf.check_no_future_timestamps(datetime.now(timezone.utc) - timedelta(days=3))
    assert vf.errors
    vf.errors.clear()
    vf.check_no_future_timestamps()
    assert not vf.errors
