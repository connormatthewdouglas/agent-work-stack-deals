"""P63 reserved cancellation terms (Brain #966, #1082, #1099).

Deterministic fixture-page tests only. No live network. No skip/xfail.
Stale-set parity vs origin/main at a pinned feed clock.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scout"))

from core import cancel_terms, gpu as G
from core.gpu_availability import publish_availability, stale_guard
import civo_probe
import refresh_gpu_prices as R
import collect_v2

NOW = datetime(2026, 11, 28, 8, 0, tzinfo=timezone.utc)
STAMP = "2026-11-28T08:00:00Z"
FEED = ROOT / "api" / "v1" / "gpu-prices.json"
FIX = ROOT / "tests" / "fixtures"

CIVO_HTML = (FIX / "civo-legal-terms.html").read_text()
CR_HTML = (FIX / "cloudrift-terms.html").read_text()
HS_HTML = (FIX / "hyperstack-contracts.html").read_text()


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("P63 tests must not make live calls")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    monkeypatch.setattr("urllib.request.Request", boom)


def _civo_reserved(price_checked_at="2026-11-20T12:00:00Z"):
    return {
        "vendor": "Civo",
        "gpu": "H100 SXM",
        "vram_gb": 80,
        "tier": "6-month commitment",
        "tier_class": "reserved",
        "price_usd": 2.79,
        "hourly_usd": 2.79,
        "billing_unit": "hourly",
        "interruptible": False,
        "checked_at": price_checked_at,
        "verified_at": price_checked_at,
        "source_url": "https://www.civo.com/pricing",
        "quote": "Small 1 x NVIDIA H100 - 80GB $2.79 per hour",
        "evidence": {
            "source_url": "https://www.civo.com/pricing",
            "quote": "Small 1 x NVIDIA H100 - 80GB $2.79 per hour",
            "checked_at": price_checked_at,
        },
    }


def test_civo_probe_reads_published_shortfall_and_nonrefundable_upfront():
    rec = _civo_reserved()
    ev_before = dict(rec["evidence"])
    checked = rec["checked_at"]
    result = civo_probe.probe_cancel_terms(
        CIVO_HTML, collected_at=STAMP, fetch_ok=True,
        source_url=cancel_terms.CIVO_TERMS_URL,
    )
    assert result["terms_flag"] == cancel_terms.TERMS_PRESENT_AND_READ
    assert result["terms_read_at"] == STAMP
    assert result["source_url"] == cancel_terms.CIVO_TERMS_URL
    assert "spend commitment shortfall payment" in result["cancel_fee"]["text"]
    assert "upfront payments are non-refundable" in result["cancel_fee"]["text"]
    assert "cancel_window" not in result  # no numeric/notice window is published
    assert "Commitment Discount" in result["quote"]
    civo_probe.attach_cancel_terms([rec], result)
    assert rec["cancellation"]["terms_flag"] == "present_and_read"
    # Price evidence, quote IDs, and price timestamps stay put.
    assert rec["evidence"] == ev_before
    assert rec["checked_at"] == checked
    assert rec["verified_at"] == checked
    assert rec["quote"] == ev_before["quote"]


def test_cloudrift_reserved_reads_sales_final_no_refund():
    rec = {
        "vendor": "CloudRift",
        "gpu": "L40S",
        "tier": '1 Month (reserved, "1 mo")',
        "tier_class": "reserved",
        "checked_at": "2026-11-18T00:00:00Z",
        "verified_at": "2026-11-18T00:00:00Z",
        "evidence": {
            "source_url": "https://www.cloudrift.ai/l40",
            "quote": "Reserved terms bring it to $0.62/hr for 1 month",
            "checked_at": "2026-11-18T00:00:00Z",
        },
    }
    ev = dict(rec["evidence"])
    result = R.probe_cloudrift_reserved_cancel_terms(
        CR_HTML, collected_at=STAMP, fetch_ok=True,
    )
    assert result["terms_flag"] == "present_and_read"
    assert result["terms_read_at"] == STAMP
    assert result["cancel_fee"]["text"] == "All sales are final and no refund will be issued."
    assert "cancel_window" not in result
    R.attach_cloudrift_reserved_cancel_terms([rec], result)
    assert rec["cancellation"]["terms_flag"] == "present_and_read"
    assert rec["evidence"] == ev
    assert rec["checked_at"] == ev["checked_at"]
    assert rec["verified_at"] == ev["checked_at"]


def test_hyperstack_collect_v2_confirmed_absent_on_contracts_page():
    rec = {
        "vendor": "Hyperstack",
        "gpu": "H200 SXM",
        "tier": "Reservation (starting from)",
        "checked_at": "2026-11-10T00:00:00Z",
        "verified_at": "2026-11-10T00:00:00Z",
        "evidence": {
            "source_url": "https://www.hyperstack.cloud/gpu-pricing",
            "quote": "Reservation Pricing GPU Model Starting from Reserve NVIDIA H200 SXM $2.79 Reserve here",
            "checked_at": "2026-11-10T00:00:00Z",
        },
    }
    ev = dict(rec["evidence"])
    result = collect_v2.hyperstack_reserved_cancel_terms(
        HS_HTML, collected_at=STAMP, fetch_ok=True,
    )
    assert result["terms_flag"] == "confirmed_absent"
    assert result["terms_read_at"] == STAMP
    assert "cancel_window" not in result and "cancel_fee" not in result
    # Expiry Keep/Delete is not recorded as a cancel window.
    collect_v2.attach_hyperstack_reserved_cancel_terms([rec], result)
    assert rec["cancellation"]["terms_flag"] == "confirmed_absent"
    assert rec["evidence"] == ev
    assert rec["checked_at"] == ev["checked_at"]


def test_failed_fetch_is_unreadable_and_never_stamps_read_or_price_times():
    rec = _civo_reserved()
    ev = dict(rec["evidence"])
    checked = rec["checked_at"]
    result = civo_probe.probe_cancel_terms(
        None, collected_at=STAMP, fetch_ok=False, reason="HTTP 503",
    )
    assert result == {
        "terms_flag": "unreadable",
        "source_url": cancel_terms.CIVO_TERMS_URL,
        "unreadable_reason": "HTTP 503",
    }
    assert "terms_read_at" not in result
    civo_probe.attach_cancel_terms([rec], result)
    assert rec["cancellation"]["terms_flag"] == "unreadable"
    assert "terms_read_at" not in rec["cancellation"]
    assert rec["checked_at"] == checked
    assert rec["verified_at"] == checked
    assert rec["evidence"] == ev


def test_failed_cloudrift_and_hyperstack_fetches_are_unreadable():
    cr = R.probe_cloudrift_reserved_cancel_terms(
        "", collected_at=STAMP, fetch_ok=False, reason="disallowed by robots.txt",
    )
    hs = collect_v2.hyperstack_reserved_cancel_terms(
        None, collected_at=STAMP, fetch_ok=False, reason="timeout",
    )
    for result, url in (
        (cr, cancel_terms.CLOUDRIFT_TERMS_URL),
        (hs, cancel_terms.HYPERSTACK_TERMS_URL),
    ):
        assert result["terms_flag"] == "unreadable"
        assert result["source_url"] == url
        assert "terms_read_at" not in result
        assert "cancel_window" not in result
        assert "cancel_fee" not in result


def test_attach_only_reserved_rows_on_demand_stays_unknown():
    reserved = _civo_reserved()
    on_demand = {
        "vendor": "Civo",
        "gpu": "H100 SXM",
        "tier": "On-demand",
        "checked_at": "2026-11-20T12:00:00Z",
    }
    result = civo_probe.probe_cancel_terms(CIVO_HTML, collected_at=STAMP, fetch_ok=True)
    civo_probe.attach_cancel_terms([reserved, on_demand], result)
    assert "cancellation" in reserved
    assert "cancellation" not in on_demand  # unknown stays unknown


def test_confirmed_absent_on_successful_read_with_no_terms():
    blank = "<html><body><p>Hourly GPU rental pricing. Contact sales for reservations.</p></body></html>"
    result = collect_v2.hyperstack_reserved_cancel_terms(
        blank, collected_at=STAMP, fetch_ok=True,
    )
    assert result["terms_flag"] == "confirmed_absent"
    assert result["terms_read_at"] == STAMP
    assert cancel_terms.cancellation_problems(result, "x") == []


def test_record_problems_accepts_additive_cancellation_and_rejects_unreadable_stamp():
    rec = _civo_reserved()
    rec["form_factor"] = "SXM"
    rec["cancellation"] = civo_probe.probe_cancel_terms(
        CIVO_HTML, collected_at=STAMP, fetch_ok=True,
    )
    doc = {
        "vendor": "Civo",
        "deal_id": None,
        "source_url": "https://www.civo.com/pricing",
        "checked_at": rec["checked_at"],
        "extras": {
            "egress": {"status": "unknown", "text": "not published", "source_url": "https://www.civo.com/pricing"},
            "storage": {"status": "unknown", "text": "not published", "source_url": "https://www.civo.com/pricing"},
            "interruption": {"status": "unknown", "text": "not published", "source_url": "https://www.civo.com/pricing"},
        },
        "records": [rec],
    }
    # Isolated shape check of the cancellation object (full vendor-file checks need every required extra).
    assert cancel_terms.cancellation_problems(rec["cancellation"], "civo") == []
    bad = {"terms_flag": "unreadable", "terms_read_at": STAMP, "source_url": cancel_terms.CIVO_TERMS_URL}
    probs = cancel_terms.cancellation_problems(bad, "x")
    assert any("must not stamp terms_read_at" in p for p in probs)


def test_feed_passthrough_is_additive_schema_unchanged_no_ranking_change():
    data = json.loads(FEED.read_text())
    assert data["schema"] == "lantern-works-gpu-prices/1"
    reserved = [r for r in data["rates"] if r.get("tier_class") == "reserved"]
    assert reserved, "feed should have reserved rows"
    # Ranking key used by compare (reserved last, then unmet min_gpus, monthly cost, advertiser, gpu).
    def rank_key(x):
        return (
            x.get("tier_class") == "reserved",
            G.min_gpus_unmet(x, 1),
            x.get("price_usd"),
            x.get("advertiser") or "",
            x.get("gpu") or "",
        )
    before = [rank_key(r) for r in data["rates"]]
    order = [(r.get("advertiser"), r.get("gpu"), r.get("tier")) for r in data["rates"]]
    # Simulate publishing cancellation onto reserved rows only.
    result = {"terms_flag": "confirmed_absent", "terms_read_at": STAMP,
              "source_url": "https://example.com/terms"}
    cloned = []
    for r in data["rates"]:
        row = dict(r)
        if row.get("tier_class") == "reserved":
            row = {**row, "cancellation": result}
        cloned.append(row)
    after = [rank_key(r) for r in cloned]
    assert after == before
    assert [(r.get("advertiser"), r.get("gpu"), r.get("tier")) for r in cloned] == order
    # Additive: on-demand rows still have no cancellation key.
    assert all("cancellation" not in r for r in cloned if r.get("tier_class") != "reserved")


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
    name = "core._p63_main_gpu_availability"
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
