"""A4: outside watchdog. 26h and 4h bars stay put; T41-12's 48h bar applies per ranked row."""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import freshness_watchdog as W  # noqa: E402

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
FRESH_FEED = {
    "feed_updated_at": "2026-11-09T10:00:00Z",
    "availability_collected_at": "2026-11-09T11:30:00Z",
    "rates": [{"advertiser": "RunPod", "gpu": "H100", "tier": "On-demand", "verified_at": "2026-11-09T08:00:00Z",
               "checked_at": "2026-11-09T08:00:00Z"}],
    "held_stale": [],
}
HOSTED_OK = {"version": "0.6.2", "build": "21684cc5"}
EXPECT = "21684cc5ca768c928e4ecc1d3c957b71c091efbe"


def test_thresholds_are_the_existing_bars():
    assert W.FEED_MAX_HOURS == 26
    assert W.AVAIL_MAX_HOURS == 4
    assert W.ROW_MAX_HOURS == 48


def test_stale_live_surfaces():
    feed = {"feed_updated_at": "2026-11-06T06:50:00Z", "availability_collected_at": "2026-11-06T02:51:00Z",
            "rates": [{"advertiser": "RunPod", "gpu": "H100", "tier": "On-demand", "verified_at": "2026-11-06T06:50:00Z"}],
            "held_stale": []}
    hosted = {"version": "0.6.0", "build": "2767db56"}
    probs = W.evaluate(feed, hosted, now=NOW, expected_version="0.6.2", expected_build=EXPECT)
    assert any(p.startswith("feed_updated_at") and "26h" in p for p in probs)
    assert any(p.startswith("availability_collected_at") and "4h" in p for p in probs)
    assert any("0.6.0" in p and "0.6.2" in p for p in probs)
    assert any("48h" in p for p in probs)


def test_matching_build_is_fresh_and_a_different_build_is_not():
    assert W.evaluate(FRESH_FEED, HOSTED_OK, now=NOW, expected_version="0.6.2", expected_build=EXPECT) == []
    probs = W.evaluate(FRESH_FEED, {"version": "0.6.2", "build": "2767db56"}, now=NOW,
                       expected_version="0.6.2", expected_build=EXPECT)
    assert len(probs) == 1 and probs[0].startswith("hosted MCP build")


def test_unresolvable_or_short_build_fails():
    for bad in ("", None, "abc", "123456", "not-a-sha", "unknown"):
        probs = W.evaluate(FRESH_FEED, {"version": "0.6.2", "build": bad}, now=NOW,
                           expected_version="0.6.2", expected_build=EXPECT)
        assert probs and "unresolvable" in probs[0], bad
    probs = W.evaluate(FRESH_FEED, HOSTED_OK, now=NOW, expected_version="0.6.2", expected_build="")
    assert any("expected build is unresolvable" in p for p in probs)
    assert not W.builds_match("21684c", EXPECT)  # 6 hex digits is not enough
    assert W.builds_match("21684cc", EXPECT)


def test_empty_rates_all_held_future_and_shrink(monkeypatch):
    monkeypatch.setattr(W, "_owner_names", lambda: ["Hyperstack", "Verda"])
    empty = {**FRESH_FEED, "rates": [], "held_stale": [
        {"vendor": "Hyperstack", "checked_at": "2026-11-01T00:00:00Z", "reason": "owner hold"}]}
    probs = W.evaluate(empty, HOSTED_OK, now=NOW, expected_version="0.6.2", expected_build=EXPECT,
                       committed_rate_count=100)
    assert any("rates list is empty" in p for p in probs)
    assert any("all tracked rows are held" in p for p in probs)
    assert any("shrank from 100 to 0" in p for p in probs)
    holds = W.hold_lines(empty, NOW)
    assert holds and holds[0].startswith("held owner-held Hyperstack") and "h" in holds[0]
    future = {**FRESH_FEED, "feed_updated_at": "2026-11-10T00:00:00Z",
              "rates": [{"advertiser": "RunPod", "gpu": "H100", "tier": "On-demand", "verified_at": "2026-11-10T00:00:00Z"}]}
    fprobs = W.evaluate(future, HOSTED_OK, now=NOW, expected_version="0.6.2", expected_build=EXPECT)
    assert any("in the future" in p for p in fprobs)
    shrunk = {**FRESH_FEED, "rates": FRESH_FEED["rates"] * 1}
    assert any("shrank from 10 to 1" in p for p in W.evaluate(
        shrunk, HOSTED_OK, now=NOW, expected_version="0.6.2", expected_build=EXPECT, committed_rate_count=10))


def test_failed_collector_run_is_a_problem():
    notes = ["gpu-refresh.yml: conclusion failure (https://example.test/run)"]
    probs = W.evaluate(FRESH_FEED, HOSTED_OK, now=NOW, expected_version="0.6.2", expected_build=EXPECT,
                       workflow_notes=notes)
    assert probs == notes


def test_checkout_version_commit_is_0_6_2():
    version, sha = W.expected_from_checkout(ROOT)
    assert version == "0.6.2"
    assert sha.startswith("21684cc5") and len(sha) >= 7


def test_workflow_schedule_label_and_node24_actions():
    text = (ROOT / ".github/workflows/freshness-watchdog.yml").read_text(encoding="utf-8")
    assert 'cron: "11 */4 * * *"' in text
    assert "issues: write" in text and "actions: read" in text
    assert "freshness-watchdog" in text
    assert "actions/checkout@v5" in text and "actions/setup-python@v6" in text
    assert "fetch-depth: 0" in text
    assert W.FEED_MAX_HOURS == 26 and W.AVAIL_MAX_HOURS == 4
