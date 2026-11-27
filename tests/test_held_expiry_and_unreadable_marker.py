"""Held-row 72h expiry and the no-$ page-marker rule. Pinned clocks and fixtures only; no network."""
from __future__ import annotations

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import check_gpu_freshness as gate  # noqa: E402
import refresh_gpu_prices as R  # noqa: E402
from core.gpu import HOLD_EXPIRE_HOURS, build_rates, last_successful_check_at  # noqa: E402
from test_gpu_history import Fake, NOW, PAGE, doc, rec  # noqa: E402


CLOCK = datetime(2026, 11, 27, 6, 25, tzinfo=timezone.utc)
URL = "https://example.com/gpu-rental/rtx-4090/"


def _held_rec(*, age_h: float, stale=None, no_capacity=None, gpu="RTX 4090", price=0.67):
    verified = (CLOCK - timedelta(hours=age_h)).replace(microsecond=0).isoformat()
    r = {
        "vendor": "ExampleCloud",
        "gpu": gpu,
        "vram_gb": 24,
        "price_usd": price,
        "billing_unit": "hourly",
        "hourly_usd": price,
        "interruptible": False,
        "tier": "On-demand",
        "form_factor": "PCIe",
        "quote": f"On ExampleCloud the NVIDIA {gpu} is ${price}/hr per GPU",
        "source_url": URL,
        "checked_at": verified,
        "verified_at": verified,
        "evidence": {
            "source_url": URL,
            "quote": f"On ExampleCloud the NVIDIA {gpu} is ${price}/hr per GPU",
            "checked_at": verified,
        },
    }
    if stale is not None:
        r["stale"] = stale
    if no_capacity is not None:
        r["no_capacity"] = no_capacity
    return r


def _doc_for(r: dict) -> dict:
    return {
        "vendor": r["vendor"],
        "deal_id": None,
        "source_url": r["source_url"],
        "checked_at": r["checked_at"],
        "extras": {k: {"status": "unknown", "text": "x", "source_url": r["source_url"]}
                   for k in ("egress", "storage", "interruption")},
        "records": [r],
    }


def _fresh_ok():
    stamp = (CLOCK - timedelta(hours=1)).isoformat()
    return {"vendor": "Ok", "records": [{"checked_at": stamp, "gpu": "H100", "tier": "On-demand"}]}


def test_held_row_past_72h_is_expired_and_freshness_passes():
    """A generate-time held row whose last successful check is 73h old is marked expired;
    evidence and stamps are kept; freshness with that held_stale list exits 0."""
    rec73 = _held_rec(age_h=73)
    before = copy.deepcopy(rec73)
    out = build_rates([], [_doc_for(rec73)], now=CLOCK)
    assert out["rates"] == []
    held = out["held_stale"]
    assert held and held[0]["expired"] is True
    assert "older than 72 h" in held[0]["expired_reason"]
    ev = held[0]["records"][0]["evidence"]
    assert ev["quote"] == before["evidence"]["quote"]
    assert ev["source_url"] == before["evidence"]["source_url"]
    assert held[0]["records"][0]["quote"] == before["quote"]
    assert last_successful_check_at(held[0]["records"][0]) == last_successful_check_at(before)
    assert rec73["checked_at"] == before["checked_at"]
    assert rec73["verified_at"] == before["verified_at"]
    assert rec73.get("stale") is None
    assert last_successful_check_at(held[0]["records"][0]) == last_successful_check_at(before)
    assert HOLD_EXPIRE_HOURS == 72.0 == gate.CEILING_HOURS

    docs = [_fresh_ok(), _doc_for(rec73)]
    code, msgs = gate.status(CLOCK, 26, docs=docs, held_stale=held)
    assert code == 0, msgs
    assert "hard ceiling" not in "\n".join(msgs)
    assert "ExampleCloud|RTX 4090" not in "\n".join(msgs)


def test_ranked_row_past_72h_still_fails_freshness():
    """An unheld ranked row 73h old still trips the 72h ceiling. The bar is not loosened."""
    # Just inside 48h so generate-time hold does not apply; the row stays rankable / unheld.
    rec73 = _held_rec(age_h=73)
    # status looks at vendor files, not generate output: an unheld vendor record past 72h fails
    # even if a sibling refresh is fresh.
    docs = [_fresh_ok(), _doc_for(rec73)]
    code, msgs = gate.status(CLOCK, 26, docs=docs, held_stale=[])
    assert code == 1, msgs
    assert any("older than 72 h" in m and "hard ceiling" in m and "ExampleCloud|RTX 4090|On-demand" in m
               for m in msgs)


def test_held_row_under_72h_is_unchanged():
    """A held row at 50h (past 48h, under 72h) stays in held_stale with its age label; not expired."""
    from core.data_age import stale_label
    rec50 = _held_rec(age_h=50)
    before = copy.deepcopy(rec50)
    out = build_rates([], [_doc_for(rec50)], now=CLOCK)
    assert out["rates"] == []
    held = out["held_stale"]
    assert len(held) == 1
    assert held[0].get("expired") is not True
    assert "expired_reason" not in held[0]
    assert held[0]["reason"] == stale_label(rec50, CLOCK)
    assert held[0]["records"][0]["quote"] == before["quote"]
    ev = held[0]["records"][0]["evidence"]
    assert ev["quote"] == before["evidence"]["quote"]
    assert ev["source_url"] == before["evidence"]["source_url"]
    assert last_successful_check_at(held[0]["records"][0]) == last_successful_check_at(before)
    # Vendor record stamps and hold flags are not rewritten. (Published evidence
    # strings are UTC-Z normalized by apply_utc_z on a shared dict; the instant is the same.)
    assert rec50["checked_at"] == before["checked_at"]
    assert rec50["verified_at"] == before["verified_at"]
    assert rec50.get("stale") is None
    code, msgs = gate.status(CLOCK, 26, docs=[_fresh_ok(), _doc_for(rec50)], held_stale=held)
    assert code == 0, msgs
    assert "hard ceiling" not in "\n".join(msgs)


def test_no_dollar_page_with_marker_is_held_without_inventing():
    """A 200 product page that shows the GPU name but no $ figures is auto-held; stamps are not invented."""
    d = doc(rec(gpu="RTX 4090", form_factor="PCIe"))
    page = (
        "<html><body>"
        "Explore NVIDIA RTX 4090 Features &amp; Specs | High-Performance GPU Model "
        "RTX 4090: Unleash superior performance. GPU Architecture Ada Lovelace. "
        "Start Building Now"
        "</body></html>"
    )
    rows = R.refresh([d], Fake(page), NOW)
    r = d["records"][0]
    assert r["price_usd"] == 1.99 and r["hourly_usd"] == 1.99
    assert r["verified_at"] == "2026-11-01T10:00:00+00:00"
    assert r["checked_at"] == "2026-11-01T10:00:00+00:00"
    assert r["last_failed_check_at"] == "2026-11-03T12:00:00+00:00"
    assert r["stale"]["auto"] is True
    assert "no $ price figures in visible page text" in r["stale"]["reason"]
    assert rows[0]["result"].startswith("unreadable") and "HELD" in rows[0]["result"]
    assert R.listed_page_marker_visible(r, R.page_text(page))


def test_no_dollar_interstitial_without_marker_does_not_hold_or_stamp():
    """A 200 bot-check / interstitial page with no GPU marker and no $ is a failed read:
    no new hold, checked_at / verified_at / quote / evidence unchanged."""
    d = doc(rec(gpu="RTX 4090", form_factor="PCIe"))
    before = copy.deepcopy(d["records"][0])
    page = (
        "<html><body>"
        "Just a moment... Checking your browser before you continue. "
        "Enable JavaScript and cookies to continue. Cloudflare ray id 000."
        "</body></html>"
    )
    rows = R.refresh([d], Fake(page), NOW)
    r = d["records"][0]
    assert "stale" not in r
    assert r["price_usd"] == before["price_usd"]
    assert r["quote"] == before["quote"]
    assert r["evidence"] == before["evidence"]
    assert r["checked_at"] == before["checked_at"]
    assert r["verified_at"] == before.get("verified_at") or before["checked_at"]
    assert r["last_failed_check_at"] == "2026-11-03T12:00:00+00:00"
    assert rows[0]["result"].startswith("unreadable") and "HELD" not in rows[0]["result"]
    assert not R.listed_page_marker_visible(r, R.page_text(page))
    assert not R.PRICE_RE.search(R.page_text(page))
