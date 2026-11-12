"""T121: sitemap lastmod must be honest per URL (no global stale stamp)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_seo_pages as gen  # noqa: E402

# The monoculture date Pax found on every URL (audit-t119-t121-2026-11-06).
STALE_HARDCODED = "2026-10-23"


def _entries() -> list[tuple[str, str | None]]:
    sm = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    out: list[tuple[str, str | None]] = []
    for m in re.finditer(r"<url>(.*?)</url>", sm, re.S):
        block = m.group(1)
        loc_m = re.search(r"<loc>(.*?)</loc>", block)
        assert loc_m, block[:120]
        lm_m = re.search(r"<lastmod>(.*?)</lastmod>", block)
        out.append((loc_m.group(1), lm_m.group(1) if lm_m else None))
    return out


def test_sitemap_not_all_stale_hardcoded_lastmod():
    mods = [lm for _, lm in _entries() if lm]
    # All-omitted is allowed; a single global STALE_HARDCODED stamp is not.
    assert set(mods) != {STALE_HARDCODED}, (
        "T121 regression: every sitemap lastmod is the stale hardcoded "
        f"{STALE_HARDCODED}"
    )


def test_sitemap_lastmods_not_identical_monoculture():
    entries = _entries()
    mods = [lm for _, lm in entries if lm]
    if not mods:
        return  # deliberate omission of every lastmod is honest
    unique = set(mods)
    assert len(unique) > 1, (
        "T121: expected per-page lastmod variety, got one date for all "
        f"URLs: {unique}"
    )


def test_sitemap_lastmods_not_older_than_stale_as_only_value():
    """Fail if the only lastmod present is older than / equal to the known stale stamp monoculture."""
    mods = [lm for _, lm in _entries() if lm]
    if not mods:
        return
    # A monoculture of dates all <= STALE_HARDCODED means the generator is
    # still not tracking real updates (site changed daily through Nov 2026).
    if len(set(mods)) == 1:
        only = next(iter(set(mods)))
        assert only > STALE_HARDCODED, (
            f"T121: sole lastmod {only} is older than or equal to stale "
            f"hardcoded {STALE_HARDCODED}"
        )


def test_sitemap_write_path_does_not_use_lastmod_constant():
    src = (ROOT / "scripts" / "generate_seo_pages.py").read_text(encoding="utf-8")
    # The sitemap writer must not interpolate the display-only LASTMOD constant.
    assert "lastmod>{LASTMOD}" not in src
    assert "lastmod>{LASTMOD}</lastmod>" not in src
    assert "sitemap_lastmod_for_loc" in src


def test_changes_lastmod_follows_data_date_not_the_commit(monkeypatch):
    """A refresh dates the changes feed today, then the gate runs before that data is committed.

    The last commit of the generator stays on the previous day. Lastmod for the changes JSON and
    gpu/changes.xml must follow the feed date that was just written, not that commit.
    """
    monkeypatch.setattr(gen, "_git_commit_date", lambda *_a, **_k: "2026-11-06")
    gen._SITEMAP_GIT_DATE_CACHE.clear()
    changes = ROOT / "api" / "v1" / "gpu-price-changes.json"
    sitemap = ROOT / "sitemap.xml"
    original_changes = changes.read_text(encoding="utf-8")
    original_sitemap = sitemap.read_text(encoding="utf-8")
    doc = json.loads(original_changes)
    doc["date"] = "2026-11-09"
    changes.write_text(json.dumps(doc), encoding="utf-8")
    try:
        for loc in (
            "https://thelanternworks.com/api/v1/gpu-price-changes.json",
            "https://thelanternworks.com/api/v1/gpu-price-changes.xml",
            "https://thelanternworks.com/gpu/changes.xml",
            "https://thelanternworks.com/gpu/changes/",
        ):
            assert gen.sitemap_lastmod_for_loc(loc) == "2026-11-09", loc
        gen.rewrite_sitemap_lastmods()
        text = sitemap.read_text(encoding="utf-8")
        for loc in (
            "https://thelanternworks.com/api/v1/gpu-price-changes.json",
            "https://thelanternworks.com/gpu/changes.xml",
        ):
            block = text.split(f"<loc>{loc}</loc>", 1)[1].split("</url>", 1)[0]
            assert "<lastmod>2026-11-09</lastmod>" in block, loc
            assert gen.sitemap_lastmod_for_loc(loc) == "2026-11-09"
    finally:
        changes.write_text(original_changes, encoding="utf-8")
        sitemap.write_text(original_sitemap, encoding="utf-8")
        gen._SITEMAP_GIT_DATE_CACHE.clear()


def test_changes_feed_is_written_before_the_sitemap():
    src = (ROOT / "scripts" / "generate_seo_pages.py").read_text(encoding="utf-8")
    main = src.split("def main", 1)[1]
    assert main.index("gpu_changes_feed.write") < main.index("write_sitemap(")


def _reset_lastmod_caches() -> None:
    gen._SITEMAP_GIT_DATE_CACHE.clear()
    gen._SITEMAP_DEAL_DATES = None
    gen._SITEMAP_DEALS_FEED_DAY = False
    gen._SITEMAP_GPU_FEED_DAY = False


def test_homepage_lastmod_follows_feed_not_script_commit_or_clock(monkeypatch):
    """Homepage lastmod is the GPU/deals/changes content day, not a script squash-merge date or the wall clock.

    #208 merged scripts/home_page.py at 19:38 America/New_York (00:38 UTC next day).
    Using that git date made the helper emit the next UTC day and fail this file's
    committed-sitemap check after midnight even though feed_updated_at had not moved.
    """
    _reset_lastmod_caches()
    expected = max(gen._homepage_content_days())
    tomorrow = "2099-01-02"
    original_git = gen._git_commit_date

    def fake_git(rel):
        # Generator and data-file git dates look like the next UTC day (late ET squash merge).
        # CHANGELOG.md is the changelog content source and is allowed through.
        key = str(rel).replace('\\', '/')
        if key == 'CHANGELOG.md':
            return original_git(rel)
        return tomorrow

    monkeypatch.setattr(gen, "_git_commit_date", fake_git)
    # A faked next-day clock must not move homepage lastmod either.
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2099, 1, 2, 12, 0, 0, tzinfo=tz or timezone.utc)

        @classmethod
        def utcnow(cls):
            return datetime(2099, 1, 2, 12, 0, 0)

    monkeypatch.setattr(gen, "datetime", _FrozenDateTime)
    _reset_lastmod_caches()
    got = gen.sitemap_lastmod_for_loc("https://thelanternworks.com/")
    assert got == expected
    assert got != tomorrow
    committed = dict(_entries())["https://thelanternworks.com/"]
    assert got == committed, (got, committed, expected)
    # Deal-hub lastmods also ignore the generator script's squash-merge date.
    deals_day = gen._deals_feed_day()
    for loc in (
        "https://thelanternworks.com/deals/",
        "https://thelanternworks.com/categories/ai-agents/",
        "https://thelanternworks.com/guides/cheap-gpu-week/",
        "https://thelanternworks.com/for-agents/",
    ):
        assert gen.sitemap_lastmod_for_loc(loc) == deals_day, loc
        assert gen.sitemap_lastmod_for_loc(loc) != tomorrow
    # Changelog follows CHANGELOG.md, not the generator script.
    cl = gen.sitemap_lastmod_for_loc("https://thelanternworks.com/changelog/")
    assert cl == gen._git_commit_date("CHANGELOG.md")
    assert cl != tomorrow
    # The check is still strict: a newer feed date must not be hidden.
    monkeypatch.setattr(gen, "_gpu_feed_day", lambda: "2099-01-02")
    monkeypatch.setattr(gen, "_deals_feed_day", lambda: "2099-01-02")
    monkeypatch.setattr(gen, "_changes_content_day", lambda: "2099-01-02")
    stale = gen.sitemap_lastmod_for_loc("https://thelanternworks.com/")
    assert stale == "2099-01-02"
    assert stale != committed
    _reset_lastmod_caches()


def test_sitemap_lastmod_helper_varies_and_skips_future():

    entries = _entries()
    assert entries, "sitemap.xml missing entries"
    today = datetime.now(timezone.utc).date().isoformat()
    for loc, lm in entries:
        if lm is None:
            continue
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", lm), (loc, lm)
        assert lm <= today, f"future lastmod {lm} on {loc}"
    # Helper agrees with committed sitemap for a sample of URLs.
    for loc, lm in entries[:20]:
        got = gen.sitemap_lastmod_for_loc(loc)
        assert got == lm, (loc, lm, got)


def test_iso_date_and_git_lastmod_are_utc():
    assert gen._iso_date("2026-11-08T22:30:00-05:00") == "2026-11-09"
    assert gen._iso_date("2026-11-08T22:30:00Z") == "2026-11-08"
    assert gen._iso_date("2026-11-08") == "2026-11-08"
    gen._SITEMAP_GIT_DATE_CACHE.clear()
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        got = gen._git_commit_date("README.md")
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()
        gen._SITEMAP_GIT_DATE_CACHE.clear()
    ts = int(subprocess.check_output(["git", "log", "-1", "--format=%ct", "--", "README.md"], cwd=ROOT))
    assert got == datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def test_rewrite_sitemap_lastmods_keeps_url_count_and_fixes_coverage_slash():
    before = [loc for loc, _ in _entries()]
    gen.rewrite_sitemap_lastmods()
    after = _entries()
    assert len(after) == len(before)
    assert [loc for loc, _ in after] == before or all(
        "//" not in loc[len("https://") :] for loc, _ in after
    )
    locs = [loc for loc, _ in after]
    assert "https://thelanternworks.com/coverage/" in locs
    assert "https://thelanternworks.com/coverage//" not in locs
    mods = [lm for _, lm in after if lm]
    assert len(set(mods)) > 1
    counts = Counter(mods)
    assert counts.get(STALE_HARDCODED, 0) < len(mods), (
        "T121: stale hardcoded date still dominates the sitemap"
    )
