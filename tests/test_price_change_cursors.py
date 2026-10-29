"""T38: lossless price-change pagination (cursors), stable ids, watcher resume + dedupe, rename-stable rate_id."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import DealError  # noqa: E402
from core import gpu_history as H  # noqa: E402
from core.deals import price_changes  # noqa: E402
from core.ids import decode_cursor, encode_cursor, rate_id  # noqa: E402


def snap(day, prices, tier="On-demand"):
    return {"date": day, "rows": [
        {"key": H.series_key(f"V{i:03d}", "H100", tier, 80, 1), "vendor": f"V{i:03d}", "gpu": "H100", "tier": tier,
         "vram_gb": 80, "gpu_count": 1, "billing_unit": "hourly", "price_usd": p, "hourly_usd": p, "status": "ranked",
         "verified_at": f"{day}T10:00:00+00:00", "source_url": "https://example.com/p"} for i, p in enumerate(prices)]}


def hist201():
    # 201 vendors all move on the same day -> 201 same-day events
    return H.build_history([snap("2026-11-01", [2.0] * 201), snap("2026-11-02", [1.9] * 201)])


def drain(history, cursor, limit=200, **kw):
    seen, pages = [], 0
    while True:
        r = price_changes(None, history, cursor=cursor, limit=limit, **kw)
        assert "error" not in r
        seen += [c["event_id"] for c in r["changes"]]
        cursor, pages = r["next_cursor"], pages + 1
        if not r["has_more"]:
            return seen, cursor, pages


def test_history_ids_deterministic_and_seq_ordered():
    a, b = hist201(), hist201()
    assert a == b and a["last_seq"] == 201
    seqs = [c["seq"] for c in a["changes"]]
    assert sorted(seqs) == list(range(1, 202)) and len({c["event_id"] for c in a["changes"]}) == 201
    assert all(c["event_id"].startswith("2026-11-02:r_") and c["event_id"].endswith(":down") for c in a["changes"])
    assert a["snapshot_ids"][0].startswith("2026-11-01.")


def test_201_events_fully_paginated():
    h = hist201()
    first = price_changes(None, h, since="2026-11-01", limit=200)
    assert first["total"] == 201 and first["count"] == 200 and first["has_more"] is True
    ids, _, pages = drain(h, first["next_cursor"])
    assert len(ids) == 201 == len(set(ids)) and pages == 2
    assert set(ids) == {c["event_id"] for c in h["changes"]}


def test_restart_resume_and_missed_polls():
    h1 = hist201()
    cur = price_changes(None, h1, since="2026-11-01")["next_cursor"]
    got, cur, _ = drain(h1, cur, limit=50)
    saved = json.dumps({"cursor": cur})  # watcher persists, process restarts, two daily runs are missed
    h3 = H.build_history([snap("2026-11-01", [2.0] * 201), snap("2026-11-02", [1.9] * 201),
                          snap("2026-11-03", [1.8] * 201), snap("2026-11-04", [1.7] * 201)])
    assert {c["event_id"]: c["seq"] for c in h3["changes"] if c["seq"] <= 201} == {c["event_id"]: c["seq"] for c in h1["changes"]}
    more, _, _ = drain(h3, json.loads(saved)["cursor"], limit=70)
    assert len(more) == 402 and not set(more) & set(got)
    assert set(got) | set(more) == {c["event_id"] for c in h3["changes"]}


def test_duplicate_poll_emits_nothing_new():
    h = hist201()
    _, cur, _ = drain(h, encode_cursor(0, None))
    again = price_changes(None, h, cursor=cur)
    assert again["changes"] == [] and again["has_more"] is False and again["next_cursor"] == cur
    # overlapping since-window re-read + local dedupe on event_id yields no duplicate alerts
    seen = {c["event_id"] for c in h["changes"]}
    overlap = price_changes(None, h, since="2026-11-02", limit=200)["changes"]
    assert [c for c in overlap if c["event_id"] not in seen] == []


def test_cursor_expired_and_invalid():
    h = hist201()
    bogus = encode_cursor(5, "2026-11-02:r_000000000000:down")
    with pytest.raises(DealError) as e:
        price_changes(None, h, cursor=bogus)
    assert e.value.code == "cursor_expired" and "since='2026-11-02'" in str(e.value)
    with pytest.raises(DealError) as e:
        price_changes(None, h, cursor=encode_cursor(999, "x"))
    assert e.value.code == "cursor_expired"
    with pytest.raises(DealError) as e:
        price_changes(None, h, cursor="not-a-cursor")
    assert e.value.code == "invalid_cursor"
    with pytest.raises(DealError):
        price_changes(None, h, cursor=encode_cursor(0, None), since="2026-11-01")
    assert decode_cursor(encode_cursor(3, "e")) == {"seq": 3, "eid": "e"}


def test_kinds_and_gpu_filters_still_advance_cursor():
    h = H.build_history([snap("2026-11-01", [2.0, 2.0, 2.0]), snap("2026-11-02", [1.0, 3.0, 1.5])])
    r = price_changes(None, h, cursor=encode_cursor(0, None), kinds=["up"])
    assert [c["direction"] for c in r["changes"]] == ["up"] and r["has_more"] is False
    assert decode_cursor(r["next_cursor"])["seq"] == 3
    assert price_changes(None, h, since="2026-11-01", kinds=["down"])["total"] == 2
    with pytest.raises(DealError):
        price_changes(None, h, since="2026-11-01", kinds=["sideways"])


def test_tier_rename_keeps_rate_id_and_config_change_does_not():
    base = {"vendor": "RunPod", "gpu": "H100 PCIe", "vram_gb": 80, "gpu_count": 1, "billing_unit": "hourly"}
    assert rate_id({**base, "tier": "Secure Cloud"}) == rate_id({**base, "tier": "On-demand (Secure Cloud)"})
    assert rate_id({**base, "tier": "On-demand"}) == rate_id({**base, "tier": " on-demand ", "vendor": " runpod ", "vram_gb": "80"})
    assert rate_id({**base, "tier": "On-demand"}) != rate_id({**base, "tier": "Spot"})
    assert rate_id({**base, "tier": "On-demand"}) != rate_id({**base, "tier": "On-demand", "vram_gb": 94})
    assert rate_id({**base, "tier": "On-demand"}) != rate_id({**base, "tier": "On-demand", "gpu_count": 8})
    r1 = {**base, "tier": '1 Month (reserved, "1 mo")'}
    assert rate_id(r1) != rate_id({**base, "tier": '3 Month (reserved, "3 mo")'})
    assert rate_id(r1) == rate_id({**base, "tier": "Reserved, 1 month"})
    h = H.build_history([snap("2026-11-01", [2.0], tier="Secure Cloud"), snap("2026-11-02", [1.0], tier="On-demand (Secure Cloud)")])
    assert len({s["rate_id"] for s in h["series"]}) == 1


def test_published_history_migrated():
    h = json.loads((ROOT / "api" / "v1" / "gpu-prices" / "history.json").read_text())
    assert h["schema"].endswith("/2") and h["last_seq"] == len(h["changes"])
    assert all(c.get("event_id") and c.get("rate_id") and isinstance(c.get("seq"), int) and c.get("snapshot_id") for c in h["changes"])
    assert len({s["rate_id"] for s in h["series"]}) == len(h["series"])
    r = price_changes(None, h, since=h["first_snapshot"])
    assert all(c["key"] and c["event_id"] for c in r["changes"])


def test_mcp_tool_cursor_and_latest_ids(monkeypatch):
    from mcp_server import server
    h = hist201()
    monkeypatch.setattr(server.history_loader, "load", lambda *a, **k: h)
    r = server.get_price_changes(since="2026-11-01", limit=200)
    ids, _, _ = [], None, None
    cur = r["next_cursor"]
    while True:
        p = server.get_price_changes(cursor=cur, limit=200, kinds=["down"])
        assert p["ok"] is True
        ids += [c["event_id"] for c in p["changes"]]
        cur = p["next_cursor"]
        if not p["has_more"]:
            break
    assert len(set(ids)) == 201
    bad = server.get_price_changes(cursor="junk")
    assert bad["ok"] is False and bad["error"]["code"] == "invalid_cursor"
    exp = server.get_price_changes(cursor=encode_cursor(5, "2026-11-02:r_000000000000:down"))
    assert exp["ok"] is False and exp["error"]["code"] == "cursor_expired"
    brief = server.get_price_changes(since="2026-11-01", mode="brief")
    assert brief["ok"] and "next_cursor" in brief and "has_more" in brief and "event_id" in brief["changes"][0]
    latest = json.loads((ROOT / "api" / "v1" / "gpu-price-changes.json").read_text())
    monkeypatch.setattr(server.changes_loader, "load", lambda *a, **k: latest)
    out = server.get_price_changes()
    assert all(c["event_id"].startswith(latest["date"] + ":r_") and c["key"] for c in out["changes"])
