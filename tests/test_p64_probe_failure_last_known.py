"""P64 (marxsignal, Brain #971 / #981): quota and region failures must not overwrite last_known.

A failed probe can move the check time forward; last_known_in_stock / last_known_at stay at the
last firm true/false observation. sold_out (in_stock false) last_known goes stale on the same
clock as an in_stock true reading: AVAIL_MAX_AGE_H hours after last_known_at.
"""
from datetime import datetime, timedelta, timezone

from core.gpu_availability import AVAIL_MAX_AGE_H, apply_probe, carry_scout_row, last_known, stale_guard
from core.probe_reason import is_quota_or_region_failure

T0 = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
CHECK = "2026-11-11T12:00:00Z"
LATER = "2026-11-11T13:00:00Z"  # +1h


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _firm(in_stock, at=CHECK, **extra):
    from core.gpu_availability import expires_at
    a = {"status": "available when checked" if in_stock else "out of stock when checked",
         "in_stock": in_stock, "checked_at": at, "origin": "scout",
         "availability_expires_at": expires_at(at), "max_age_hours": AVAIL_MAX_AGE_H}
    a.update(extra)
    return a


def _failure(reason, detail, at=LATER, last_check_at=None, **extra):
    a = {"status": "unknown", "in_stock": None, "checked_at": at, "origin": "scout",
         "availability_reason": reason, "availability_reason_detail": detail}
    if last_check_at is not None:
        a["last_check_at"] = last_check_at
    a.update(extra)
    return a


def test_quota_or_region_failure_keeps_last_known_while_check_time_moves():
    """marxsignal (Colony 2e258e4b comment 068c34a9): on quota or region failure rows,
    last_known_in_stock and last_known_at stay fixed while the check time
    (checked_at / last_check_at) moves forward."""
    cases = (
        ("quota", "quota_exceeded"),
        ("quota", "quota_exhausted"),
        ("quota", "rate_limited"),
        ("region", "region_unavailable"),
        ("region", "not_in_region"),
    )
    for prior in (True, False):
        prev = _firm(prior, last_check_at=CHECK)
        for reason, detail in cases:
            # in_stock false on the failure row must not become the new last_known
            for fail_stock in (None, False):
                cur = _failure(reason, detail, at=LATER, last_check_at=LATER, in_stock=fail_stock)
                if fail_stock is False:
                    cur["status"] = "out of stock when checked"
                out = apply_probe(prev, cur, now=T0 + timedelta(hours=1))
                assert out["last_known_in_stock"] is prior, (prior, reason, detail, fail_stock)
                assert out["last_known_at"] == CHECK
                assert out["checked_at"] == LATER
                assert out["last_check_at"] == LATER
                assert out["in_stock"] is None
                assert is_quota_or_region_failure(cur)


def test_real_observation_still_updates_last_known():
    prev = _firm(True, last_check_at=CHECK)
    # a later firm sold_out (not region/quota) updates last_known
    sold = apply_probe(prev, _firm(False, at=LATER, last_check_at=LATER), now=T0 + timedelta(hours=1))
    assert sold["in_stock"] is False
    assert sold["last_known_in_stock"] is False and sold["last_known_at"] == LATER
    assert sold["checked_at"] == LATER
    # a later firm in-stock updates it again
    back = apply_probe(sold, _firm(True, at="2026-11-11T14:00:00Z", last_check_at="2026-11-11T14:00:00Z"),
                       now=T0 + timedelta(hours=2))
    assert back["in_stock"] is True
    assert back["last_known_in_stock"] is True and back["last_known_at"] == "2026-11-11T14:00:00Z"
    # a quota failure after that keeps the updated last_known, not the original
    fail = apply_probe(back, _failure("quota", "quota_exceeded", at="2026-11-11T15:00:00Z",
                                      last_check_at="2026-11-11T15:00:00Z"),
                       now=T0 + timedelta(hours=3))
    assert fail["last_known_in_stock"] is True and fail["last_known_at"] == "2026-11-11T14:00:00Z"
    assert fail["checked_at"] == fail["last_check_at"] == "2026-11-11T15:00:00Z"
    assert fail["in_stock"] is None


def test_sold_out_and_in_stock_last_known_go_stale_on_the_same_clock():
    """A sold_out (in_stock false) last_known is marked stale on the same clock as in_stock true:
    AVAIL_MAX_AGE_H hours after last_known_at (core/gpu_availability.py)."""
    assert AVAIL_MAX_AGE_H == 8
    still_fresh = T0 + timedelta(hours=AVAIL_MAX_AGE_H)  # h == 8, now == expiry: still fresh
    just_stale = T0 + timedelta(hours=AVAIL_MAX_AGE_H, seconds=1)
    for firm in (True, False):
        live_fresh = stale_guard(_firm(firm), still_fresh)
        assert live_fresh["in_stock"] is firm and not live_fresh.get("availability_stale")
        live_stale = stale_guard(_firm(firm), just_stale)
        assert live_stale["in_stock"] is None and live_stale["availability_stale"] is True
        assert live_stale["last_known_in_stock"] is firm and live_stale["last_known_at"] == CHECK
        # After a later quota failure, last_known still ages from last_known_at, not from checked_at.
        failed = apply_probe(_firm(firm, last_check_at=CHECK),
                             _failure("quota", "rate_limited", at=LATER, last_check_at=LATER),
                             now=T0 + timedelta(hours=1))
        assert failed["checked_at"] == LATER and failed["last_known_at"] == CHECK
        mid = stale_guard(failed, still_fresh)
        assert mid.get("availability_stale") is not True
        assert mid["last_known_in_stock"] is firm and mid["last_known_at"] == CHECK
        assert mid["checked_at"] == LATER  # check time stays at the failed probe
        aged = stale_guard(failed, just_stale)
        assert aged["availability_stale"] is True
        assert aged["last_known_in_stock"] is firm and aged["last_known_at"] == CHECK
        assert aged["checked_at"] == LATER
        assert aged["in_stock"] is None


def test_each_failure_reason_ageing():
    """Documented reasons: whether they keep last_known, and when it is marked stale."""
    prev = _firm(True, last_check_at=CHECK)
    just_stale = T0 + timedelta(hours=AVAIL_MAX_AGE_H, seconds=1)
    # quota / region / other (check_failed_*): keep last_known; stale after AVAIL_MAX_AGE_H from last_known_at
    keepers = (
        _failure("quota", "quota_exceeded", at=LATER, last_check_at=LATER),
        _failure("region", "region_unavailable", at=LATER, last_check_at=LATER),
        _failure("check_failed_http", "http_429", at=LATER, last_check_at=LATER),
        _failure("check_failed_timeout", "timeout", at=LATER, last_check_at=LATER),
        _failure("no_source", "no_api", at=LATER, last_check_at=LATER),
    )
    for cur in keepers:
        out = apply_probe(prev, cur, now=T0 + timedelta(hours=1))
        assert out["last_known_in_stock"] is True and out["last_known_at"] == CHECK, cur["availability_reason"]
        assert out["checked_at"] == LATER and out["in_stock"] is None
        aged = stale_guard(out, just_stale)
        assert aged["availability_stale"] is True
        assert aged["last_known_in_stock"] is True and aged["last_known_at"] == CHECK
        assert aged["checked_at"] == LATER
    # sold_out is a firm observation: it updates last_known, then ages on that new time
    sold = apply_probe(prev, _firm(False, at=LATER, last_check_at=LATER), now=T0 + timedelta(hours=1))
    assert sold["last_known_in_stock"] is False and sold["last_known_at"] == LATER
    assert stale_guard(sold, T0 + timedelta(hours=1) + timedelta(hours=AVAIL_MAX_AGE_H)).get("availability_stale") is not True
    assert stale_guard(sold, T0 + timedelta(hours=1) + timedelta(hours=AVAIL_MAX_AGE_H, seconds=1))["availability_stale"] is True
    # no prior firm claim + no_source: last_known is not invented
    bare = apply_probe(None, _failure("no_source", "no_api", at=LATER), now=T0 + timedelta(hours=1))
    assert last_known(bare) == (None, None)
    assert "last_known_in_stock" not in bare and "last_known_at" not in bare


def test_carry_scout_row_keeps_last_known_only_when_current_is_not_firm():
    prev = {"vendor": "RunPod", "gpu": "H100", "tier": "Secure", "in_stock": True,
            "availability_checked_at": CHECK, "availability_reason": "in_stock"}
    firm = {"vendor": "RunPod", "gpu": "H100", "tier": "Secure", "in_stock": True,
            "availability_checked_at": LATER, "availability_reason": "in_stock"}
    out = carry_scout_row(dict(firm), prev)
    assert "last_known_in_stock" not in out and "last_known_at" not in out
    assert out["in_stock"] is True
    keep = ("in_stock", "offer_count", "unrented_servers", "stock_level", "available_regions", "availability_note", "last_known_in_stock")
    assert any(out.get(k) is not None for k in keep)
    fail = {"vendor": "RunPod", "gpu": "H100", "tier": "Secure", "in_stock": False,
            "availability_checked_at": LATER, "availability_reason": "quota",
            "availability_reason_detail": "quota_exceeded"}
    out = carry_scout_row(dict(fail), prev)
    assert out["in_stock"] is None
    assert out["last_known_in_stock"] is True and out["last_known_at"] == CHECK
    bare = {"vendor": "RunPod", "gpu": "H100", "tier": "Secure", "in_stock": None,
            "availability_checked_at": LATER, "availability_reason": "no_source"}
    out = carry_scout_row(dict(bare), None)
    assert "last_known_in_stock" not in out and "last_known_at" not in out
