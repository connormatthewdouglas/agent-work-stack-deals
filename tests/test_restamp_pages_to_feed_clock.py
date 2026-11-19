"""Feed-clock restamp: clock-only drift is restamped; real drift is left alone.

No live network. Clocks are taken from the committed feed or injected fixtures,
never from the wall clock.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_generated_pages as chk  # noqa: E402
import restamp_pages_to_feed_clock as restamp  # noqa: E402


def _worktree(path: Path) -> None:
    subprocess.check_call(
        ["git", "-C", str(ROOT), "worktree", "add", "--detach", "--quiet", str(path), "HEAD"],
        stdout=subprocess.DEVNULL,
    )


def _remove(path: Path) -> None:
    subprocess.call(
        ["git", "-C", str(ROOT), "worktree", "remove", "--force", str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _feed_stamp(root: Path) -> str:
    return json.loads((root / "api" / "v1" / "gpu-prices.json").read_text())["feed_updated_at"]


def _html_clock(iso: str) -> str:
    """2026-11-19T01:47:16Z -> 2026-11-19 01:47:16 UTC (page meta format)."""
    stamp = iso.replace("Z", "").replace("+00:00", "").replace("T", " ")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", stamp):
        return stamp + " UTC"
    return stamp + " UTC"


def test_diff_line_parser_strips_trailing_differ(tmp_path, monkeypatch):
    """diff -rq suffixes every pair with ' differ'; the parser must not keep that word in the path."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir(); dest.mkdir()
    a = src / "page.html"
    b = dest / "page.html"
    a.write_text("feed_updated_at=2026-11-19 00:57:48 UTC $0.44")
    b.write_text("feed_updated_at=2026-11-19 01:47:16 UTC $0.44")
    line = f"Files {a} and {b} differ"
    monkeypatch.setattr(chk, "_diff_names", lambda s, d: [line])
    pairs = restamp._diff_files(src, dest)
    assert pairs == [(a, b)]
    assert restamp.only_clock_display_differs(a, b)


def test_clock_noise_keeps_prices_quotes_and_last_verified():
    html = (
        'Feed timestamp: <code>feed_updated_at=2026-11-19 00:57:48 UTC</code>. '
        'Prices verified through <code>2026-11-19 00:57:04 UTC</code>. '
        '<td>$0.44</td><td><strong class="stale-label">Stale</strong> · '
        'last verified 2026-10-29 23:14:39 UTC · read 20d ago</td>'
        '<blockquote><p>RTX 4090 from $0.44/hr</p></blockquote>'
        '<time datetime="2026-11-18T19:01:10Z">read 6h ago</time>'
    )
    later = html.replace("00:57:48 UTC", "01:47:16 UTC").replace("00:57:04 UTC", "01:46:45 UTC")
    later = later.replace("read 20d ago", "read 21d ago").replace("read 6h ago", "read 7h ago")
    assert restamp._clock_noise_text(html) == restamp._clock_noise_text(later)
    # A price or last-verified change is not clock noise.
    tampered = later.replace("$0.44", "$9.99")
    assert restamp._clock_noise_text(html) != restamp._clock_noise_text(tampered)
    tampered = later.replace("last verified 2026-10-29 23:14:39 UTC", "last verified 2026-11-01 00:00:00 UTC")
    assert restamp._clock_noise_text(html) != restamp._clock_noise_text(tampered)
    tampered = later.replace("RTX 4090 from $0.44/hr", "TAMPERED QUOTE")
    assert restamp._clock_noise_text(html) != restamp._clock_noise_text(tampered)


def test_matching_tree_is_match_and_noop(tmp_path):
    dest = tmp_path / "match"
    _worktree(dest)
    try:
        os.environ["LW_AVAIL_NOW"] = _feed_stamp(dest)
        assert restamp.classify(dest) == restamp.MATCH
        before = (dest / "reports" / "vendors" / "beam" / "index.html").read_text()
        assert restamp.restamp(dest) == 0
        assert (dest / "reports" / "vendors" / "beam" / "index.html").read_text() == before
    finally:
        _remove(dest)


def test_feed_timestamp_only_is_clock_stale_and_is_restamped(tmp_path):
    dest = tmp_path / "clock"
    _worktree(dest)
    try:
        page = dest / "reports" / "vendors" / "beam" / "index.html"
        text = page.read_text(encoding="utf-8")
        stamp = _feed_stamp(dest)
        html_now = _html_clock(stamp)
        # A prior generate clock, not wall clock.
        html_old = "2026-11-19 00:57:48 UTC"
        assert html_now != html_old
        assert html_now in text
        page.write_text(text.replace(html_now, html_old), encoding="utf-8")
        os.environ["LW_AVAIL_NOW"] = stamp
        assert restamp.classify(dest) == restamp.CLOCK_STALE
        assert restamp.restamp(dest) == 0
        updated = page.read_text(encoding="utf-8")
        assert html_now in updated
        assert html_old not in updated
        assert "$0.44" in updated
        assert "last verified 2026-10-29 23:14:39 UTC" in updated
        assert chk.check(dest) == 0
    finally:
        _remove(dest)


def test_hand_edited_title_is_real_drift_and_not_restamped(tmp_path):
    dest = tmp_path / "tamper"
    _worktree(dest)
    try:
        page = dest / "reports" / "vendors" / "beam" / "index.html"
        text = page.read_text(encoding="utf-8")
        page.write_text(text.replace("Beam GPU price sample report", "TAMPERED TITLE", 1), encoding="utf-8")
        os.environ["LW_AVAIL_NOW"] = _feed_stamp(dest)
        assert restamp.classify(dest) == restamp.REAL_DRIFT
        assert restamp.restamp(dest) == 1
        assert "TAMPERED TITLE" in page.read_text(encoding="utf-8")
    finally:
        _remove(dest)


def test_validate_and_deploy_restamps_before_pytest_and_regenerates_before_deploy():
    text = (ROOT / ".github" / "workflows" / "validate-and-deploy.yml").read_text(encoding="utf-8")
    tests_at = text.find("\n  tests:")
    deploy_at = text.find("\n  deploy:")
    assert 0 <= tests_at < deploy_at
    tests = text[tests_at:deploy_at]
    pytest_at = tests.find("python3 -m pytest")
    restamp_at = tests.find("scripts/restamp_pages_to_feed_clock.py")
    assert 0 <= restamp_at < pytest_at, "restamp must run before pytest in the tests job"
    deploy = text[deploy_at:]
    jekyll_at = deploy.find("jekyll-build-pages")
    gen_at = deploy.find("scripts/generate_seo_pages.py")
    pin_at = deploy.find("LW_AVAIL_NOW")
    assert 0 <= pin_at < gen_at < jekyll_at, (
        "deploy must pinned-generate at feed_updated_at before the Pages build"
    )
    assert "json.load(open('api/v1/gpu-prices.json'))['feed_updated_at']" in deploy[pin_at:gen_at + 80]
