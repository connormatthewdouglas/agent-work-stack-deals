"""A4: the outside watchdog flags a stale feed, stale availability, or an old hosted build."""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import freshness_watchdog as W  # noqa: E402

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def test_thresholds_are_the_existing_bars():
    assert W.FEED_MAX_HOURS == 26
    assert W.AVAIL_MAX_HOURS == 4


def test_stale_live_surfaces():
    feed = {"feed_updated_at": "2026-11-06T06:50:00Z", "availability_collected_at": "2026-11-06T02:51:00Z"}
    hosted = {"version": "0.6.0", "build": "2767db56"}
    probs = W.evaluate(feed, hosted, now=NOW, expected_version="0.6.2", expected_build="21684cc5abcdef")
    assert any(p.startswith("feed_updated_at") and "26h" in p for p in probs)
    assert any(p.startswith("availability_collected_at") and "4h" in p for p in probs)
    assert any("0.6.0" in p and "0.6.2" in p for p in probs)


def test_matching_build_is_fresh_and_a_different_build_is_not():
    feed = {"feed_updated_at": "2026-11-09T10:00:00Z", "availability_collected_at": "2026-11-09T11:30:00Z"}
    assert W.evaluate(feed, {"version": "0.6.2", "build": "21684cc5"}, now=NOW,
                      expected_version="0.6.2", expected_build="21684cc5abcdef") == []
    probs = W.evaluate(feed, {"version": "0.6.2", "build": "2767db56"}, now=NOW,
                       expected_version="0.6.2", expected_build="21684cc5abcdef")
    assert len(probs) == 1 and probs[0].startswith("hosted MCP build")


def test_workflow_fails_the_run_and_writes_an_issue():
    text = (ROOT / ".github/workflows/freshness-watchdog.yml").read_text(encoding="utf-8")
    assert "schedule:" in text and "issues: write" in text
    assert "freshness_watchdog.py" in text
    assert "FEED_MAX" not in text  # the hours live in the script, next to the 26h gate
