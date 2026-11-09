"""Regenerate the site in a temp copy and diff it against the pages on disk.

Nothing in the source tree is written. The comparison is the current files, not git HEAD,
so a workflow that has already regenerated from this same feed still passes. On a clean
checkout those files are the committed pages. The clock is LW_AVAIL_NOW when set (one build clock for scout-import checks),
otherwise the feed's own feed_updated_at. A hand-edited page still fails.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Checkout noise and local secrets. The generator does not own these.
_SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _stamp(root: Path) -> str:
    # Prefer LW_AVAIL_NOW when the caller pinned one build clock (check_latest_scout_import.sh).
    # Otherwise fall back to the feed's own stamp so a clean checkout still matches itself.
    env_stamp = (os.environ.get("LW_AVAIL_NOW") or "").strip()
    if env_stamp:
        return env_stamp
    feed = json.loads((root / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    stamp = feed.get("feed_updated_at")
    if not stamp:
        raise SystemExit("gpu-prices.json has no feed_updated_at")
    return stamp


def _overlay(src: Path, dest: Path) -> None:
    """Make dest's files match src, leaving dest's .git (a worktree file) in place."""
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if _SKIP_PARTS.intersection(rel.parts):
            continue
        target = dest / rel
        if path.is_symlink() or path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target, follow_symlinks=False)
        elif path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
    extras = []
    for path in dest.rglob("*"):
        rel = path.relative_to(dest)
        if not rel.parts or _SKIP_PARTS.intersection(rel.parts):
            continue
        if not (src / rel).exists():
            extras.append(path)
    for path in sorted(extras, key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            path.rmdir() if not any(path.iterdir()) else shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            path.unlink()


# Git provenance, not generated content: gpu_index.py records the last commit that touched the
# feed. A commit that changes the feed can never contain its own sha, so this field always lags
# one commit behind on the commit that changes the feed. Compare everything else in the file.
_GIT_PROVENANCE_KEYS = {"feed_commit_for_listing_counts"}
_PROVENANCE_FILES = {"api/v1/gpu-price-index.json"}


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in _GIT_PROVENANCE_KEYS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def _same_except_provenance(a: Path, b: Path) -> bool:
    try:
        return _strip(json.loads(a.read_text(encoding="utf-8"))) == _strip(json.loads(b.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def _diff_names(src: Path, dest: Path) -> list[str]:
    proc = subprocess.run(
        ["diff", "-rq", "--exclude=.git", "--exclude=__pycache__", "--exclude=.pytest_cache",
         "--exclude=.mypy_cache", "--exclude=.ruff_cache", str(src), str(dest)],
        capture_output=True, text=True,
    )
    names = []
    for line in proc.stdout.splitlines():
        if "scout/secrets" in line or line.endswith(": secrets"):
            continue
        rel = next((f for f in _PROVENANCE_FILES if line == f"Files {src / f} and {dest / f} differ"), None)
        if rel and _same_except_provenance(src / rel, dest / rel):
            continue
        names.append(line)
    return names


def check(root: Path | None = None) -> int:
    """Return 0 when a pinned regenerate of root matches the files already there."""
    root = (root or ROOT).resolve()
    stamp = _stamp(root)
    dest = Path(tempfile.mkdtemp(prefix="lw-pages-"))
    try:
        subprocess.check_call(
            ["git", "-C", str(root), "worktree", "add", "--detach", "--quiet", str(dest), "HEAD"],
            stdout=subprocess.DEVNULL,
        )
        _overlay(root, dest)
        env = os.environ.copy()
        env["LW_AVAIL_NOW"] = stamp
        subprocess.check_call(
            [sys.executable, str(dest / "scripts" / "generate_seo_pages.py")],
            cwd=dest, env=env, stdout=subprocess.DEVNULL,
        )
        names = _diff_names(root, dest)
    finally:
        subprocess.call(
            ["git", "-C", str(root), "worktree", "remove", "--force", str(dest)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
    if names:
        print("generated pages differ from the files on disk:", file=sys.stderr)
        print("\n".join(names[:80]), file=sys.stderr)
        return 1
    print("generated pages match the files on disk at", stamp)
    return 0


def main() -> int:
    return check(ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
