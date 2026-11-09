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
        text = pricing.read_text(encoding="utf-8")
        old = "2026-11-09T06:02:13+00:00"
        assert old in text
        pricing.write_text(text.replace(old, "2026-11-09T06:02:14+00:00", 1), encoding="utf-8")
        _regenerate(dest)
        assert chk.check(dest) == 0
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
