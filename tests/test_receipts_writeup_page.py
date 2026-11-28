"""P29 Receipts write-up: tallies come from the index at build time; no personal names."""
from __future__ import annotations

import hashlib
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_seo_pages as gen
import receipts_page
import receipts_writeup_page


def _source_tests():
    source = (ROOT / "data/receipts-index.json").read_bytes()
    assert hashlib.sha256(source).hexdigest() == receipts_page.SOURCE_SHA256
    return receipts_page.build(source)["tests"]


def test_figures_match_live_index_and_are_not_constants():
    tests = _source_tests()
    fig = receipts_writeup_page.figures(tests, receipts_writeup_page.discover_case_pages(ROOT))
    assert fig["total"] == len(tests)
    assert fig["counts"]["broken"] == sum(1 for t in tests if t["verdict"] == "broken")
    assert fig["counts"]["works"] == sum(1 for t in tests if t["verdict"] == "works")
    assert fig["counts"]["works_with_caveats"] == sum(1 for t in tests if t["verdict"] == "works_with_caveats")
    assert fig["counts"]["deferred"] == sum(1 for t in tests if t["verdict"] == "deferred")
    assert sum(fig["counts"].values()) == fig["total"]
    assert fig["dates"] == sorted({t["tested_at"] for t in tests})
    assert fig["content_day"] == max(t["tested_at"] for t in tests)
    # 29–31 would imply a 30 October record that the index does not have.
    assert "2026-10-30" not in fig["dates"]
    assert fig["date_list"] == receipts_writeup_page.format_date_list(fig["dates"])
    assert "30 October" not in fig["date_list"]

    reduced = [t for t in tests if t["verdict"] != "broken"]
    fig2 = receipts_writeup_page.figures(reduced, [])
    assert fig2["counts"].get("broken", 0) == 0
    assert fig2["total"] == fig["total"] - fig["counts"]["broken"]
    assert fig2["broken"] == []


def test_published_page_uses_computed_tally_and_links():
    tests = _source_tests()
    fig = receipts_writeup_page.figures(tests, receipts_writeup_page.discover_case_pages(ROOT))
    page = (ROOT / "receipts/write-up/index.html").read_text(encoding="utf-8")
    assert "computed from the Receipts index" in page
    assert fig["date_list"] in page
    assert "30 October" not in page
    assert f"{fig['total']} MCP servers" in page or f"tested {fig['total']} MCP servers" in page
    for key, label in receipts_writeup_page.VERDICT_LABELS:
        assert label in page
        assert f"<code>{key}</code>" in page
        assert f"<td>{fig['counts'].get(key, 0)}</td>" in page
    assert f"<td>{fig['total']}</td>" in page
    assert f"{fig['counts'].get('broken', 0)} of {fig['total']} records" in page
    for row in fig["broken"]:
        assert f"id=\"broken-{row['id']}\"" in page
        assert html.escape(receipts_page.scrub_personal(row["headline"])) in page
        assert f"/receipts/#test-{row['id']}" in page
    assert 'href="https://thelanternworks.com/receipts/"' in page
    for c in fig["cases"]:
        assert f"/receipts/{c['slug']}/" in page
    # Credit and privacy.
    assert "Lantern Works" in page
    assert "Frosty" not in page
    assert "Condor" not in page
    assert "Connor" not in page
    assert "connormatthew" not in page.lower()
    assert "<!-- brand -->" in page
    assert '<link rel="canonical" href="https://thelanternworks.com/receipts/write-up/" />' in page


def test_sitemap_uses_content_date_lastmod():
    tests = _source_tests()
    expected = max(t["tested_at"] for t in tests)
    assert receipts_writeup_page.content_day_from_root(ROOT) == expected
    loc = "https://thelanternworks.com/receipts/write-up/"
    assert gen.sitemap_lastmod_for_loc(loc) == expected
    sm = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    block = re.search(
        r"<url>\s*<loc>https://thelanternworks.com/receipts/write-up/</loc>\s*(?:<lastmod>(.*?)</lastmod>)?",
        sm,
    )
    assert block, "write-up missing from sitemap.xml"
    assert block.group(1) == expected
    # Other receipts URLs keep their own lastmod rule; the index must still be listed.
    assert re.search(r"<loc>https://thelanternworks.com/receipts/</loc>", sm)


def test_writeup_script_does_not_hardcode_live_counts():
    src = (ROOT / "scripts/receipts_writeup_page.py").read_text(encoding="utf-8")
    tests = _source_tests()
    counts = {v: sum(1 for t in tests if t["verdict"] == v) for v in {t["verdict"] for t in tests}}
    # Live totals must come from the data, not from literals in the generator.
    assert str(len(tests)) not in src
    for n in counts.values():
        assert str(n) not in re.findall(r"\b\d+\b", src) or str(n) not in src
    for n in counts.values():
        assert not re.search(rf"\b{n}\b", src), f"generator hardcodes count {n}"


def test_llms_and_changelog_point_at_the_writeup():
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "https://thelanternworks.com/receipts/write-up/" in llms
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "/receipts/write-up/" in log
    assert "P29" in log
