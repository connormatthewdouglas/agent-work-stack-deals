#!/usr/bin/env python3
"""Restamp generated pages when only the feed clock moved.

A collector commit can land on main between a PR's generate and its merge.
The merge tree then has the new feed_updated_at but pages still bake the
old feed timestamp / "read Nd ago" text, so test_generated_pages_match fails.

This script classifies the tree against a pinned regenerate
(LW_AVAIL_NOW=feed_updated_at, same clock CI pages-match uses):

  match        — committed pages already match the generator
  clock_stale  — the only diffs are feed-clock display (feed_updated_at,
                 prices-verified-through, "read Nd ago"). Prices, quotes,
                 titles, URLs and last-verified dates are unchanged.
  real_drift   — anything else; the tree is left untouched

On clock_stale, a pinned generate is applied in the workspace so the
strict pages-match test can run afterwards. --commit records that
restamp as a local commit (CI only; this script never pushes).

Real drift is an error: we do not overwrite hand-edits or ship a
loosened match. Last-verified dates and source evidence are never
invented or rewritten by the classifier.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_generated_pages as chk  # noqa: E402

MATCH = "match"
CLOCK_STALE = "clock_stale"
REAL_DRIFT = "real_drift"

# Display that is derived from the feed build clock, not from a row's last-verified date.
_FEED_STAMP_HTML = re.compile(
    r"feed_updated_at=\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC"
)
_VERIFIED_THROUGH_HTML = re.compile(
    r"Prices verified through <code>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC</code>"
)
# Held rows and <time> labels: "read 20d ago" / "read 6h ago" / "read 50m ago" / "read at ..."
_READ_AGO = re.compile(r"read \d+[mhd] ago|read at [0-9T:+\-Z.]+")
_JSON_CLOCK_KEYS = frozenset(
    {"feed_updated_at", "as_of", "prices_verified_through"}
)


def feed_clock(root: Path) -> str:
    """The committed feed stamp; never wall clock."""
    return chk._stamp(root)


def _clock_noise_text(text: str) -> str:
    text = _FEED_STAMP_HTML.sub("feed_updated_at=<FEED_CLOCK>", text)
    text = _VERIFIED_THROUGH_HTML.sub(
        "Prices verified through <code><FEED_CLOCK></code>", text
    )
    text = _READ_AGO.sub("<READ_AGO>", text)
    return text


def _clock_noise_json(text: str):
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    return _strip_clock_keys(doc)


def _strip_clock_keys(obj):
    if isinstance(obj, dict):
        return {
            k: ("<FEED_CLOCK>" if k in _JSON_CLOCK_KEYS else _strip_clock_keys(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_strip_clock_keys(v) for v in obj]
    return obj


def only_clock_display_differs(a: Path, b: Path) -> bool:
    """True when a and b differ only by feed-clock display, not by prices or copy."""
    try:
        ta = a.read_text(encoding="utf-8")
        tb = b.read_text(encoding="utf-8")
    except OSError:
        return False
    ja, jb = _clock_noise_json(ta), _clock_noise_json(tb)
    if ja is not None and jb is not None:
        return ja == jb
    return _clock_noise_text(ta) == _clock_noise_text(tb)


def _diff_files(src: Path, dest: Path) -> list[tuple[Path, Path]] | None:
    """Return (src, dest) pairs for mismatched files, or None if a path was added/removed."""
    lines = chk._diff_names(src, dest)
    pairs = []
    prefix = f"Files {src}/"
    mid = f" and {dest}/"
    for line in lines:
        if line.startswith(prefix) and mid in line:
            rest = line[len("Files "):]
            left, right = rest.split(" and ", 1)
            if right.endswith(" differ"):
                right = right[: -len(" differ")]
            pairs.append((Path(left), Path(right)))
        else:
            # "Only in ..." (added or removed page) is real drift, not a clock restamp.
            return None
    return pairs


def _regen_copy(root: Path) -> Path:
    """Generate into a detached worktree at the feed clock; caller must remove it."""
    stamp = feed_clock(root)
    dest = Path(tempfile.mkdtemp(prefix="lw-restamp-"))
    subprocess.check_call(
        ["git", "-C", str(root), "worktree", "add", "--detach", "--quiet", str(dest), "HEAD"],
        stdout=subprocess.DEVNULL,
    )
    chk._overlay(root, dest)
    env = os.environ.copy()
    env["LW_AVAIL_NOW"] = stamp
    subprocess.check_call(
        [sys.executable, str(dest / "scripts" / "generate_seo_pages.py")],
        cwd=dest, env=env, stdout=subprocess.DEVNULL,
    )
    return dest


def classify(root: Path) -> str:
    """Classify root vs a pinned regenerate. Does not write into root."""
    root = root.resolve()
    dest = _regen_copy(root)
    try:
        pairs = _diff_files(root, dest)
        if pairs is None:
            return REAL_DRIFT
        if not pairs:
            return MATCH
        if all(only_clock_display_differs(a, b) for a, b in pairs):
            return CLOCK_STALE
        return REAL_DRIFT
    finally:
        subprocess.call(
            ["git", "-C", str(root), "worktree", "remove", "--force", str(dest)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)


def _generate_in_place(root: Path) -> None:
    stamp = feed_clock(root)
    env = os.environ.copy()
    env["LW_AVAIL_NOW"] = stamp
    subprocess.check_call(
        [sys.executable, str(root / "scripts" / "generate_seo_pages.py")],
        cwd=root, env=env, stdout=subprocess.DEVNULL,
    )


def _commit_if_dirty(root: Path, stamp: str) -> None:
    status = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain"], text=True
    )
    if not status.strip():
        return
    subprocess.check_call(["git", "-C", str(root), "add", "-A"])
    # Local commit only so subsequent pages-match HEAD worktrees see the restamp.
    # Never pushed by this script.
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "lantern-works-ci"
    env["GIT_AUTHOR_EMAIL"] = "ci@localhost"
    env["GIT_COMMITTER_NAME"] = "lantern-works-ci"
    env["GIT_COMMITTER_EMAIL"] = "ci@localhost"
    subprocess.check_call(
        [
            "git", "-C", str(root), "commit", "-qm",
            f"ci: restamp generated pages to feed clock {stamp}",
        ],
        env=env,
    )


def restamp(root: Path, *, commit: bool = False) -> int:
    """Return 0 on match or after a clock restamp; 1 on real drift (tree unchanged)."""
    root = root.resolve()
    kind = classify(root)
    stamp = feed_clock(root)
    if kind == MATCH:
        print(f"generated pages already match the feed clock {stamp}")
        return 0
    if kind == REAL_DRIFT:
        print(
            "generated pages differ from the pinned generator by more than the "
            "feed clock (real drift). Tree left unchanged.",
            file=sys.stderr,
        )
        return 1
    _generate_in_place(root)
    print(f"restamped generated pages to feed clock {stamp}")
    if commit:
        _commit_if_dirty(root, stamp)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--classify-only",
        action="store_true",
        help="print match / clock_stale / real_drift and do not write",
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="after a clock restamp, make a local git commit (never pushed)",
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args()
    root = a.root.resolve()
    if a.classify_only:
        kind = classify(root)
        print(kind)
        return 0 if kind != REAL_DRIFT else 1
    return restamp(root, commit=a.commit)


if __name__ == "__main__":
    raise SystemExit(main())
