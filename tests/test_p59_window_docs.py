"""P59 (dingdang6284-bot2, #724): coverage_note only when observed_hours is shorter than the planned window."""
from core import availability_rate as A

FIRST = "2026-11-11T22:46:10Z"
LAST = "2026-11-12T22:56:27Z"  # 24.2 h


def test_coverage_note_only_when_shorter_than_planned_window():
    d = A._describe(10, 5, 2, "s", "e", "scout_t112", first=FIRST, last=LAST)
    assert d["window_days"] == 7 and d["observed_hours"] == 24.2
    assert d["coverage_note"] == "Covers 24.2h of the planned 7-day window."
    full = A._describe(10, 5, 2, "s", "e", "git_history", first=FIRST, last="2026-11-18T22:46:10Z")  # 168.0 h
    assert full["observed_hours"] == 168.0 and full["coverage_note"] is None
    none = A._describe(10, 5, 2, "s", "e", "git_history", first=None, last=LAST)
    assert none["observed_hours"] is None and none["coverage_note"] is None
