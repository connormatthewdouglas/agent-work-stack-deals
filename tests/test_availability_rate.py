"""T116: stock checks describe observations, never prices, budgets, or predicted bills."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from core import availability_rate as A

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 6, 7, tzinfo=timezone.utc)


def setup_window(monkeypatch, known, stocked, unknown, age=1):
    end = (NOW - timedelta(hours=age)).isoformat()
    k = ("V", "H100 SXM", 80, "On-demand")
    monkeypatch.setenv("LW_AVAIL_NOW", NOW.isoformat())
    monkeypatch.setattr(A, "_SCOUT", {})
    monkeypatch.setattr(A, "_SCOUT_AT", None)
    monkeypatch.setattr(A, "_CACHE", {"window_start": (NOW - timedelta(days=7)).isoformat(),
        "window_end": end, "rows": {k: {"checks": known, "in_stock_checks": stocked,
        "unknown_checks": unknown, "last_check_at": end}}})
    return k


@pytest.mark.parametrize("known,stocked,unknown,rate,status", [
    (10, 5, 2, .5, "observed"), (100, 0, 5, 0, "observed"),
    (100, 1, 0, .01, "observed"), (2, 1, 8, .5, "insufficient_sample"),
    (0, 0, 10, None, "all_unknown")])
def test_zero_low_sparse_unknown_never_become_dollars(monkeypatch, known, stocked, unknown, rate, status):
    k = setup_window(monkeypatch, known, stocked, unknown)
    for hourly in (0, 2, 200, None):
        f = A.fields(*k, hourly)
        assert f["expected_cost_usd"] is None and "deprecated" in f["expected_cost_label"]
        r = f["availability_rate_7d"]
        assert r["rate"] == rate and r["sample_status"] == status
        assert r["known_checks"] == known and r["unknown_checks"] == unknown
        assert r["total_checks"] == known + unknown and r["window_days"] == 7
        assert r["window_start"] and r["window_end"] and not r["window_stale"]


def test_old_window_remains_explicitly_historical(monkeypatch):
    k = setup_window(monkeypatch, 10, 1, 4, age=72)
    f = A.fields(*k, 2)
    assert f["expected_cost_usd"] is None
    assert f["availability_rate_7d"]["window_stale"]
    assert f["availability_rate_7d"]["rate"] == .1


def test_unknown_counts_not_invented_for_old_capture(monkeypatch):
    k = setup_window(monkeypatch, 10, 5, None)
    r = A.fields(*k, 2)["availability_rate_7d"]
    assert r["unknown_checks"] is None and r["total_checks"] is None
    assert A.fields("missing", "L4", 24, "On-demand", 1)["availability_rate_7d"] is None


def test_scout_all_unknown_and_sparse_counts_preserved(monkeypatch):
    monkeypatch.setenv("LW_AVAIL_NOW", NOW.isoformat())
    for known, stocked in [(0, 0), (2, 1)]:
        sr = {"checks_7d": 10, "known_checks_7d": known, "in_stock_checks_7d": stocked,
              "sufficient_sample": False, "first_check_at": (NOW-timedelta(days=6)).isoformat(),
              "last_check_at": NOW.isoformat()}
        monkeypatch.setattr(A, "_SCOUT", {("v", "H100", 80, "On-demand"): (sr, NOW.isoformat())})
        monkeypatch.setattr(A, "_SCOUT_AT", None)
        f = A.fields("V", "H100", 80, "On-demand", 2)
        assert f["expected_cost_usd"] is None
        assert f["availability_rate_7d"]["unknown_checks"] == 10-known
        assert not f["availability_rate_7d"]["sufficient_sample"]


def test_compute_budget_ignores_legacy_availability_dollars():
    from core.cost_per_job import estimate_job_cost
    r = {"advertiser": "V", "gpu": "H100", "vram_gb": 80, "price_usd": 2,
         "unit": "hour", "tier": "On-demand", "tier_class": "on-demand",
         "verified_at": datetime.now(timezone.utc).isoformat(), "expected_cost_usd": 2000}
    a = estimate_job_cost({"rates": [r]}, "H100", 1, job_hours=10)
    s = copy.deepcopy(r); s["expected_cost_usd"] = None
    b = estimate_job_cost({"rates": [s]}, "H100", 1, job_hours=10)
    assert a["results"] == b["results"] and a["budget_verdict"] == b["budget_verdict"]


def test_feed_legacy_field_is_explicitly_deprecated():
    rates = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]
    assert all(r["expected_cost_usd"] is None and "deprecated" in r["expected_cost_label"] for r in rates)


def test_rate_phrase_zero_of_n_and_small_sample():
    # 0/16 with a 40 h window is a firm 0/N reading, not "out of stock" / "sold out".
    ar = {"known_checks": 16, "in_stock_checks": 0, "sample_status": "observed",
          "sufficient_sample": True, "observed_hours": 40.1}
    assert A.rate_phrase(ar) == "not observed in stock in 16 checks"
    assert A.zero_of_n_phrase(ar) == "not observed in stock in 16 checks"
    one = {**ar, "known_checks": 1, "sufficient_sample": False, "sample_status": "insufficient_sample", "observed_hours": 0}
    assert A.rate_phrase(one) == (
        "not observed in stock in 1 check (small sample, N=1; treat availability as price-only)")

    assert not A.is_small_sample(ar)
    # K/N is descriptive; a 2-check window is flagged as a small sample / price-only.
    small = {"known_checks": 2, "in_stock_checks": 2, "sample_status": "insufficient_sample",
             "sufficient_sample": False, "observed_hours": 2.7}
    assert A.rate_phrase(small) == (
        "observed in stock in 2 of 2 checks (small sample, N=2; treat availability as price-only)")
    assert A.zero_of_n_phrase(small) is None
    assert A.is_small_sample(small)
    # 8 checks over a short window is also a small sample.
    mid = {"known_checks": 8, "in_stock_checks": 0, "sample_status": "observed",
           "sufficient_sample": True, "observed_hours": 18}
    assert A.is_small_sample(mid)
    assert "not observed in stock in 8 checks" in A.rate_phrase(mid)
    assert "small sample, N=8" in A.rate_phrase(mid)
    assert A.rate_phrase(None) is None
    assert A.rate_phrase({"known_checks": 0, "in_stock_checks": 0}) is None
    assert "2.7 hours" in A.RATE_FOOTNOTE and "price-only" in A.RATE_FOOTNOTE
    # Footnote must not use the old 0/N wording the pages are retiring.
    assert "out of stock" not in A.RATE_FOOTNOTE.lower()
    assert "sold out" not in A.RATE_FOOTNOTE.lower()


def test_scout_t112_age_uses_pinned_clock_not_wall_clock(monkeypatch, tmp_path):
    """The T112 24h freshness window must follow LW_AVAIL_NOW, not datetime.now().

    After a later merge moves feed_updated_at (e.g. Lium), a refresh job pins
    LW_AVAIL_NOW to now and regenerates. Dest-worktree pages-match tests then
    rebuild HEAD at the committed feed stamp. If T112 age used wall clock, a
    file still inside the 24h window at that stamp would flip to git_history
    and the provenance/sitemap tests would fail (refresh run 43616682835).
    """
    import json
    gen = "2026-11-13T14:59:21Z"
    pin_inside = "2026-11-14T07:00:07Z"  # 16h later, still inside 24h
    pin_outside = "2026-11-14T15:00:00Z"  # just over 24h
    doc = {"kind": "t112_availability_rate_inputs", "generated_at": gen, "rows": [
        {"vendor": "Civo", "gpu_model": "H100 SXM", "vram_gb": 80, "tier": "On-demand",
         "checks_7d": 16, "known_checks_7d": 16, "in_stock_checks_7d": 16,
         "first_check_at": "2026-11-11T22:53:00Z", "last_check_at": "2026-11-13T14:57:59Z"}]}
    path = tmp_path / "scout_rate_7d.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(A, "SCOUT_PATH", path)
    monkeypatch.setattr(A, "_CACHE", {"window_start": None, "window_end": None, "rows": {}})
    monkeypatch.setattr(A, "_SCOUT", None)
    monkeypatch.setattr(A, "_SCOUT_AT", None)
    # Stale load first: a sticky cache would keep the empty map when the pin moves back inside.
    monkeypatch.setenv("LW_AVAIL_NOW", pin_outside)
    f = A.fields("Civo", "H100 SXM", 80, "On-demand", 2)
    assert f["availability_rate_7d"] is None
    monkeypatch.setenv("LW_AVAIL_NOW", pin_inside)
    f = A.fields("Civo", "H100 SXM", 80, "On-demand", 2)
    assert f["availability_rate_7d"]["source"] == "scout_t112"
    assert f["availability_rate_7d"]["checks"] == 16
    monkeypatch.setenv("LW_AVAIL_NOW", pin_outside)
    f = A.fields("Civo", "H100 SXM", 80, "On-demand", 2)
    assert f["availability_rate_7d"] is None

