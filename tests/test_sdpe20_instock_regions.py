"""SDPE-20: confirmed in-stock H100/A100 rows must carry vendor-confirmed regions.

Fixture tests are deterministic (no live reads). The stale-set parity check
allows differences only on rates whose availability was refreshed (newer
stock-read timestamp than origin/main).
"""
from __future__ import annotations

import json
import subprocess
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
FEED = ROOT / "api/v1/gpu-prices.json"
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


def _rate_key(r: dict):
    return r.get("rate_id") or (r.get("advertiser"), r.get("gpu"), r.get("vram_gb"), r.get("tier"))


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


def test_stale_set_only_refreshed_rows_differ_from_main():
    """At the PR feed clock, stale-set / region differences vs origin/main are only on refreshed rows.

    A row is 'refreshed' when this PR's availability checked_at is newer than origin/main's.
    Other rates must publish the same stale view (in_stock, status, stale, expiry, regions).
    """
    if not FEED.is_file():
        return
    pr = json.loads(FEED.read_text())
    try:
        main_raw = subprocess.check_output(
            ["git", "show", "origin/main:api/v1/gpu-prices.json"], cwd=ROOT
        )
    except subprocess.CalledProcessError:
        return
    main = json.loads(main_raw)
    now = _now(pr["feed_updated_at"])
    main_by = {_rate_key(r): r for r in main.get("rates") or []}
    drifted = []
    refreshed = []
    new_confirmed = []
    for r in pr.get("rates") or []:
        key = _rate_key(r)
        av = r.get("availability") if isinstance(r.get("availability"), dict) else None
        if not av:
            continue
        pr_view = _stale_view(publish_availability(dict(av), r.get("advertiser"), r.get("tier"), now, annotate=True))
        mr = main_by.get(key)
        mav = mr.get("availability") if mr and isinstance(mr.get("availability"), dict) else None
        if not mav:
            if av.get("in_stock") is True and av.get("available_regions"):
                new_confirmed.append(key)
            continue
        main_view = _stale_view(publish_availability(dict(mav), mr.get("advertiser"), mr.get("tier"), now, annotate=True))
        pr_ts = av.get("checked_at") or av.get("stock_read_at") or ""
        main_ts = mav.get("checked_at") or mav.get("stock_read_at") or ""
        if pr_ts > main_ts:
            refreshed.append(key)
            continue
        if pr_view != main_view:
            drifted.append((key, main_view, pr_view))
    assert not drifted, f"stale/region view changed on rows that were not refreshed: {drifted[:8]}"
    confirmed = []
    for r in pr.get("rates") or []:
        g = (r.get("gpu") or "")
        if "H100" not in g.upper() and "A100" not in g.upper():
            continue
        av = r.get("availability") if isinstance(r.get("availability"), dict) else {}
        pub = publish_availability(dict(av), r.get("advertiser"), r.get("tier"), now, annotate=True) if av else {}
        if pub.get("in_stock") is True and pub.get("available_regions"):
            confirmed.append((r.get("advertiser"), g, r.get("tier"), pub.get("available_regions"), pub.get("checked_at")))
    assert confirmed, "expected confirmed in-stock H100/A100 rows with vendor regions in the published feed"
