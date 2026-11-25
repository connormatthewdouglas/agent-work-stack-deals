"""F2 (Brain #1029): price_trend from existing history — no invented days or prices."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import gpu_history as H  # noqa: E402
from core.deals import compare_gpu_prices  # noqa: E402
from core.ids import rate_id  # noqa: E402

LAST = "2026-11-23"
FIRST = "2026-10-27"
# Contiguous except the real archive gap of 2026-11-07 and 2026-11-08, which must not be invented.
DATES = [d for i in range((datetime.fromisoformat(LAST) - datetime.fromisoformat(FIRST)).days + 1)
         if (d := (datetime.fromisoformat(FIRST) + timedelta(days=i)).date().isoformat()) not in ("2026-11-07", "2026-11-08")]


def _sid(d):
    return f"{d}.deadbeef"


def _pt(day, price, status="ranked", verified=None):
    return {"date": day, "price_usd": price, "hourly_usd": price, "status": status,
            "verified_at": verified or f"{day}T12:00:00+00:00"}


def _series(points, vendor="Acme", gpu="H100", rid="r_aaaaaaaaaaaa"):
    return {"key": f"{vendor}|{gpu}|On-demand|80|1", "rate_id": rid, "vendor": vendor, "gpu": gpu,
            "tier": "On-demand", "vram_gb": 80, "gpu_count": 1, "points": points,
            "first_seen": points[0]["date"], "last_seen": points[-1]["date"]}


def _hist(series, dates=DATES):
    return {"first_snapshot": dates[0], "last_snapshot": dates[-1], "snapshot_count": len(dates),
            "snapshot_ids": [_sid(d) for d in dates], "series": series if isinstance(series, list) else [series],
            "changes": []}


def _live(price=2.0, hours_old=1.0, reason=None, in_stock=None, sold=False, undated=False):
    ts = None if undated else (datetime(2026, 11, 23, 12, tzinfo=timezone.utc) - timedelta(hours=hours_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    av = {"in_stock": False if sold else in_stock, "availability_reason": reason}
    if reason:
        av["availability_reason"] = reason
    row = {"advertiser": "Acme", "gpu": "H100", "vram_gb": 80, "tier": "On-demand", "hourly_equiv_usd": price,
           "billing_unit": "hourly", "gpu_count": 1, "availability": av, "availability_reason": reason,
           "in_stock": False if sold else in_stock}
    if ts:
        row["checked_at"] = row["verified_at"] = ts
    return row


NOW = datetime(2026, 11, 23, 18, tzinfo=timezone.utc)


def test_snapshot_dates_do_not_invent_the_nov_7_8_gap():
    assert "2026-11-07" not in DATES and "2026-11-08" not in DATES
    assert H.snapshot_dates(_hist(_series([_pt(FIRST, 2.0)]))) == DATES


def test_down_up_flat_deadband():
    # 11-17 start 2.00, 11-23 end 1.80 -> -10% down. Enough ranked days (7).
    s = _series([_pt("2026-11-17", 2.00), _pt("2026-11-23", 1.80)])
    w = {x["days"]: x for x in H.price_trend(s, history=_hist(s), live=_live(), now=NOW, windows=[7])["windows"]}
    assert w[7]["direction"] == "down" and w[7]["pct"] == -10.0 and w[7]["start_usd"] == 2.0 and w[7]["end_usd"] == 1.8
    assert w[7]["ranked_days"] == 7 and w[7]["start_at"].endswith("Z") and w[7]["end_at"].endswith("Z")
    # +2.0% is up; +1.9% is flat
    s = _series([_pt("2026-11-17", 2.00), _pt("2026-11-23", 2.04)])
    assert H.price_trend(s, history=_hist(s), live=_live(2.04), now=NOW, windows=[7])["windows"][0]["direction"] == "up"
    s = _series([_pt("2026-11-17", 2.00), _pt("2026-11-23", 2.038)])  # 1.9%
    assert H.price_trend(s, history=_hist(s), live=_live(2.038), now=NOW, windows=[7])["windows"][0]["direction"] == "flat"
    s = _series([_pt("2026-11-17", 2.00), _pt("2026-11-23", 1.96)])  # -2.0% down
    assert H.price_trend(s, history=_hist(s), live=_live(1.96), now=NOW, windows=[7])["windows"][0]["direction"] == "down"


def test_carry_forward_stable_price_is_flat():
    # A single ranked change point carried across the whole 7d window is a valid flat, not insufficient.
    s = _series([_pt("2026-10-27", 3.50)])
    w = H.price_trend(s, history=_hist(s), live=_live(3.50), now=NOW, windows=[7])["windows"][0]
    assert w["direction"] == "flat" and w["pct"] == 0.0 and w["start_usd"] == w["end_usd"] == 3.50
    assert w["ranked_days"] == 7 and "reason" not in w


def test_held_and_removed_points_are_excluded():
    # Mid-window held days do not count; a removed tail is not a ranked end.
    points = [_pt("2026-11-17", 2.0), _pt("2026-11-19", 2.0, "held"), _pt("2026-11-21", 2.0), _pt("2026-11-23", 1.5)]
    s = _series(points)
    w = H.price_trend(s, history=_hist(s), live=_live(1.5), now=NOW, windows=[7])["windows"][0]
    # 11-17,18 ranked (carry 2.0); 11-19,20 held; 11-21,22,23 ranked. ranked_days=5.
    assert w["ranked_days"] == 5 and w["end_usd"] == 1.5 and w["start_usd"] == 2.0
    # Removed on last day: no end price -> insufficient
    s = _series([_pt("2026-11-17", 2.0), _pt("2026-11-23", 2.0, "removed")])
    w = H.price_trend(s, history=_hist(s), live=_live(), now=NOW, windows=[7])["windows"][0]
    assert w["reason"] == "insufficient_points"


def test_missing_snapshot_days_are_not_invented():
    s = _series([_pt("2026-10-27", 2.0)])
    dates = H.snapshot_dates(_hist(s))
    assert "2026-11-07" not in dates and "2026-11-08" not in dates
    # A 30-day window starting before first_snapshot is not filled with invented prices.
    w = {x["days"]: x for x in H.price_trend(s, history=_hist(s), live=_live(), now=NOW)["windows"]}
    assert w[30]["reason"] == "window_exceeds_history" and "pct" not in w[30]


def test_insufficient_ranked_days():
    # Only 3 ranked days in the 7d window (11-21,22,23); need 4.
    s = _series([_pt("2026-11-21", 2.0)])
    w = H.price_trend(s, history=_hist(s), live=_live(), now=NOW, windows=[7])["windows"][0]
    assert w["reason"] == "insufficient_points" and w["ranked_days"] == 3


@pytest.mark.parametrize("kw,reason", [
    (dict(held=True), "held_stale"),
    (dict(live=_live(reason="no_source")), "no_source"),
    (dict(live=_live(sold=True)), "sold_out"),
    (dict(live=_live(hours_old=49)), "stale"),
    (dict(live=_live(undated=True)), "undated"),
])
def test_live_stale_held_no_source_sold_out_block_the_whole_trend(kw, reason):
    s = _series([_pt("2026-10-27", 2.0), _pt("2026-11-23", 1.0)])  # would otherwise be a downtrend
    live = kw.get("live", _live())
    out = H.price_trend(s, history=_hist(s), live=live, held=kw.get("held", False), now=NOW)
    assert out["trend"] is None and out["trend_reason"] == reason and out["windows"] == []


def test_utc_z_and_plus00_verified_at():
    s = _series([_pt("2026-11-17", 2.0, verified="2026-11-17T12:00:00+00:00"),
                 _pt("2026-11-23", 1.5, verified="2026-11-23T08:30:00+00:00")])
    w = H.price_trend(s, history=_hist(s), live=_live(), now=NOW, windows=[7])["windows"][0]
    assert w["start_at"] == "2026-11-17T12:00:00Z" and w["end_at"] == "2026-11-23T08:30:00Z"
    tr = H.price_trend(s, history=_hist(s), live=_live(), now=NOW, windows=[7])
    assert tr["as_of"].endswith("Z") and "T" in tr["as_of"]


def test_history_unavailable_and_no_series():
    assert H.price_trend(None, history={"error": "boom", "series": []}, live=_live(), now=NOW)["trend_reason"] == "history_unavailable"
    assert H.price_trend(None, history=_hist([]), live=_live(), now=NOW)["trend_reason"] == "insufficient_points"


def test_compare_gpu_prices_adds_trend_without_bloating_history_view():
    fresh = (NOW - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = _live(1.80, hours_old=6)
    row.update({"hourly_equiv_usd": 1.80, "verified_at": fresh, "checked_at": fresh, "tier": "On-demand",
                "source_url": "https://acme.example/p"})
    rid = rate_id({**row, "vendor": "Acme"})
    s = _series([_pt("2026-11-17", 2.00), _pt("2026-11-23", 1.80)], rid=rid)
    data = {"rates": [row], "held_stale": [], "hours_per_month": 730}
    out = compare_gpu_prices(data, "H100", 5, history=_hist(s), include_history=False, now=NOW, on_demand_only=False)
    assert "history" not in out and "price_history" not in out["results"][0]
    tr = out["results"][0]["trend"]
    assert tr and tr["windows"][0]["direction"] == "down" and tr["as_of"].endswith("Z")
    with_h = compare_gpu_prices(data, "H100", 5, history=_hist(s), include_history=True, now=NOW, on_demand_only=False)
    assert "history" in with_h and with_h["results"][0]["price_history"]
    # default include_history=None keeps the old "history= means include_history" behaviour
    legacy = compare_gpu_prices(data, "H100", 5, history=_hist(s), now=NOW, on_demand_only=False)
    assert "history" in legacy


def _dates_to(last: str, first: str = FIRST, skip=("2026-11-07", "2026-11-08")) -> list[str]:
    d0, d1 = datetime.fromisoformat(first), datetime.fromisoformat(last)
    return [d for i in range((d1 - d0).days + 1)
            if (d := (d0 + timedelta(days=i)).date().isoformat()) not in skip]


def test_30d_exceeds_history_until_archive_spans_30_days():
    """Inclusive window start is last-(days-1). A 29-day archive still starts before first_snapshot;
    a 30-day archive fits. window_exceeds_history takes precedence over insufficient_points.
    A series held on last_snapshot has no end price and is insufficient_points once the window fits.
    """
    ranked = _series([_pt(FIRST, 2.0)])
    h29 = _hist(ranked, dates=_dates_to("2026-11-24"))
    assert (date.fromisoformat(h29["last_snapshot"]) - date.fromisoformat(h29["first_snapshot"])).days + 1 == 29
    w = {x["days"]: x for x in H.price_trend(ranked, history=h29, live=_live(2.0), now=NOW)["windows"]}
    assert w[30]["reason"] == "window_exceeds_history" and "pct" not in w[30]
    # Precedence: even a short series on a 29-day archive is exceeds, not insufficient_points.
    short = _series([_pt("2026-11-24", 2.0)])
    w = {x["days"]: x for x in H.price_trend(short, history=_hist(short, dates=_dates_to("2026-11-24")), live=_live(2.0), now=NOW)["windows"]}
    assert w[30]["reason"] == "window_exceeds_history"
    h30 = _hist(ranked, dates=_dates_to("2026-11-25"))
    assert (date.fromisoformat(h30["last_snapshot"]) - date.fromisoformat(h30["first_snapshot"])).days + 1 == 30
    w = {x["days"]: x for x in H.price_trend(ranked, history=h30, live=_live(2.0), now=NOW)["windows"]}
    assert "reason" not in w[30] and w[30]["direction"] == "flat" and w[30]["ranked_days"] >= 10
    held = _series([_pt(FIRST, 2.0), _pt("2026-11-25", 2.0, "held")])
    w = {x["days"]: x for x in H.price_trend(held, history=_hist(held, dates=_dates_to("2026-11-25")), live=_live(2.0), now=NOW)["windows"]}
    assert w[30]["reason"] == "insufficient_points" and "pct" not in w[30]


def _assert_window_follows_design(w: dict, first: str, last: str) -> None:
    """Structural + precedence check. Does not pin a frozen reason to the live archive length."""
    assert isinstance(w.get("days"), int) and w["days"] >= 1
    start = (date.fromisoformat(last) - timedelta(days=w["days"] - 1)).isoformat()
    if start < first:
        assert w.get("reason") == "window_exceeds_history" and "direction" not in w and "pct" not in w
        return
    if "reason" in w:
        assert w["reason"] == "insufficient_points" and "direction" not in w and "pct" not in w
        assert isinstance(w.get("ranked_days"), int) and w["ranked_days"] >= 0
        return
    assert w["direction"] in ("up", "down", "flat")
    assert isinstance(w.get("pct"), (int, float))
    assert str(w.get("start_at") or "").endswith("Z") and "T" in w["start_at"]
    assert str(w.get("end_at") or "").endswith("Z") and "T" in w["end_at"]
    assert isinstance(w.get("ranked_days"), int) and w["ranked_days"] >= 0


def _assert_history_shape(hist: dict, now: datetime) -> None:
    assert hist["first_snapshot"] and hist["last_snapshot"]
    for sid in hist.get("snapshot_ids") or []:
        assert isinstance(sid, str) and len(sid) >= 10 and sid[4] == "-" and sid[7] == "-"
    dummy = {"verified_at": f"{hist['last_snapshot']}T12:00:00Z", "hourly_equiv_usd": 1.0}
    for s in hist.get("series") or []:
        for p in s.get("points") or []:
            assert p.get("status") in ("ranked", "held", "removed")
        if not s.get("points"):
            continue
        live = {**dummy, "hourly_equiv_usd": s["points"][-1].get("hourly_usd") or 1.0}
        tr = H.price_trend(s, history=hist, live=live, now=now)
        if tr.get("as_of"):
            assert tr["as_of"].endswith("Z") and "T" in tr["as_of"]
        for w in tr.get("windows") or []:
            _assert_window_follows_design(w, hist["first_snapshot"], hist["last_snapshot"])


def test_committed_history_json_unchanged():
    """Live history must stay a faithful build_history() of committed snapshots.

    Window reasons are checked structurally (UTC Z, valid statuses/reasons, design precedence)
    and are not pinned to a single frozen value — a new snapshot day can move 30d from
    window_exceeds_history to a computable trend or insufficient_points.
    """
    snaps = H.load_snapshots()
    path = ROOT / "api" / "v1" / "gpu-prices" / "history.json"
    raw = path.read_text()
    hist = json.loads(raw)
    assert hist == {**H.build_history(snaps), "source": hist["source"]}
    now = datetime.fromisoformat(hist["last_snapshot"] + "T18:00:00+00:00")
    _assert_history_shape(hist, now)
    # Read-only: the committed file is not rewritten.
    assert path.read_text() == raw


def test_one_extra_snapshot_keeps_valid_window_reasons():
    """What scout-import does: one new snapshot day. Reasons must still follow design precedence."""
    import copy
    hist = copy.deepcopy(json.loads((ROOT / "api" / "v1" / "gpu-prices" / "history.json").read_text()))
    nxt = (date.fromisoformat(hist["last_snapshot"]) + timedelta(days=1)).isoformat()
    hist["snapshot_ids"] = list(hist["snapshot_ids"]) + [f"{nxt}.deadbeef"]
    hist["last_snapshot"] = nxt
    hist["snapshot_count"] = len(hist["snapshot_ids"])
    now = datetime.fromisoformat(nxt + "T18:00:00+00:00")
    _assert_history_shape(hist, now)


def test_get_price_trend_tool_contract(monkeypatch):
    from core import contract
    from mcp_server import server
    fresh = (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = _live(1.8, hours_old=2)
    row.update({"verified_at": fresh, "checked_at": fresh, "source_url": "https://acme.example/p"})
    rid = rate_id({**row, "vendor": "Acme"})
    s = _series([_pt("2026-11-17", 2.0), _pt("2026-11-23", 1.8)], rid=rid)
    hist, feed = _hist(s), {"rates": [row], "held_stale": []}
    monkeypatch.setattr(server.history_loader, "load", lambda: hist)
    monkeypatch.setattr(server.gpu_loader, "load", lambda: feed)
    # get_price_trend -> price_trend uses wall clock when now is omitted.
    # The fixture row is verified at NOW-2h (2026-11-23T16:00Z); 48h later
    # live_trend_block returns stale and windows is empty (lium-collect /
    # scout-import 2026-11-25T18:51Z). Pin the same frozen clock as the unit tests.
    orig_trend = H.price_trend
    def _pinned_trend(*args, **kwargs):
        kwargs.setdefault("now", NOW)
        return orig_trend(*args, **kwargs)
    monkeypatch.setattr(H, "price_trend", _pinned_trend)
    out = server.get_price_trend(rid)
    contract.finalize("get_price_trend", out, "brief")
    wrapped = contract.finalize("get_price_trend", out, "full")
    import jsonschema
    jsonschema.validate(json.loads(json.dumps(wrapped)), contract.output_schema("get_price_trend"))
    assert wrapped["ok"] is True and wrapped["windows"][0]["direction"] == "down"
    assert server.get_price_trend("nope")["ok"] is False and server.get_price_trend("nope")["error"]["code"] == "invalid_argument"
    assert server.get_price_trend("r_000000000000")["ok"] is False and server.get_price_trend("r_000000000000")["error"]["code"] == "not_found"
    assert server.get_price_trend(rid, windows=[0])["ok"] is False
