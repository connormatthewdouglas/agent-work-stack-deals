"""P58 (dingdang6284-bot2, #714): first_check_at + observed_hours so callers see real coverage beside window_days 7."""
from core import availability_rate as A

FIRST = "2026-11-11T22:46:10Z"
LAST = "2026-11-12T22:56:27Z"  # 24.171... h -> 24.2


def test_observed_hours_from_first_to_last():
    d = A._describe(10, 5, 2, "s", "e", "scout_t112", first=FIRST, last=LAST)
    assert d["first_check_at"] == FIRST and d["last_check_at"] == LAST
    assert d["observed_hours"] == 24.2
    assert d["rate"] == 0.5 and d["window_days"] == 7


def test_observed_hours_null_without_first_keeps_rate_and_split():
    d = A._describe(10, 5, 4, "s", "e", "git_history", first=None, last=LAST, never_ran=1, no_source=3)
    assert d["first_check_at"] is None and d["observed_hours"] is None
    assert d["rate"] == 0.5 and d["window_days"] == 7
    assert (d["unknown_checks"], d["never_ran_checks"], d["no_source_checks"]) == (4, 1, 3)


def test_observed_hours_falls_back_to_window_end():
    d = A._describe(10, 5, 2, "s", "2026-11-12T22:46:10Z", "git_history", first=FIRST, last=None)
    assert d["observed_hours"] == 24.0 and d["first_check_at"] == FIRST


def test_unparsable_first_is_null_not_a_crash():
    d = A._describe(10, 5, 2, "s", "e", "git_history", first="not-a-stamp", last=LAST)
    assert d["first_check_at"] == "not-a-stamp" and d["observed_hours"] is None


def test_same_first_and_last_is_zero():
    d = A._describe(10, 5, 2, "s", "e", "git_history", first=FIRST, last=FIRST)
    assert d["observed_hours"] == 0.0


def test_fields_scout_path_publishes_observed_hours(monkeypatch):
    monkeypatch.setattr(A, "_SCOUT", {("v", "H100", 80, "On-demand"): ({
        "checks_7d": 10, "known_checks_7d": 7, "in_stock_checks_7d": 7,
        "first_check_at": FIRST, "last_check_at": LAST,
        "never_ran_checks_7d": 1, "no_source_checks_7d": 2,
    }, LAST)})
    r = A.fields("V", "H100", 80, "On-demand", 2)["availability_rate_7d"]
    assert r["first_check_at"] == FIRST and r["observed_hours"] == 24.2
    assert r["window_days"] == 7 and (r["never_ran_checks"], r["no_source_checks"]) == (1, 2)
