"""Sturdiness pass (Relay, 2026-11-17): stale data warns and goes to the freshness-watchdog issue instead of
failing PRs; #816: a later-commit hosted hotfix is not a build mismatch, a real mismatch still is."""
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import freshness_watchdog as W  # noqa: E402

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
FEED = {
    "feed_updated_at": "2026-11-09T10:00:00Z",
    "availability_collected_at": "2026-11-09T11:30:00Z",
    "rates": [{"advertiser": "RunPod", "gpu": "H100", "tier": "On-demand", "verified_at": "2026-11-09T08:00:00Z",
               "checked_at": "2026-11-09T08:00:00Z"}],
    "held_stale": [],
}
VERSION_SHA = "21684cc5ca768c928e4ecc1d3c957b71c091efbe"
HOTFIX = "dc95666428102c7b66e115c767062bd8646c2786"


def _git(*a: str) -> str:
    return subprocess.check_output(["git", *a], cwd=ROOT, text=True).strip()


def test_later_commit_hotfix_passes_and_real_mismatch_still_fails():
    hosted = {"version": "0.6.2", "build": HOTFIX}
    ok = W.evaluate(FEED, hosted, now=NOW, expected_version="0.6.2", expected_build=VERSION_SHA,
                    deployed_ok=lambda b, v: (b, v) == (HOTFIX, VERSION_SHA))
    assert ok == []
    bad = W.evaluate(FEED, hosted, now=NOW, expected_version="0.6.2", expected_build=VERSION_SHA,
                     deployed_ok=lambda b, v: False)
    assert len(bad) == 1 and bad[0].startswith("hosted MCP build") and "later commit on main" in bad[0]
    # garbage build never reaches the ancestry check
    junk = W.evaluate(FEED, {"version": "0.6.2", "build": "unknown"}, now=NOW, expected_version="0.6.2",
                      expected_build=VERSION_SHA, deployed_ok=lambda b, v: True)
    assert any("unresolvable" in p for p in junk)


def test_deployed_descends_uses_git_ancestry():
    try:
        version, sha = W.expected_from_checkout()
    except Exception:  # shallow clone without the version commit
        return
    head = _git("rev-parse", "HEAD")
    assert W.deployed_descends(head, sha)                       # main HEAD descends from the version commit
    assert W.deployed_descends(sha, sha)
    parents = _git("rev-list", "--parents", "-n", "1", sha).split()[1:]
    if parents:
        assert not W.deployed_descends(parents[0], sha)        # a build OLDER than the version commit alarms
    assert not W.deployed_descends("deadbeefdeadbeef", sha)     # unknown commit alarms
    assert not W.deployed_descends("", sha)


def test_ci_stale_mode_never_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_REPO", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    notes = tmp_path / "stale-notes.txt"
    assert W.main(["--ci-stale", str(notes)]) == 0                 # missing file
    notes.write_text("latest-scout-import: Scout snapshot x is 11.8h old (> 8h); refusing to import\n")
    assert W.main(["--ci-stale", str(notes), "--dry-run"]) == 0


def test_scout_import_stale_pattern_matches_the_importer_message():
    sh = (ROOT / "scripts" / "check_latest_scout_import.sh").read_text(encoding="utf-8")
    pat = re.search(r"grep -Eq '(.+?)' \"\$T/import.log\"", sh).group(1).replace("\\(", r"\(").replace("\\)", r"\)")
    msg = "Scout snapshot 2026-11-16T18:47:50Z is 11.8h old (> 8h); refusing to import"
    assert re.search(pat, msg)
    assert not re.search(pat, "Scout v3.2 snapshot refused: no manifest sha256 to verify it (set LW_SCOUT_MANIFESTS)")
    src = (ROOT / "scripts" / "import_scout_availability.py").read_text(encoding="utf-8")
    assert "refusing to import" in src  # importer still emits this wording


def test_workflow_routes_staleness_and_pins_the_test_clock():
    wf = (ROOT / ".github" / "workflows" / "validate-and-deploy.yml").read_text(encoding="utf-8")
    assert wf.count('freshness_watchdog.py --ci-stale "$RUNNER_TEMP/stale-notes.txt"') == 2
    assert 'LW_STALE_NOTES="$RUNNER_TEMP/stale-notes.txt" sh scripts/check_latest_scout_import.sh' in wf
    assert "LW_AVAIL_NOW=" in wf.split("pytest (entire tests/ directory", 1)[1].split("- name:", 1)[0]
