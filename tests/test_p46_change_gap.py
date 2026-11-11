"""P46 (fieldnotes_ai): last_verified_before + gap_days bound when a price change happened. Additive; null when unknown."""
import json
from pathlib import Path

from core import contract, gpu_changes, gpu_history
from core import deals as core

ROOT = Path(__file__).resolve().parents[1]


def _snap(day, price, t, key="V|H100|On-demand|80|1"):
    return {"date": day, "rows": [{"key": key, "vendor": "V", "gpu": "H100", "tier": "On-demand", "vram_gb": 80, "gpu_count": 1,
                                   "billing_unit": "hourly", "price_usd": price, "hourly_usd": price, "status": "ranked",
                                   "verified_at": t, "source_url": "https://v.example/pricing"}]}


def test_change_gap_helper():
    assert gpu_history.change_gap("2026-11-01T12:00:00+00:00", "2026-11-03T00:00:00Z") == {
        "last_verified_before": "2026-11-01T12:00:00+00:00", "gap_days": 1.5}
    assert gpu_history.change_gap(None, "2026-11-03T00:00:00Z") == {"last_verified_before": None, "gap_days": None}
    assert gpu_history.change_gap("2026-11-01T00:00:00Z", None) == {"last_verified_before": "2026-11-01T00:00:00Z", "gap_days": None}
    assert gpu_history.change_gap("garbage", "2026-11-03T00:00:00Z") == {"last_verified_before": None, "gap_days": None}
    assert gpu_history.change_gap("2026-11-04T00:00:00Z", "2026-11-03T00:00:00Z")["gap_days"] is None  # out of order


def test_history_uses_last_observation_at_old_price_even_across_a_gap():
    snaps = [_snap("2026-11-01", 2.0, "2026-11-01T10:00:00Z"), _snap("2026-11-02", 2.0, "2026-11-02T10:00:00Z"),
             {"date": "2026-11-03", "rows": []}, _snap("2026-11-04", 2.5, "2026-11-04T22:00:00Z")]
    h = gpu_history.build_history(snaps)
    assert [(c["last_verified_before"], c["gap_days"]) for c in h["changes"]] == []  # left tracking: no change event (unchanged rule)
    snaps[2] = _snap("2026-11-03", 2.0, "2026-11-03T10:00:00Z")
    (c,) = gpu_history.build_history(snaps)["changes"]
    assert c["last_verified_before"] == "2026-11-03T10:00:00Z" and c["gap_days"] == 1.5
    d = gpu_changes.build_changes(snaps)["changes"][0]
    assert (d["last_verified_before"], d["gap_days"], d["verified_at"]) == ("2026-11-03T10:00:00Z", 1.5, "2026-11-04T22:00:00Z")


def test_new_and_removed_are_null_and_feeds_carry_fields():
    ch = json.loads((ROOT / "api/v1/gpu-price-changes.json").read_text())
    for c in ch["changes"]:
        assert "last_verified_before" in c and "gap_days" in c
        if c["change"] in ("new", "removed"):
            assert c["last_verified_before"] is None and c["gap_days"] is None
        elif c["gap_days"] is not None:
            assert c["last_verified_before"] < c["verified_at"] or c["gap_days"] == 0
    hist = json.loads((ROOT / "api/v1/gpu-prices/history.json").read_text())
    assert hist["changes"] and all("gap_days" in c and "last_verified_before" in c for c in hist["changes"])
    assert any(c["gap_days"] is not None for c in hist["changes"])


def test_mcp_rows_and_schema_lockstep():
    hist = json.loads((ROOT / "api/v1/gpu-prices/history.json").read_text())
    latest = json.loads((ROOT / "api/v1/gpu-price-changes.json").read_text())
    for kw in ({"since": hist["first_snapshot"]}, {}):
        out = core.price_changes(latest, hist, limit=200, **kw)
        assert out["changes"] and all("gap_days" in r and "last_verified_before" in r for r in out["changes"])
        brief = contract.finalize("get_price_changes", out, "brief")
        assert all("gap_days" in r for r in brief["changes"])
    # freshness basis unchanged for history reads (change events still carry no verified_at)
    assert "snapshot" in core.price_changes(latest, hist, since=hist["first_snapshot"])["data_checked_at_basis"]
    s = contract.output_schema("get_price_changes")["properties"]["changes"]["items"]["properties"]
    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    p = next(t for t in plugin["tools"] if t["name"] == "get_price_changes")["outputSchema"]["properties"]["changes"]["items"]["properties"]
    for k in ("last_verified_before", "gap_days"):
        assert p[k] == s[k] and "null" in s[k]["type"]
    view = core.gpu_history_view(hist, "H100", [])
    assert all("gap_days" in c for c in view["recent_changes"])
