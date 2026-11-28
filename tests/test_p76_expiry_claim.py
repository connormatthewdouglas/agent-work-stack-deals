"""P76: label which claim availability_expires_at belongs to; carry an older in-stock claim's own expiry."""
from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import deals, gpu_availability as A
from core.gpu_availability import (
    annotate_last_known_window,
    availability_expires_claim,
    publish_availability,
    stale_guard,
)
import gpu_pages as gp  # noqa: E402

# marxsignal's example (Brain #1171): last_known_at + 8h = 2026-11-25T20:49:53Z
NOW = datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc)
LAST_KNOWN_AT = "2026-11-25T12:49:53Z"
LAST_KNOWN_EXPIRES = "2026-11-25T20:49:53Z"
NULL_READ_AT = "2026-11-27T02:42:14Z"  # later than last_known; Brain's then-current expiry was this + ? 
# Current feed shape: checked_at later than last_known, expiry = checked_at + 8h
CHECKED_AT = "2026-11-28T03:06:33Z"
CHECKED_EXPIRES = "2026-11-28T11:06:33Z"
FEED = ROOT / "api" / "v1" / "gpu-prices.json"


def _null_beside_older_instock(**extra) -> dict:
    av = {
        "in_stock": None,
        "status": "unknown",
        "checked_at": CHECKED_AT,
        "last_known_in_stock": True,
        "last_known_at": LAST_KNOWN_AT,
        "availability_expires_at": CHECKED_EXPIRES,
        "max_age_hours": 8.0,
        "max_age_source": "policy",
        "availability_reason": "api_null_signal",
        "origin": "scout",
    }
    av.update(extra)
    return av


def test_live_expiry_is_labelled_as_the_current_read():
    av = _null_beside_older_instock()
    out = annotate_last_known_window(av, NOW)
    assert out["availability_expires_at"] == CHECKED_EXPIRES
    assert out["availability_expires_claim"] == "checked_at"
    assert availability_expires_claim(out) == "checked_at"
    # Live expiry itself is unchanged (no TTL change).
    assert out["availability_expires_at"] == av["availability_expires_at"]
    assert out["in_stock"] is None


def test_older_instock_claim_carries_its_own_expiry():
    out = annotate_last_known_window(_null_beside_older_instock(), NOW)
    assert out["last_known_at"] == LAST_KNOWN_AT
    assert out["last_known_in_stock"] is True
    assert out["last_known_expires_at"] == LAST_KNOWN_EXPIRES
    assert out["last_known_max_age_hours"] == 8.0
    assert out["last_known_expires_at"] != out["availability_expires_at"]
    assert out["last_known_expires_at"] < out["availability_expires_at"]


def test_no_last_known_does_not_invent_an_older_expiry():
    av = {
        "in_stock": None,
        "status": "unknown",
        "checked_at": CHECKED_AT,
        "availability_expires_at": CHECKED_EXPIRES,
        "max_age_hours": 8.0,
        "origin": "scout",
    }
    out = annotate_last_known_window(av, NOW)
    assert "last_known_at" not in out or out.get("last_known_at") in (None, "")
    assert not out.get("last_known_expires_at")
    assert out["availability_expires_claim"] == "checked_at"
    assert out["in_stock"] is None


def test_failed_read_is_not_a_successful_check():
    """A later null/no_source read must not become in_stock or extend the last-known window."""
    av = _null_beside_older_instock(availability_reason="no_source")
    guarded = stale_guard(av, NOW)
    out = publish_availability(av, "RunPod", "On-demand (Secure Cloud)", NOW, annotate=True)
    assert out["in_stock"] is None
    assert out.get("last_known_in_stock") is True
    assert out["last_known_at"] == LAST_KNOWN_AT
    assert out["last_known_expires_at"] == LAST_KNOWN_EXPIRES
    # Last-known window is last_known_at + 8h, not checked_at + 8h.
    assert out["last_known_expires_at"] != out["availability_expires_at"]
    assert guarded["in_stock"] is None or guarded.get("availability_stale") in (True, None)


def test_publish_matches_marxsignal_runpod_example():
    """last_known_at 2026-11-25T12:49:53Z + 8h = 2026-11-25T20:49:53Z, separate from the null-read expiry."""
    # Use the feed's current RunPod H100 PCIe Secure Cloud row if present; else the pinned fixture.
    data = json.loads(FEED.read_text())
    row = next(
        (
            r for r in data["rates"]
            if r.get("advertiser") == "RunPod"
            and "H100 PCIe" in (r.get("gpu") or "")
            and "Secure" in (r.get("tier") or "")
        ),
        None,
    )
    assert row, "expected the RunPod H100 PCIe Secure Cloud row on the feed"
    av = row["availability"]
    out = publish_availability(av, row.get("advertiser"), row.get("tier"), NOW, annotate=True)
    if av.get("last_known_at") == LAST_KNOWN_AT:
        assert out["last_known_expires_at"] == LAST_KNOWN_EXPIRES
    assert out["availability_expires_claim"] == "checked_at"
    assert out["in_stock"] is None
    assert out.get("last_known_in_stock") is True


def test_pages_label_both_expiries():
    class _G:
        @staticmethod
        def esc(s):
            return str(s)

    av = annotate_last_known_window(_null_beside_older_instock(), NOW)
    html = gp._avail_cell(_G, {"advertiser": "RunPod", "availability": av})
    assert "checked_at" in html
    assert "last_known_at" in html
    assert "current-read expiry" in html
    assert "last-known in-stock claim expiry" in html


def test_compare_ranking_unchanged_when_claim_fields_present():
    data = json.loads(FEED.read_text())
    a = deals.compare_gpu_prices(data, "H100", limit=10, now=NOW, on_demand_only=False, include_reserved=True)
    ids = [r["rate_id"] for r in a["results"]]
    b = deals.compare_gpu_prices(data, "H100", limit=10, now=NOW, on_demand_only=False, include_reserved=True)
    assert ids == [r["rate_id"] for r in b["results"]]
    assert a["results"]


def _stale_view(av: dict) -> tuple:
    return (
        bool(av.get("availability_stale")),
        av.get("status"),
        av.get("in_stock"),
        av.get("availability_reason"),
        av.get("max_age_reason"),
        av.get("checked_at"),
        av.get("availability_expires_at"),
    )


def _load_main_gpu_availability():
    src = subprocess.check_output(["git", "show", "origin/main:core/gpu_availability.py"], cwd=ROOT)
    name = "core._p76_main_gpu_availability"
    m = types.ModuleType(name)
    m.__file__ = str(ROOT / "core" / "gpu_availability.py")
    m.__package__ = "core"
    sys.modules[name] = m
    exec(compile(src, "gpu_availability_main.py", "exec"), m.__dict__)
    return m


def test_expiry_claim_matches_main_stale_set_and_reasons():
    """At the committed feed clock, PR publish/stale_guard matches origin/main's stale set and reasons."""
    data = json.loads(FEED.read_text())
    now = datetime.fromisoformat(str(data["feed_updated_at"]).replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    main_ga = _load_main_gpu_availability()

    pr_stale, main_stale = {}, {}
    pr_all, main_all = {}, {}
    for r in data["rates"]:
        av = r.get("availability")
        if not isinstance(av, dict):
            continue
        key = r.get("rate_id") or (r.get("advertiser"), r.get("gpu"), r.get("tier"))
        pr = A.publish_availability(av, r.get("advertiser") or r.get("vendor"), r.get("tier"), now, annotate=True)
        mn = main_ga.publish_availability(av, r.get("advertiser") or r.get("vendor"), r.get("tier"), now, annotate=True)
        pr_all[key] = _stale_view(pr)
        main_all[key] = _stale_view(mn)
        if pr.get("availability_stale"):
            pr_stale[key] = pr_all[key]
        if mn.get("availability_stale"):
            main_stale[key] = main_all[key]
        # Additive fields must not alter the published claim used by stale_guard.
        assert _stale_view(pr) == _stale_view(mn), key

    assert pr_stale == main_stale
    assert pr_all == main_all
