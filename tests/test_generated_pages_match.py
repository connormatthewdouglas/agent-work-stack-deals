"""A pinned regenerate must match the pages on disk, and must not touch this checkout.

On a clean tree the pages on disk are the committed ones. A tree that was already
regenerated from the same feed (even if that regeneration is uncommitted) passes.
A hand-edited page fails.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_generated_pages as chk  # noqa: E402


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


def _regenerate(path: Path) -> None:
    stamp = json.loads((path / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))["feed_updated_at"]
    env = os.environ.copy()
    env["LW_AVAIL_NOW"] = stamp
    subprocess.check_call(
        [sys.executable, str(path / "scripts" / "generate_seo_pages.py")],
        cwd=path, env=env, stdout=subprocess.DEVNULL,
    )


def test_committed_pages_match_pinned_generator():
    assert chk.check(ROOT) == 0


def test_restamp_then_regenerate_still_matches(tmp_path):
    """A workflow that only moves a vendor check time, then regenerates, must pass."""
    dest = tmp_path / "restamp"
    _worktree(dest)
    try:
        pricing = dest / "data" / "gpu_pricing" / "civo.json"
        doc = json.loads(pricing.read_text(encoding="utf-8"))
        old = doc["checked_at"]
        doc["checked_at"] = old[:-1] + "1" if old.endswith("0") else old[:-1] + "0"
        assert doc["checked_at"] != old
        pricing.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        _regenerate(dest)
        # Parent LW_AVAIL_NOW (e.g. check_latest_scout_import) must not override dest's feed stamp.
        saved = os.environ.pop("LW_AVAIL_NOW", None)
        try:
            assert chk.check(dest) == 0
        finally:
            if saved is not None:
                os.environ["LW_AVAIL_NOW"] = saved
    finally:
        _remove(dest)


def test_snapshot_price_move_then_one_regenerate_matches(tmp_path):
    """A price refresh moves today's snapshot; ONE regenerate must already match (the "Since" column reads the
    changes feed, so that feed has to be written before the pages that read it)."""
    dest = tmp_path / "snapmove"
    _worktree(dest)
    try:
        snaps = sorted((dest / "data" / "gpu_pricing" / "snapshots").glob("*.json"))
        doc = json.loads(snaps[-1].read_text(encoding="utf-8"))
        row = next(r for r in doc["rows"] if r.get("gpu") == "H100" and r.get("hourly_usd"))
        row["hourly_usd"] = row["price_usd"] = round(row["hourly_usd"] * 1.1, 4)
        snaps[-1].write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        _regenerate(dest)
        saved = os.environ.pop("LW_AVAIL_NOW", None)
        try:
            assert chk.check(dest) == 0
        finally:
            if saved is not None:
                os.environ["LW_AVAIL_NOW"] = saved
    finally:
        _remove(dest)


def test_tampered_page_fails(tmp_path):
    dest = tmp_path / "tamper"
    _worktree(dest)
    try:
        page = dest / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace("H100", "H100-TAMPERED", 1), encoding="utf-8")
        assert chk.check(dest) != 0
    finally:
        _remove(dest)


def test_feed_commit_provenance_lag_passes_but_other_index_edits_fail(tmp_path):
    """feed_commit_for_listing_counts lags on the commit that changes the feed; nothing else may drift."""
    dest = tmp_path / "provenance"
    _worktree(dest)
    try:
        index = dest / "api" / "v1" / "gpu-price-index.json"
        text = index.read_text(encoding="utf-8")
        doc = json.loads(text)
        days = [d for d in doc.get("history", doc.get("days", [])) if isinstance(d, dict) and "feed_commit_for_listing_counts" in d]
        if not days:
            days = [doc]
        days[-1]["feed_commit_for_listing_counts"] = "0" * 40
        index.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        assert chk.check(dest) == 0
        index.write_text(text.replace('"median_usd_per_gpu_hour": ', '"median_usd_per_gpu_hour": 9', 1), encoding="utf-8")
        assert chk.check(dest) != 0
    finally:
        _remove(dest)


def test_sitemap_lastmod_drift_passes_but_url_changes_fail(tmp_path):
    """A squash merge moves git dates behind <lastmod>; URL adds/removals must still fail."""
    import re as _re
    dest = tmp_path / "sitemap"
    _worktree(dest)
    try:
        sm = dest / "sitemap.xml"
        text = sm.read_text(encoding="utf-8")
        sm.write_text(_re.sub(r"<lastmod>[^<]*</lastmod>", "<lastmod>2000-01-01</lastmod>", text), encoding="utf-8")
        assert chk.check(dest) == 0
        first = _re.search(r"<url>.*?</url>\s*", text, _re.S).group(0)
        sm.write_text(text.replace(first, "", 1), encoding="utf-8")
        assert chk.check(dest) != 0
    finally:
        _remove(dest)


def test_gpu_refresh_workflow_pins_one_clock_for_generate_and_pytest():
    """#220: generate and the pages-match check must share one LW_AVAIL_NOW.

    The refresh job used to call generate_seo_pages.py with no pin (wall-clock
    expiry) and then pytest, whose check() falls back to feed_updated_at, which
    is kept when ranked prices are unchanged. Those clocks diverge, so
    test_committed_pages_match_pinned_generator fails and the refresh never
    publishes. The pin must be exported in run_refresh before generate, so
    pytest inherits it.
    """
    text = (ROOT / ".github" / "workflows" / "gpu-refresh.yml").read_text(encoding="utf-8")
    pin = text.find("export LW_AVAIL_NOW=")
    assert pin != -1 and "run_refresh()" in text[:pin]
    rest = text[pin:]
    close = rest.find("\n          }")
    gen = rest.find("scripts/generate_seo_pages.py")
    pytest_at = rest.find("pytest")
    assert close != -1 and 0 <= gen < pytest_at < close
