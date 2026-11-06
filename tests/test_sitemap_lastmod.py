"""T121: sitemap lastmod must be honest per URL (no global stale stamp)."""
from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import date
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


def test_sitemap_lastmod_helper_varies_and_skips_future():
    entries = _entries()
    assert entries, "sitemap.xml missing entries"
    today = date.today().isoformat()
    for loc, lm in entries:
        if lm is None:
            continue
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", lm), (loc, lm)
        assert lm <= today, f"future lastmod {lm} on {loc}"
    # Helper agrees with committed sitemap for a sample of URLs.
    for loc, lm in entries[:20]:
        got = gen.sitemap_lastmod_for_loc(loc)
        assert got == lm, (loc, lm, got)


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
