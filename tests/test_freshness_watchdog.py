"""A4: outside watchdog. 26h feed and 48h row bars stay put; availability is 8h (AVAIL_MAX_AGE_H)."""
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
FRESH_STATS = {"generated_at": "2026-11-08T12:00:00Z"}


def _eval(feed=FRESH_FEED, hosted=HOSTED_OK, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("expected_version", "0.6.2")
    kw.setdefault("expected_build", EXPECT)
    return W.evaluate(feed, hosted, **kw)


def test_thresholds_are_the_existing_bars():
    assert W.FEED_MAX_HOURS == 26
    assert W.AVAIL_MAX_HOURS == 8
    assert W.ROW_MAX_HOURS == 48
    assert W.STATS_MAX_HOURS == 192
    assert W.WORKFLOW_SUCCESS_MAX_HOURS == {
        "gpu-refresh.yml": 30,
        "scout-import.yml": 10,
        "lium-collect.yml": 6,
    }
    assert W.FETCH_ATTEMPTS == 3
    assert W.FETCH_TIMEOUT_SEC == 30
    assert W.FETCH_BACKOFF_SEC == (1, 2)
    assert W.GH_TIMEOUT_SEC == 60


def test_stale_live_surfaces():
    feed = {"feed_updated_at": "2026-11-06T06:50:00Z", "availability_collected_at": "2026-11-06T02:51:00Z",
            "rates": [{"advertiser": "RunPod", "gpu": "H100", "tier": "On-demand", "verified_at": "2026-11-06T06:50:00Z"}],
            "held_stale": []}
    hosted = {"version": "0.6.0", "build": "2767db56"}
    probs = _eval(feed, hosted)
    assert any(p.startswith("feed_updated_at") and "26h" in p for p in probs)
    assert any(p.startswith("availability_collected_at") and "8h" in p for p in probs)
    assert any("0.6.0" in p and "0.6.2" in p for p in probs)
    assert any("48h" in p for p in probs)


def test_availability_five_hours_is_fresh_and_nine_hours_is_not():
    # 5h would have failed the old 4h bar; 8h matches AVAIL_MAX_AGE_H.
    fresh = {**FRESH_FEED, "availability_collected_at": "2026-11-09T07:00:00Z"}
    assert _eval(fresh) == []
    stale = {**FRESH_FEED, "availability_collected_at": "2026-11-09T02:30:00Z"}
    probs = _eval(stale)
    assert any(p.startswith("availability_collected_at") and "8h" in p for p in probs)


def test_matching_build_is_fresh_and_a_different_build_is_not():
    assert _eval() == []
    probs = _eval(hosted={"version": "0.6.2", "build": "2767db56"})
    assert len(probs) == 1 and probs[0].startswith("hosted MCP build")


def test_unresolvable_or_short_build_fails():
    for bad in ("", None, "abc", "123456", "not-a-sha", "unknown"):
        probs = _eval(hosted={"version": "0.6.2", "build": bad})
        assert probs and "unresolvable" in probs[0], bad
    probs = _eval(expected_build="")
    assert any("expected build is unresolvable" in p for p in probs)
    assert not W.builds_match("21684c", EXPECT)  # 6 hex digits is not enough
    assert W.builds_match("21684cc", EXPECT)


def test_empty_rates_all_held_future_and_shrink(monkeypatch):
    monkeypatch.setattr(W, "_owner_names", lambda: ["Hyperstack", "Verda"])
    empty = {**FRESH_FEED, "rates": [], "held_stale": [
        {"vendor": "Hyperstack", "checked_at": "2026-11-01T00:00:00Z", "reason": "owner hold"}]}
    probs = _eval(empty, committed_rate_count=100)
    assert any("rates list is empty" in p for p in probs)
    assert any("all tracked rows are held" in p for p in probs)
    assert any("shrank from 100 to 0" in p for p in probs)
    holds = W.hold_lines(empty, NOW)
    assert holds and holds[0].startswith("held owner-held Hyperstack") and "h" in holds[0]
    future = {**FRESH_FEED, "feed_updated_at": "2026-11-10T00:00:00Z",
              "rates": [{"advertiser": "RunPod", "gpu": "H100", "tier": "On-demand", "verified_at": "2026-11-10T00:00:00Z"}]}
    fprobs = _eval(future)
    assert any("in the future" in p for p in fprobs)
    shrunk = {**FRESH_FEED, "rates": FRESH_FEED["rates"] * 1}
    assert any("shrank from 10 to 1" in p for p in _eval(shrunk, committed_rate_count=10))


def test_stats_generated_at():
    assert _eval(stats=FRESH_STATS) == []
    # NOW is 2026-11-09T12:00Z; 193h earlier is 2026-11-01T11:00Z (just over 192h).
    stale = {"generated_at": "2026-11-01T11:00:00Z"}
    probs = _eval(stats=stale)
    assert any("stats generated_at" in p and "192h" in p for p in probs)
    assert any("missing" in p for p in _eval(stats={}))
    assert any("in the future" in p for p in _eval(stats={"generated_at": "2026-11-10T00:00:00Z"}))
    # 191h is still under the bar.
    under = {"generated_at": "2026-11-01T13:00:00Z"}
    assert _eval(stats=under) == []


def test_notes_for_workflow_ignores_in_progress_and_age_gates_success():
    in_prog = {"status": "in_progress", "conclusion": None, "url": "https://example.test/1",
               "updatedAt": "2026-11-09T11:50:00Z"}
    queued = {"status": "queued", "conclusion": None, "url": "https://example.test/2",
              "updatedAt": "2026-11-09T11:55:00Z"}
    failed = {"status": "completed", "conclusion": "failure", "url": "https://example.test/fail",
              "updatedAt": "2026-11-09T11:00:00Z"}
    success_fresh = {"status": "completed", "conclusion": "success", "url": "https://example.test/ok",
                     "updatedAt": "2026-11-09T10:00:00Z"}
    success_old = {"status": "completed", "conclusion": "success", "url": "https://example.test/old",
                   "updatedAt": "2026-11-07T12:00:00Z"}

    assert W.notes_for_workflow("gpu-refresh.yml", [in_prog, queued], NOW, 30) == [
        "gpu-refresh.yml: no completed runs"]

    notes = W.notes_for_workflow("gpu-refresh.yml", [in_prog, failed, success_fresh], NOW, 30)
    assert any("conclusion failure" in n and "example.test/fail" in n for n in notes)
    assert not any("last success is" in n for n in notes)

    notes = W.notes_for_workflow("gpu-refresh.yml", [success_old], NOW, 30)
    assert any("last success is" in n and "30h" in n and "example.test/old" in n for n in notes)

    success_12h = {"status": "completed", "conclusion": "success", "url": "https://example.test/s",
                   "updatedAt": "2026-11-09T00:00:00Z"}
    notes = W.notes_for_workflow("scout-import.yml", [success_12h], NOW, 10)
    assert any("last success is" in n and "10h" in n for n in notes)

    success_5h = {"status": "completed", "conclusion": "success", "url": "https://example.test/l",
                  "updatedAt": "2026-11-09T07:00:00Z"}
    assert W.notes_for_workflow("lium-collect.yml", [success_5h], NOW, 6) == []

    notes = W.notes_for_workflow("lium-collect.yml", [queued, failed], NOW, 6)
    assert any("conclusion failure" in n for n in notes)
    assert any("no successful run in the listed window (limit 6h)" in n for n in notes)


def test_issue_title_and_body_separate_collector_from_data():
    assert W.issue_title(["feed_updated_at is 30.0h old (limit 26h)"], []) == W.TITLE_DATA
    assert W.issue_title([], ["gpu-refresh.yml: conclusion failure (https://example.test/r)"]) == W.TITLE_COLLECTOR
    assert W.issue_title(["x"], ["y"]) == W.TITLE_BOTH
    body = W.format_body(["feed old"], ["gpu-refresh failed"], ["held X: 3.0h (reason)"], "https://example.test/run")
    assert "Data freshness:" in body and "Collector runs:" in body
    assert body.index("Data freshness:") < body.index("feed old") < body.index("Collector runs:")
    assert "Held rows:" in body and "held X" in body
    assert "Run: https://example.test/run" in body
    collector_only = W.format_body([], ["lium-collect.yml: last success is 12.0h old (limit 6h)"], [], "")
    assert "Data freshness:" not in collector_only and "Collector runs:" in collector_only
    assert "the live feed is stale" not in collector_only.lower() or "Collector runs:" in collector_only


def test_get_json_retries_then_succeeds(monkeypatch):
    import io
    sleeps: list[float] = []
    monkeypatch.setattr(W.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        assert timeout == 30
        if calls["n"] < 3:
            raise TimeoutError("blip")

        class Resp:
            def __enter__(self):
                return io.BytesIO(b'{"ok": true}')

            def __exit__(self, *a):
                return None

        return Resp()

    monkeypatch.setattr(W.urllib.request, "urlopen", fake_urlopen)
    assert W._get_json("https://example.test/x") == {"ok": True}
    assert calls["n"] == 3
    assert sleeps == [1, 2]


def test_get_json_fails_after_three_tries(monkeypatch):
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    n = {"c": 0}

    def fake_urlopen(req, timeout=None):
        n["c"] += 1
        raise TimeoutError("down")

    monkeypatch.setattr(W.urllib.request, "urlopen", fake_urlopen)
    try:
        W._get_json("https://example.test/x")
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected TimeoutError")
    assert n["c"] == 3


def test_gh_calls_use_timeout(monkeypatch):
    seen: dict = {}

    def fake_co(cmd, text=True, timeout=None):
        seen["output"] = timeout
        return "1\n"

    def fake_cc(cmd, timeout=None):
        seen["call"] = timeout
        return 0

    monkeypatch.setattr(W.subprocess, "check_output", fake_co)
    monkeypatch.setattr(W.subprocess, "check_call", fake_cc)
    assert W._gh("issue", "list") == "1"
    W._gh_ok("issue", "comment", "1")
    assert seen["output"] == 60 and seen["call"] == 60


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
    assert W.FEED_MAX_HOURS == 26 and W.AVAIL_MAX_HOURS == 8
