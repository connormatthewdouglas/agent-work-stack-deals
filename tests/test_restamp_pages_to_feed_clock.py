"""Feed-clock restamp: clock-only drift is restamped; real drift is left alone.

No live network. Clocks are taken from injected fixtures, never from the
wall clock or the live checkout. classify/restamp are exercised against a
tmp fixture tree; a live HEAD worktree is not a stable MATCH after a
collector or a concurrent import (lium-collect run 45618756131).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import restamp_pages_to_feed_clock as restamp  # noqa: E402

# Frozen fixture clock. Not read from the live feed or datetime.now().
FROZEN_FEED = "2026-11-19T01:47:16Z"
HTML_NOW = "2026-11-19 01:47:16 UTC"
HTML_OLD = "2026-11-19 00:57:48 UTC"
TITLE = "Beam GPU price sample report"
PRICE = "$0.44"
LAST_VERIFIED = "last verified 2026-10-29 23:14:39 UTC"


def _page(*, clock: str, title: str = TITLE) -> str:
    return (
        f"<!doctype html><title>{title}</title>"
        f"Feed timestamp: <code>feed_updated_at={clock}</code>. "
        f"Prices verified through <code>{clock}</code>. "
        f"<td>{PRICE}</td><td>{LAST_VERIFIED} · read 20d ago</td>"
        f"<blockquote><p>RTX 4090 from {PRICE}/hr</p></blockquote>"
    )


def _write_tree(root: Path, *, clock: str, title: str = TITLE) -> Path:
    prices = root / "api" / "v1"
    prices.mkdir(parents=True, exist_ok=True)
    (prices / "gpu-prices.json").write_text(
        json.dumps({"feed_updated_at": FROZEN_FEED}, indent=2) + "\n",
        encoding="utf-8",
    )
    page = root / "reports" / "vendors" / "beam" / "index.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(_page(clock=clock, title=title), encoding="utf-8")
    return page


def _isolate_from_live_tree(tmp_path: Path, monkeypatch):
    """Point classify/restamp at a fixture regenerate, not live HEAD or wall clock."""
    generated = tmp_path / "generated"
    _write_tree(generated, clock=HTML_NOW)

    def _regen(_root: Path) -> Path:
        dest = Path(tempfile.mkdtemp(prefix="lw-restamp-fixture-"))
        shutil.copytree(generated, dest, dirs_exist_ok=True)
        return dest

    def _generate(root: Path) -> None:
        for path in generated.rglob("*"):
            if path.is_file():
                target = root / path.relative_to(generated)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())

    monkeypatch.setattr(restamp, "_regen_copy", _regen)
    monkeypatch.setattr(restamp, "_generate_in_place", _generate)
    monkeypatch.setenv("LW_AVAIL_NOW", FROZEN_FEED)
    return generated


def test_diff_line_parser_strips_trailing_differ(tmp_path, monkeypatch):
    """diff -rq suffixes every pair with ' differ'; the parser must not keep that word in the path."""
    import check_generated_pages as chk

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


def test_matching_tree_is_match_and_noop(tmp_path, monkeypatch):
    _isolate_from_live_tree(tmp_path, monkeypatch)
    dest = tmp_path / "match"
    page = _write_tree(dest, clock=HTML_NOW)
    before = page.read_text(encoding="utf-8")
    assert restamp.classify(dest) == restamp.MATCH
    assert restamp.restamp(dest) == 0
    assert page.read_text(encoding="utf-8") == before


def test_feed_timestamp_only_is_clock_stale_and_is_restamped(tmp_path, monkeypatch):
    generated = _isolate_from_live_tree(tmp_path, monkeypatch)
    dest = tmp_path / "clock"
    page = _write_tree(dest, clock=HTML_OLD)
    text = page.read_text(encoding="utf-8")
    assert HTML_NOW not in text
    assert HTML_OLD in text
    assert restamp.classify(dest) == restamp.CLOCK_STALE
    assert restamp.restamp(dest) == 0
    updated = page.read_text(encoding="utf-8")
    assert HTML_NOW in updated
    assert HTML_OLD not in updated
    assert PRICE in updated
    assert LAST_VERIFIED in updated
    # Restamp must leave the tree identical to the pinned generate fixture.
    assert updated == (generated / "reports" / "vendors" / "beam" / "index.html").read_text(
        encoding="utf-8"
    )


def test_hand_edited_title_is_real_drift_and_not_restamped(tmp_path, monkeypatch):
    _isolate_from_live_tree(tmp_path, monkeypatch)
    dest = tmp_path / "tamper"
    page = _write_tree(dest, clock=HTML_NOW, title="TAMPERED TITLE")
    assert restamp.classify(dest) == restamp.REAL_DRIFT
    assert restamp.restamp(dest) == 1
    assert "TAMPERED TITLE" in page.read_text(encoding="utf-8")
    assert TITLE not in page.read_text(encoding="utf-8")


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
