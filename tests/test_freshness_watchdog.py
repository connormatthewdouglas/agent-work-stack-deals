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


def test_empty_rates_all_held_future_and_shrink(fixed_owner_hold):
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


def test_owner_hold_json_is_not_a_ranked_staleness_failure(fixed_owner_hold):
    """The owner hold list is read (fixed fixture list here). An old Hyperstack row does not fail the 48h bar; a non-held row still does."""
    assert W._is_owner_held("Hyperstack") and W._is_owner_held("Verda (formerly DataCrunch)")
    assert not W._is_owner_held("RunPod") and not W._is_owner_held("Lambda")
    feed = {**FRESH_FEED, "rates": [
        {"advertiser": "Hyperstack", "gpu": "H100", "tier": "On-demand", "verified_at": "2026-11-01T00:00:00Z"},
        {"advertiser": "RunPod", "gpu": "H100", "tier": "On-demand", "verified_at": "2026-11-09T08:00:00Z"},
    ]}
    assert W.evaluate(feed, HOSTED_OK, now=NOW, expected_version="0.6.2", expected_build=EXPECT) == []
    stale = {**feed, "rates": feed["rates"] + [
        {"advertiser": "Lambda", "gpu": "A100", "tier": "On-demand", "verified_at": "2026-11-01T00:00:00Z"}]}
    probs = W.evaluate(stale, HOSTED_OK, now=NOW, expected_version="0.6.2", expected_build=EXPECT)
    assert any("Lambda" in p and "48h" in p for p in probs)
    assert not any("Hyperstack" in p for p in probs)


def test_last_success_older_than_twice_the_schedule():
    assert W.SUCCESS_WINDOW == 2
    assert W.FEED_MAX_HOURS == 26 and W.AVAIL_MAX_HOURS == 4 and W.ROW_MAX_HOURS == 48
    assert W.COLLECTORS == (("gpu-refresh.yml", 24), ("lium-collect.yml", 2), ("scout-import.yml", 4))
    bodies = {name: (ROOT / ".github/workflows" / name).read_text(encoding="utf-8") for name, _h in W.COLLECTORS}
    assert 'cron: "23 10 * * *"' in bodies["gpu-refresh.yml"] and 'cron: "47 14 * * *"' in bodies["gpu-refresh.yml"]
    assert 'cron: "40 */2 * * *"' in bodies["lium-collect.yml"]
    assert 'cron: "*/10 * * * *"' in bodies["scout-import.yml"] and "4-hourly" in bodies["scout-import.yml"]
    assert W.collector_problems({"conclusion": "success", "url": "u"}, "2026-11-09T09:00:00Z",
                                name="lium-collect.yml", interval_h=2, now=NOW) == []
    late = W.collector_problems({"conclusion": "success", "url": "u"}, "2026-11-09T07:00:00Z",
                                name="lium-collect.yml", interval_h=2, now=NOW)
    assert late and "limit 4h" in late[0] and "2h schedule" in late[0]
    scout = W.collector_problems({"conclusion": "success"}, "2026-11-09T00:00:00Z",
                                 name="scout-import.yml", interval_h=4, now=NOW)
    assert scout and "limit 8h" in scout[0]
    assert W.collector_problems({"conclusion": "success"}, "2026-11-07T13:00:00Z",
                                name="gpu-refresh.yml", interval_h=24, now=NOW) == []
    daily = W.collector_problems({"conclusion": "success"}, "2026-11-07T10:00:00Z",
                                 name="gpu-refresh.yml", interval_h=24, now=NOW)
    assert daily and "limit 48h" in daily[0]
    failed = W.collector_problems({"conclusion": "failure", "url": "u"}, "2026-11-09T11:00:00Z",
                                  name="lium-collect.yml", interval_h=2, now=NOW)
    assert any("conclusion failure" in p for p in failed) and not any("last success" in p for p in failed)


def test_workflow_schedule_label_and_node24_actions():
    text = (ROOT / ".github/workflows/freshness-watchdog.yml").read_text(encoding="utf-8")
    assert 'cron: "11 */4 * * *"' in text
    assert "issues: write" in text and "actions: read" in text
    assert "freshness-watchdog" in text
    assert "actions/checkout@v5" in text and "actions/setup-python@v6" in text
    assert "fetch-depth: 0" in text
    assert W.FEED_MAX_HOURS == 26 and W.AVAIL_MAX_HOURS == 4
