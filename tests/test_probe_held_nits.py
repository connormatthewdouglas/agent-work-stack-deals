"""#372 probe string-error, #370 held-tier match, #370 SXM suffix marker, stale-set parity.

Pinned clocks and fixtures only. No skip/xfail. No live network.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import gpu_availability as A
from core.gpu_availability import apply_probe, publish_availability, stale_guard
import check_gpu_freshness as gate
import refresh_gpu_prices as R

NOW = datetime(2026, 11, 28, 6, 0, tzinfo=timezone.utc)
FEED = ROOT / "api" / "v1" / "gpu-prices.json"


def test_apply_probe_keeps_a_string_error_and_only_pops_exceptions():
    previous = {
        "in_stock": True,
        "status": "in stock",
        "checked_at": "2026-11-28T03:00:00Z",
        "origin": "scout",
    }
    cur = {
        "in_stock": None,
        "status": "unknown",
        "checked_at": "2026-11-28T05:00:00Z",
        "origin": "scout",
        "error": "api returned error: timeout",
        "availability_reason": "no_source",
    }
    out = apply_probe(previous, cur, now=NOW)
    assert out.get("error") == "api returned error: timeout"
    assert "probe_error" not in out
    assert out.get("checked_at") == "2026-11-28T05:00:00Z"
    # A real exception still converts and is not left as a raw error object.
    crashed = apply_probe(previous, {"error": RuntimeError("boom"), "origin": "scout"}, now=NOW)
    assert "probe_error" in crashed
    assert not isinstance(crashed.get("error"), BaseException)
    # A crash is not a successful check: last firm claim and checked_at stay put.
    assert crashed.get("in_stock") is True
    assert crashed.get("checked_at") == previous["checked_at"]
    assert crashed.get("probe_attempted_at") == "2026-11-28T06:00:00Z"


def test_published_held_no_tier_matches_only_no_tier_rows():
    """A held record with no tier must not match every tier of that GPU (#370 nit 1)."""
    d = {"vendor": "ExampleCloud"}
    tiered = {"gpu": "H100", "tier": "On-demand", "vram_gb": 80, "checked_at": (NOW - timedelta(hours=80)).isoformat()}
    no_tier = {"gpu": "H100", "tier": None, "vram_gb": 80, "checked_at": (NOW - timedelta(hours=80)).isoformat()}
    spot = {"gpu": "H100", "tier": "Spot", "vram_gb": 80, "checked_at": (NOW - timedelta(hours=80)).isoformat()}
    held_no_tier = [{"vendor": "ExampleCloud", "records": [{"gpu": "H100", "vram_gb": 80}]}]
    held_ondemand = [{"vendor": "ExampleCloud", "records": [{"gpu": "H100", "tier": "On-demand", "vram_gb": 80}]}]

    assert gate._published_held(d, no_tier, held_no_tier) is True
    assert gate._published_held(d, tiered, held_no_tier) is False
    assert gate._published_held(d, spot, held_no_tier) is False
    assert gate._published_held(d, tiered, held_ondemand) is True
    assert gate._published_held(d, spot, held_ondemand) is False
    assert gate._published_held(d, no_tier, held_ondemand) is False


def test_no_tier_held_record_does_not_loosen_the_72h_ceiling():
    """An unheld On-demand row 80h old still fails the ceiling even if a no-tier hold exists for that GPU."""
    stamp = (NOW - timedelta(hours=80)).replace(microsecond=0).isoformat()
    fresh = (NOW - timedelta(hours=1)).isoformat()
    row = {"checked_at": stamp, "gpu": "H100", "tier": "On-demand", "vendor": "ExampleCloud"}
    docs = [
        {"vendor": "Ok", "records": [{"checked_at": fresh, "gpu": "H100", "tier": "On-demand"}]},
        {"vendor": "ExampleCloud", "records": [row]},
    ]
    held = [{"vendor": "ExampleCloud", "records": [{"gpu": "H100"}]}]  # no tier
    code, msgs = gate.status(NOW, 26, docs=docs, held_stale=held)
    assert code == 1, msgs
    assert any("hard ceiling" in m and "ExampleCloud|H100|On-demand" in m for m in msgs)
    # A no-tier held row of the same age is excluded from the gate (matched only to no-tier).
    no_tier_row = {"checked_at": stamp, "gpu": "H100", "vendor": "ExampleCloud"}
    docs_nt = [
        {"vendor": "Ok", "records": [{"checked_at": fresh, "gpu": "H100", "tier": "On-demand"}]},
        {"vendor": "ExampleCloud", "records": [no_tier_row]},
    ]
    code_nt, msgs_nt = gate.status(NOW, 26, docs=docs_nt, held_stale=held)
    assert code_nt == 0, msgs_nt
    assert "hard ceiling" not in "\n".join(msgs_nt)


def test_h100_sxm_marker_allows_known_sxm_suffix_only():
    r = {"gpu": "H100 SXM"}
    assert R.listed_page_marker_visible(r, "NVIDIA H100 SXM5 80GB on demand")
    assert R.listed_page_marker_visible(r, "NVIDIA H100 SXM 80GB on demand")
    assert R.listed_page_marker_visible(r, "NVIDIA H100 SXM4 80GB")
    assert not R.listed_page_marker_visible(r, "NVIDIA H100 SXM7 80GB")
    assert not R.listed_page_marker_visible(r, "NVIDIA H100 SXMfoo")
    assert not R.listed_page_marker_visible(r, "Just a moment... Checking your browser")
    # A row already named SXM5 still matches its exact marker.
    assert R.listed_page_marker_visible({"gpu": "H100 SXM5"}, "H100 SXM5 80GB")
    # No $ + SXM5 variant on an H100 SXM row is a hold, same as an exact marker.
    page = "Explore NVIDIA H100 SXM5 80GB Features. Start Building Now."
    assert R.should_hold_unreadable_listed(r, page, "unreadable")
    assert not R.should_hold_unreadable_listed(r, "Just a moment... Cloudflare", "unreadable")


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
    name = "core._nits_main_gpu_availability"
    m = types.ModuleType(name)
    m.__file__ = str(ROOT / "core" / "gpu_availability.py")
    m.__package__ = "core"
    sys.modules[name] = m
    exec(compile(src, "gpu_availability_main.py", "exec"), m.__dict__)
    return m


def test_stale_set_matches_main_at_pinned_feed_clock():
    """This PR must not change the stale set or stale reasons vs origin/main."""
    data = json.loads(FEED.read_text())
    now = datetime.fromisoformat(str(data["feed_updated_at"]).replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    main_ga = _load_main_gpu_availability()
    pr_all, main_all = {}, {}
    for r in data["rates"]:
        av = r.get("availability")
        if not isinstance(av, dict):
            continue
        key = r.get("rate_id") or (r.get("advertiser"), r.get("gpu"), r.get("tier"))
        pr = publish_availability(av, r.get("advertiser"), r.get("tier"), now, annotate=True)
        mn = main_ga.publish_availability(av, r.get("advertiser"), r.get("tier"), now, annotate=True)
        pr_all[key] = _stale_view(pr)
        main_all[key] = _stale_view(mn)
        assert _stale_view(pr) == _stale_view(mn), key
        assert _stale_view(stale_guard(av, now)) == _stale_view(main_ga.stale_guard(av, now)), key
    assert pr_all == main_all
