"""P37 (Brain #584, agentsgot): effective_at separate from last_verified. P43 (eddie_compute): min_bill_usd_per_hour.
Additive, display only, never invented, ranking unchanged."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from core import contract, gpu_history, rate_dates
from core import deals as core

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
KEYS = rate_dates.EFFECTIVE_KEYS + rate_dates.MIN_BILL_KEYS


def _pt(day, price, status="ranked", t=None):
    return {"date": day, "price_usd": price, "hourly_usd": price, "status": status, "verified_at": t or f"{day}T18:00:00+00:00"}


def test_first_observed_after_a_real_change_only():
    pts = [_pt("2026-10-27", 2.0), _pt("2026-11-04", 2.5), _pt("2026-11-06", 2.5, "held")]  # status change keeps the run
    assert rate_dates.effective_at({"hourly_equiv_usd": 2.5}, {"points": pts}) == ("2026-11-04T18:00:00+00:00", "first_observed")
    # first price ever recorded: predates tracking -> null, never the tracking start date
    assert rate_dates.effective_at({"hourly_equiv_usd": 2.0}, {"points": [_pt("2026-10-27", 2.0)]}) == (None, None)
    # price moved after the latest snapshot -> not datable from history
    assert rate_dates.effective_at({"hourly_equiv_usd": 3.0}, {"points": pts}) == (None, None)
    # back in tracking after a gap: no observed change -> null
    gap = [_pt("2026-10-27", 2.0), _pt("2026-10-29", 2.0, "removed"), _pt("2026-11-02", 2.5)]
    assert rate_dates.effective_at({"hourly_equiv_usd": 2.5}, {"points": gap}) == (None, None)
    assert rate_dates.effective_at({"hourly_equiv_usd": 2.5}, None) == (None, None)
    # A -> B -> A: dated from the return to A, not the first A
    aba = [_pt("2026-10-27", 2.0), _pt("2026-11-01", 2.2), _pt("2026-11-05", 2.0)]
    assert rate_dates.effective_at({"hourly_equiv_usd": 2.0}, {"points": aba})[0] == "2026-11-05T18:00:00+00:00"


def test_vendor_stated_wins_unless_a_later_change_was_observed():
    pts = [_pt("2026-10-27", 6.99), _pt("2026-11-06", 7.99)]  # Lambda-style: future list seen before it took effect
    row = {"hourly_equiv_usd": 7.99, "price_effective_at": "2026-11-16T00:00:00Z"}
    assert rate_dates.effective_at(row, {"points": pts}) == ("2026-11-16T00:00:00Z", "vendor_stated")
    assert rate_dates.effective_at(row, None) == ("2026-11-16T00:00:00Z", "vendor_stated")
    later = pts + [_pt("2026-12-01", 8.49)]
    assert rate_dates.effective_at({**row, "hourly_equiv_usd": 8.49}, {"points": later}) == ("2026-12-01T18:00:00+00:00", "first_observed")
    assert rate_dates.effective_at({**row, "price_effective_at": "not a date"}, None) == (None, None)


def test_min_bill():
    assert rate_dates.min_bill({"min_gpus": 8, "hourly_equiv_usd": 6.155, "billing_unit": "hourly"}) == (49.24, "hourly_rate")
    assert rate_dates.min_bill({"min_gpus": 1, "hourly_equiv_usd": 3.9492, "billing_unit": "per-second"}) == (3.9492, "per_second_rate")
    assert rate_dates.min_bill({"min_gpus": 4, "hourly_equiv_usd": 1.6024, "billing_unit": "monthly"}) == (6.4096, "monthly_equivalent")
    assert rate_dates.min_bill({"min_gpus": 2, "hourly_usd": 1.5, "billing_unit": "hourly"}) == (3.0, "hourly_rate")  # MCP row shape
    for bad in ({"hourly_equiv_usd": 2.0}, {"min_gpus": None, "hourly_equiv_usd": 2.0}, {"min_gpus": 2, "hourly_equiv_usd": None},
                {"min_gpus": True, "hourly_equiv_usd": 2.0}, {"min_gpus": 0, "hourly_equiv_usd": 2.0}):
        assert rate_dates.min_bill(bad) == (None, None)


def test_committed_feed_matches_history_and_inputs():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    hist = gpu_history.build_history(gpu_history.load_snapshots())
    series = {s["key"]: s for s in hist["series"]}
    for r in feed["rates"]:
        assert set(KEYS) <= set(r)
        assert (r["effective_at"], r["effective_at_basis"]) == rate_dates.effective_at(r, series.get(rate_dates.series_key(r)))
        assert r["min_bill_usd_per_hour"] == round(r["min_gpus"] * r["hourly_equiv_usd"], 6)
        assert (r["effective_at"] is None) == (r["effective_at_basis"] is None)
        if r["effective_at_basis"] == "first_observed":  # never later than our last confirmation
            assert r["effective_at"] <= r["last_verified"] or r["effective_at"][:10] <= r["last_verified"][:10]
    assert any(r["effective_at_basis"] == "first_observed" for r in feed["rates"])
    assert any(r["min_bill_basis"] == "monthly_equivalent" for r in feed["rates"])


def test_mcp_rows_full_brief_and_ranking_unchanged():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    stripped = copy.deepcopy(feed)
    for r in stripped["rates"]:
        for k in KEYS:
            r.pop(k, None)
    for gpu, n in (("H100", None), ("A100", None), ("RTX 5090", None), ("H100", 8), ("B200", 8)):
        a = core.compare_gpu_prices(feed, gpu, limit=25, now=T0, gpus=n)
        b = core.compare_gpu_prices(stripped, gpu, limit=25, now=T0, gpus=n)
        assert [x["rate_id"] for x in a["results"]] == [x["rate_id"] for x in b["results"]], gpu  # ranking unchanged
        for x, y in zip(a["results"], b["results"]):
            assert x["min_bill_usd_per_hour"] == y["min_bill_usd_per_hour"] == round(x["min_gpus"] * x["hourly_usd"], 6)
            assert y["effective_at"] is None  # an older feed without the field: null, never guessed
        for e in a["excluded_min_gpus"]:
            assert e["min_bill_usd_per_hour"] == round(e["min_gpus"] * e["hourly_usd"], 6)
        full = contract.finalize("compare_gpu_prices", copy.deepcopy(a), "full")
        brief = contract.finalize("compare_gpu_prices", copy.deepcopy(a), "brief")
        for f, br in zip(full["results"], brief["results"]):
            assert set(KEYS) <= set(f)
            assert ("effective_at" in br) == bool(f["effective_at"])
            assert ("min_bill_usd_per_hour" in br) == ((f["min_gpus"] or 1) > 1)
    h8 = core.compare_gpu_prices(feed, "H100", limit=25, now=T0, gpus=8)["results"]
    assert any(x["min_gpus"] == 8 and x["min_bill_usd_per_hour"] == round(8 * x["hourly_usd"], 6) for x in h8)


def test_schema_and_manifest_lockstep():
    s = contract.output_schema("compare_gpu_prices")["properties"]["results"]["items"]["properties"]
    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    tool = next(t for t in plugin["tools"] if t["name"] == "compare_gpu_prices")
    p = tool["outputSchema"]["properties"]["results"]["items"]["properties"]
    for k in KEYS:
        assert p[k] == s[k] and "null" in s[k]["type"]
    doc = (ROOT / "docs/GPU-PRICES-FIELDS.md").read_text()
    assert all(f"`{k}`" in doc for k in KEYS)
