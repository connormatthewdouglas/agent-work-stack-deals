"""P74: stock age at read time, never-read vs read-expired, stale-set parity with main."""
from __future__ import annotations

import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import deals, gpu_availability as A
from core.stock_age import (
    NEVER_READ,
    READ,
    READ_EXPIRED,
    attach_stock_age,
    stock_age_fields,
    stock_age_phrase,
    stock_timestamp,
)
import gpu_pages as gp  # noqa: E402

NOW = datetime(2026, 11, 28, 6, 0, 0, tzinfo=timezone.utc)
FEED = ROOT / "api" / "v1" / "gpu-prices.json"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_never_read_has_null_age_and_invents_no_timestamp():
    fields = stock_age_fields({"in_stock": None, "status": "unknown"}, NOW)
    assert fields["stock_age_hours"] is None
    assert fields["stock_age_basis"] is None
    assert fields["stock_read_state"] == NEVER_READ
    assert stock_timestamp({}) == (None, None)
    assert stock_age_phrase({"in_stock": None}, NOW) == ""


def test_read_age_uses_stock_read_at_not_price_row_time():
    stock_at = _iso(NOW - timedelta(hours=2))
    av = {
        "in_stock": True,
        "status": "available when checked",
        "stock_read_at": stock_at,
        "checked_at": _iso(NOW - timedelta(hours=5)),
        "availability_expires_at": _iso(NOW + timedelta(hours=6)),
    }
    # A price timestamp on a wrapping row must not be used.
    row = {
        "verified_at": _iso(NOW - timedelta(minutes=10)),
        "checked_at": _iso(NOW - timedelta(minutes=10)),
        "availability": av,
        "probe_attempted_at": _iso(NOW - timedelta(minutes=1)),
    }
    fields = stock_age_fields(av, NOW)
    assert fields["stock_age_hours"] == 2.0
    assert fields["stock_age_basis"] == "stock_read_at"
    assert fields["stock_read_state"] == READ
    attached = attach_stock_age(row, NOW)
    assert attached["stock_age_hours"] == 2.0
    # Availability is passed through unchanged (E5 contract).
    assert attached["availability"] is row["availability"]
    assert "stock_age_hours" not in av


def test_falls_back_to_stock_checked_at_and_ignores_probe_attempted_at():
    av = {
        "in_stock": False,
        "status": "out of stock when checked",
        "checked_at": _iso(NOW - timedelta(hours=3)),
        "probe_attempted_at": _iso(NOW - timedelta(minutes=5)),
        "availability_expires_at": _iso(NOW + timedelta(hours=5)),
    }
    fields = stock_age_fields(av, NOW)
    assert fields["stock_age_hours"] == 3.0
    assert fields["stock_age_basis"] == "checked_at"
    assert fields["stock_read_state"] == READ


def test_read_expired_is_distinct_from_never_read():
    av = {
        "in_stock": None,
        "status": "unknown (stale availability, last checked 1:00 AM ET)",
        "availability_stale": True,
        "checked_at": _iso(NOW - timedelta(hours=10)),
        "stock_read_at": _iso(NOW - timedelta(hours=10)),
    }
    fields = stock_age_fields(av, NOW)
    assert fields["stock_age_hours"] == 10.0
    assert fields["stock_read_state"] == READ_EXPIRED
    # Expiry by availability_expires_at, even if stale flag not yet set.
    living = {
        "in_stock": True,
        "checked_at": _iso(NOW - timedelta(hours=2)),
        "availability_expires_at": _iso(NOW - timedelta(minutes=1)),
    }
    assert stock_age_fields(living, NOW)["stock_read_state"] == READ_EXPIRED
    # Equal to expiry is still valid (P70/P71): not expired.
    at_edge = {
        "in_stock": True,
        "checked_at": _iso(NOW - timedelta(hours=1)),
        "availability_expires_at": _iso(NOW),
    }
    assert stock_age_fields(at_edge, NOW)["stock_read_state"] == READ


def test_expired_claim_age_uses_last_known_at_not_a_later_checked_at():
    """A stale row may carry a later checked_at (scout touch) than the firm claim."""
    av = {
        "in_stock": None,
        "status": "unknown (stale availability, last checked 2026-11-25 07:49 ET)",
        "availability_stale": True,
        "checked_at": _iso(NOW - timedelta(hours=2, minutes=44)),
        "last_known_at": _iso(NOW - timedelta(days=2, hours=17, minutes=11)),
        "last_known_in_stock": True,
        "availability_expires_at": _iso(NOW + timedelta(hours=5)),
    }
    fields = stock_age_fields(av, NOW)
    assert fields["stock_age_basis"] == "last_known_at"
    assert fields["stock_read_state"] == READ_EXPIRED
    # Must not look like a 2.7h-old current claim.
    assert fields["stock_age_hours"] == 65.2


def test_unknown_after_successful_read_is_not_never_read():
    av = {
        "in_stock": None,
        "status": "unknown",
        "checked_at": _iso(NOW - timedelta(hours=1)),
        "availability_reason": "api_null_signal",
    }
    fields = stock_age_fields(av, NOW)
    assert fields["stock_read_state"] == READ
    assert fields["stock_age_hours"] == 1.0


def test_compare_gpu_prices_adds_stock_age_and_does_not_change_ranking():
    data = json.loads(FEED.read_text())
    a = deals.compare_gpu_prices(data, "H100", limit=10, now=NOW, on_demand_only=False, include_reserved=True)
    b = deals.compare_gpu_prices(data, "H100", limit=10, now=NOW, on_demand_only=False, include_reserved=True)
    ids_a = [r["rate_id"] for r in a["results"]]
    ids_b = [r["rate_id"] for r in b["results"]]
    assert ids_a == ids_b
    assert a["results"], "expected H100 results on the live feed"
    for r in a["results"]:
        assert r["stock_read_state"] in {NEVER_READ, READ, READ_EXPIRED}
        if r["stock_read_state"] == NEVER_READ:
            assert r["stock_age_hours"] is None
            assert r["stock_age_basis"] is None
        else:
            assert isinstance(r["stock_age_hours"], float)
            assert r["stock_age_basis"] in {"stock_read_at", "checked_at", "last_known_at"}
            av = r["availability"]
            # Price data_age_hours stays the price clock, and may differ from stock age.
            assert "data_age_hours" in r
            if r.get("verified_at") or r.get("checked_at"):
                if (av or {}).get("stock_read_at") or (av or {}).get("checked_at"):
                    # stock basis is a stock stamp, never the price-only stamp when stock exists
                    assert r["stock_age_basis"] in {"stock_read_at", "checked_at", "last_known_at"}


def test_find_available_gpus_ranks_the_same_with_stock_age_present():
    data = json.loads(FEED.read_text())
    out = deals.find_available_gpus(data, "H100", gpus=1, limit=10, on_demand_only=True, now=NOW)
    ids = [r["rate_id"] for r in out["available"]]
    # Recompute expected order from the same freshness key (checked_at, price), ignoring stock_age.
    def fresh_key(item):
        ts = deals._parse_dt(item.get("checked_at")) if item.get("checked_at") else None
        stamp = ts.timestamp() if ts else float("-inf")
        price = item["hourly_usd"] if isinstance(item.get("hourly_usd"), (int, float)) else float("inf")
        return (-stamp, price, item.get("advertiser") or "", item.get("gpu") or "")
    assert ids == [r["rate_id"] for r in sorted(out["available"], key=fresh_key)]
    for bucket in ("available", "sold_out", "unknown"):
        for r in out[bucket]:
            assert r["stock_read_state"] in {NEVER_READ, READ, READ_EXPIRED}


def test_pages_label_never_read_distinctly_from_expired():
    class _G:
        @staticmethod
        def esc(s):
            return str(s)

    never = {"advertiser": "ExampleCo", "availability": {"in_stock": None, "status": "unknown"}}
    expired = {
        "advertiser": "ExampleCo",
        "availability": {
            "in_stock": None,
            "status": "unknown (stale availability, last checked 1:00 AM ET)",
            "availability_stale": True,
            "checked_at": _iso(NOW - timedelta(hours=10)),
            "origin": "scout",
        },
    }
    # Pin the page clock via LW_AVAIL_NOW through stock_age._clock.
    import os
    os.environ["LW_AVAIL_NOW"] = _iso(NOW)
    try:
        never_html = gp._avail_cell(_G, never)
        exp_html = gp._avail_cell(_G, expired)
    finally:
        os.environ.pop("LW_AVAIL_NOW", None)
    assert "never read" in never_html
    assert "stale availability" in exp_html
    assert "never read" not in exp_html
    assert "stock read" in exp_html
    assert "ago" not in exp_html
    assert "stock read 2026-11-27 20:00 UTC" in exp_html  # NOW-10h at pinned clock
    # (a) a no-signal check is not called a stock read.
    nosig = {
        "advertiser": "ExampleCo",
        "availability": {
            "in_stock": None,
            "status": "unknown",
            "checked_at": _iso(NOW - timedelta(hours=2)),
        },
    }
    nosig_html = gp._avail_cell(_G, nosig)
    assert "unknown (no signal), checked " in nosig_html
    assert "stock read" not in nosig_html
    assert "ago" not in nosig_html
    # Explainer no longer lumps em-dash / unknown as "no signal".
    assert "never read" in A.STOCK_EXPLAINER
    assert "expired" in A.STOCK_EXPLAINER
    assert "means no signal, not sold out" not in A.STOCK_EXPLAINER
    assert A.NOTE == A.STOCK_EXPLAINER and A.NOTE.startswith("Where a status is shown")


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
    """Load origin/main's gpu_availability.py as a sibling core module (relative imports resolve to this tree)."""
    import subprocess
    src = subprocess.check_output(
        ["git", "show", "origin/main:core/gpu_availability.py"],
        cwd=ROOT,
    )
    name = "core._p74_main_gpu_availability"
    m = types.ModuleType(name)
    m.__file__ = str(ROOT / "core" / "gpu_availability.py")
    m.__package__ = "core"
    sys.modules[name] = m
    exec(compile(src, "gpu_availability_main.py", "exec"), m.__dict__)
    return m


def test_stock_age_matches_main_stale_set_and_reasons():
    """At a pinned clock, PR publish/stale_guard matches origin/main's stale set and reasons.

    Stock-age fields are a later additive pass and must not change enforcement.
    """
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
        # Additive age must not alter the published claim.
        aged = attach_stock_age({"availability": pr}, now)["availability"]
        assert _stale_view(aged) == _stale_view(pr), key

    assert pr_stale == main_stale
    assert pr_all == main_all


def test_static_pages_contain_no_relative_stock_ago():
    """B1: static HTML must not bake relative 'stock read Nh ago' (false freshness if collection stalls)."""
    import re
    ago = re.compile(r"stock read\s[^<]*\bago\b", re.I)
    roots = [ROOT / "gpu", ROOT / "lanternworks", ROOT / "tools"]
    hits = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            m = ago.search(text)
            if m:
                hits.append(f"{path.relative_to(ROOT)}: {m.group(0)!r}")
    assert not hits, "relative stock-age phrasing on static pages:\n" + "\n".join(hits[:20])
