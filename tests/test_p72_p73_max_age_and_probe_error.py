"""P72 (max_age_source / availability_expires_at) and P73 (probe crash). Pinned clocks; no network."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core import gpu_availability as A
from core.gpu import last_successful_check_at
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_gpu_freshness as gate  # noqa: E402

CLOCK = datetime(2026, 11, 27, 14, 23, tzinfo=timezone.utc)
CHECK = "2026-11-27T13:23:00Z"  # 1h before CLOCK; used by annotate_max_age tests
# Inside the 1h policy with room for CI's LW_BUILD_HORIZON_MIN=25 cutoff (build_now = now + horizon).
NO_SOURCE_CHECK = "2026-11-27T13:53:00Z"  # 30 min before CLOCK
ATTEMPT = "2026-11-27T14:23:00Z"
OLD_OK = "2026-11-26T12:00:00Z"


@pytest.fixture(autouse=True)
def _pin_build_horizon(monkeypatch):
    """These tests pass an explicit now=; do not let a generate-time horizon shift the clock."""
    monkeypatch.delenv("LW_BUILD_HORIZON_MIN", raising=False)


def test_max_age_source_provider():
    av = A.annotate_max_age(
        {"checked_at": CHECK, "in_stock": True, "origin": "scout",
         "provider_max_age_hours": 2, "tier": "On-demand"},
        vendor="ExampleCloud",
        tier="On-demand",
    )
    assert av["max_age_source"] == A.MAX_AGE_SOURCE_PROVIDER
    assert av["max_age_hours"] == 2.0
    assert av["availability_expires_at"] == "2026-11-27T15:23:00Z"
    assert "max_age_reason" not in av


def test_max_age_source_policy():
    # Lambda overall claims follow the 1h policy.
    av = A.annotate_max_age(
        {"checked_at": CHECK, "in_stock": True, "origin": "scout", "tier": "On-demand instance (1x GPU)"},
        vendor="Lambda",
        tier="On-demand instance (1x GPU)",
    )
    assert av["max_age_source"] == A.MAX_AGE_SOURCE_POLICY
    assert av["max_age_hours"] == 1.0
    assert av["availability_expires_at"] == "2026-11-27T14:23:00Z"
    assert "max_age_reason" not in av


def test_max_age_source_fallback():
    av = A.annotate_max_age(
        {"in_stock": None, "status": "unknown", "origin": "scout", "availability_reason": "never_ran"},
        vendor="ExampleCloud",
    )
    assert av["max_age_source"] == A.MAX_AGE_SOURCE_FALLBACK
    assert av["max_age_hours"] is None
    assert av["availability_expires_at"] is None
    assert av["max_age_reason"] == "never_ran: no check time to compute expiry"


def test_availability_expires_at_present_on_no_source_rows():
    """A no_source Scout row with a check time gets a computed expiry (policy); the key is always present."""
    row = {
        "vendor": "Lambda",
        "gpu": "H100 PCIe",
        "vram_gb": 80,
        "tier": "On-demand instance (1x GPU)",
        "in_stock": None,
        "availability_checked_at": NO_SOURCE_CHECK,
        "availability_expires_at": None,
        "availability_reason": "no_source",
        "availability_reason_detail": "unconfirmed_two_reads",
        "availability_source": "public no-auth API",
    }
    A._CACHE = {("Lambda", "H100 PCIe", 80, A._tier_key(row["tier"])): row}
    try:
        out = A.availability_for("Lambda", "H100 PCIe", 80, row["tier"], now=CLOCK)
    finally:
        A._CACHE = None
    assert "availability_expires_at" in out
    assert out["availability_expires_at"] == "2026-11-27T14:53:00Z"
    assert out["max_age_source"] == A.MAX_AGE_SOURCE_POLICY
    assert out["max_age_hours"] == 1.0
    assert out["in_stock"] is None
    assert out.get("availability_reason") == "no_source"
    # No stamp invented on the Scout row itself.
    assert row["availability_checked_at"] == NO_SOURCE_CHECK and row["availability_expires_at"] is None


def test_probe_crash_writes_error_and_does_not_count_as_success():
    """A crashed stock/terms probe writes probe_error plus the attempt time; verified_at and the
    successful checked_at are unchanged; freshness / expire_held_rows still use only success stamps."""
    previous = {
        "vendor": "ExampleCloud",
        "gpu": "H100",
        "tier": "On-demand",
        "checked_at": OLD_OK,
        "verified_at": OLD_OK,
        "evidence": {"source_url": "https://example.com/pricing", "quote": "H100 $1.00/hr", "checked_at": OLD_OK},
        "in_stock": True,
    }
    exc = RuntimeError("timeout talking to https://api.example.com/stock?token=SUPERSECRET and bearer=ABCD")
    out = A.apply_probe_crash(previous, exc, attempted_at=datetime(2026, 11, 27, 14, 23, tzinfo=timezone.utc))
    assert out["probe_error"]["type"] == "RuntimeError"
    assert "SUPERSECRET" not in out["probe_error"]["message"]
    assert "ABCD" not in out["probe_error"]["message"]
    assert "token=[redacted]" in out["probe_error"]["message"] or "[redacted]" in out["probe_error"]["message"]
    assert out["probe_attempted_at"] == ATTEMPT
    assert out["checked_at"] == OLD_OK
    assert out["verified_at"] == OLD_OK
    assert out["evidence"]["checked_at"] == OLD_OK
    assert last_successful_check_at(out) == last_successful_check_at(previous)

    from datetime import timedelta
    # A recent successful check plus a later crash attempt stays fresh: the attempt is
    # not a success stamp and does not replace checked_at, so the 26h bar still uses OLD_OK
    # only when that is the success time. Rebuild with a 1h-old success to show the gate
    # stays green, then with a 73h-old success to show a later attempt cannot clear the 72h ceiling.
    recent = (CLOCK - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent_row = A.apply_probe_crash(
        {**previous, "checked_at": recent, "verified_at": recent,
         "evidence": {**previous["evidence"], "checked_at": recent}},
        exc, attempted_at=CLOCK,
    )
    assert recent_row["checked_at"] == recent and recent_row["probe_attempted_at"] == ATTEMPT
    assert last_successful_check_at(recent_row).strftime("%Y-%m-%dT%H:%M:%SZ") == recent
    docs_ok = [{"vendor": "ExampleCloud", "records": [recent_row]}]
    code, msgs = gate.status(CLOCK, 26, docs=docs_ok, held_stale=[])
    assert code == 0, msgs
    assert "hard ceiling" not in "\n".join(msgs)
    assert gate._successfully_reverified(recent_row) is True

    old73 = (CLOCK - timedelta(hours=73)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_row = A.apply_probe_crash(
        {**previous, "checked_at": old73, "verified_at": old73,
         "evidence": {**previous["evidence"], "checked_at": old73}},
        exc, attempted_at=CLOCK,
    )
    assert stale_row["checked_at"] == old73
    assert stale_row["probe_attempted_at"] == ATTEMPT
    docs_old = [
        {"vendor": "Ok", "records": [{"checked_at": recent, "gpu": "H100", "tier": "On-demand"}]},
        {"vendor": "ExampleCloud", "records": [stale_row]},
    ]
    code, msgs = gate.status(CLOCK, 26, docs=docs_old, held_stale=[])
    assert code == 1, msgs
    assert any("older than 72 h" in m and "hard ceiling" in m and "ExampleCloud" in m for m in msgs)
