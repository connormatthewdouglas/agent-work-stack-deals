"""SDPE-20: confirmed in-stock H100/A100 rows must carry vendor-confirmed regions.

Fixture tests and the stale-set parity check are deterministic: they use
committed fixtures at a pinned clock. They do not read origin/main, the live
feed, or the wall clock.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.gpu_availability import (  # noqa: E402
    _scout,
    publish_availability,
)

FIX = json.loads((ROOT / "tests/fixtures/sdpe20_confirmed_regions.json").read_text())
PARITY = json.loads((ROOT / "tests/fixtures/sdpe20_stale_set_parity.json").read_text())
T0 = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)


def _now(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _pub(row: dict, now: datetime) -> dict:
    return publish_availability(_scout(row["vendor"], row), row["vendor"], row["tier"], now, annotate=True)


def _stale_view(av: dict | None) -> tuple:
    if not isinstance(av, dict):
        return None
    return (
        av.get("in_stock"),
        av.get("status"),
        av.get("availability_stale"),
        av.get("availability_expires_at"),
        av.get("checked_at"),
        tuple(av.get("available_regions") or ()),
    )


def _row_key(r: dict):
    return (r.get("vendor") or r.get("advertiser"), r.get("gpu"), r.get("vram_gb"), r.get("tier"))


def test_fixture_confirmed_h100_a100_regions_publish_before_expiry():
    """A vendor-confirmed in-stock claim with regions stays in-stock and keeps those regions before expiry."""
    now = T0 + timedelta(minutes=30)
    for row in FIX["rows"]:
        out = _pub(row, now)
        assert out.get("in_stock") is True, (row["vendor"], row["gpu"], out)
        assert out.get("available_regions") == row["available_regions"]
        assert all(d.get("confirmed") is True for d in row["available_regions_detail"])
        assert out.get("checked_at") == row["availability_checked_at"]


def test_fixture_unconfirmed_or_missing_read_is_not_in_stock():
    """in_stock is only confirmed when the vendor's own read says so. Unknown stays unknown."""
    out = _pub({"vendor": "Hyperstack", "tier": "On-demand", "in_stock": None}, T0)
    assert out.get("in_stock") is not True
    assert not out.get("available_regions")
    # A failed probe with no successful check must not invent a stock-read timestamp.
    failed = {"vendor": "Hyperstack", "tier": "On-demand", "in_stock": None,
              "probe_attempted_at": "2026-11-28T12:00:00Z", "availability_checked_at": None}
    out = _pub(failed, T0)
    assert out.get("in_stock") is not True
    assert not out.get("checked_at")


def test_fixture_regions_blank_after_region_expiry_without_inventing_a_fresh_stamp():
    """After the 1 h region expiry a derived claim is no longer in-stock; no fresh timestamp is invented."""
    row = FIX["rows"][0]
    checked = row["availability_checked_at"]
    after = _now(row["available_regions_detail"][0]["availability_expires_at"]) + timedelta(seconds=1)
    out = _pub(row, after)
    assert out.get("in_stock") is not True
    assert not out.get("available_regions")
    assert out.get("checked_at") == checked


def test_stale_set_only_refreshed_rows_differ():
    """At a pinned clock, only refreshed rows may change stale/region view versus the before fixture.

    A row is refreshed when after.checked_at is newer than before.checked_at (or the row is new).
    Unchanged rows must publish the same stale view. The after set must include a confirmed
    in-stock H100/A100 row with vendor regions.
    """
    clock = _now(PARITY["clock"])
    before_rows = PARITY["before"]["rows"]
    after_rows = PARITY["after"]["rows"]
    assert before_rows and after_rows and PARITY.get("refreshed_keys"), "parity fixture incomplete"
    before_by = {_row_key(r): r for r in before_rows}
    expected_refreshed = {tuple(k) for k in PARITY["refreshed_keys"]}
    drifted = []
    refreshed = []
    confirmed = []
    for r in after_rows:
        key = _row_key(r)
        after_view = _stale_view(_pub(r, clock))
        prev = before_by.get(key)
        if prev is None or (r.get("availability_checked_at") or "") > (prev.get("availability_checked_at") or ""):
            refreshed.append(key)
        else:
            before_view = _stale_view(_pub(prev, clock))
            if after_view != before_view:
                drifted.append((key, before_view, after_view))
        if (("H100" in (r.get("gpu") or "").upper() or "A100" in (r.get("gpu") or "").upper())
                and after_view and after_view[0] is True and after_view[5]):
            confirmed.append((key, after_view[5], after_view[4]))
    assert not drifted, f"stale/region view changed on rows that were not refreshed: {drifted}"
    assert set(refreshed) == expected_refreshed, (refreshed, expected_refreshed)
    assert confirmed, "after fixture must have a confirmed in-stock H100/A100 row with vendor regions"
    # The refreshed Hyperstack row actually changed view (not a no-op refresh).
    hs_before = _stale_view(_pub(before_by[("Hyperstack", "H100 PCIe", 80, "On-demand")], clock))
    hs_after = _stale_view(_pub(next(r for r in after_rows if _row_key(r) == ("Hyperstack", "H100 PCIe", 80, "On-demand")), clock))
    assert hs_before != hs_after
    assert hs_after[0] is True and hs_after[5] == ("CANADA-1",)
    assert hs_before[0] is not True and not hs_before[5]
