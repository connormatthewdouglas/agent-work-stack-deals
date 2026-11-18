#!/usr/bin/env python3
"""Daily price-history backup (sturdiness pass, Relay 2026-11-17).

Packs the price history and the files it is rebuilt from into one tar.gz plus a manifest:
  * data/gpu_pricing/** (per-vendor records and the dated snapshots/YYYY-MM-DD.json)
  * api/v1/gpu-prices.json and api/v1/gpu-prices/history.json (the published feed and per-series history)
  * data/gpu_availability/*.json, data/feed_state.json, data/owner_hold.json, data/price_confirmations.json
  * scout-data:latest/* (Scout's last import inputs), when the ref is available
  * any D1 exports already written to --d1-dir (*.sql or *.sql.gpg; see the workflow, optional)

The manifest records sha256 and size per file, snapshot count, newest snapshot date, feed_updated_at, and the
history's series/changes counts, so scripts/restore_price_history.py can prove a restore is complete.
Reads only. Never touches Cloudflare or the repo's tracked files.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "lantern-works-price-history-backup/1"
FILES = ("api/v1/gpu-prices.json", "api/v1/gpu-prices/history.json", "data/feed_state.json",
         "data/owner_hold.json", "data/price_confirmations.json")
GLOBS = ("data/gpu_pricing/**/*.json", "data/gpu_availability/*.json")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def collect(root: Path, scout_ref: str | None) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for rel in FILES:
        p = root / rel
        if p.is_file():
            out[rel] = p.read_bytes()
    for g in GLOBS:
        for p in sorted(root.glob(g)):
            if p.is_file():
                out[p.relative_to(root).as_posix()] = p.read_bytes()
    if scout_ref:
        try:
            names = subprocess.check_output(["git", "ls-tree", "--name-only", f"{scout_ref}:latest"], cwd=root,
                                            text=True, stderr=subprocess.DEVNULL).split()
            for n in names:
                out[f"scout-data/latest/{n}"] = subprocess.check_output(
                    ["git", "show", f"{scout_ref}:latest/{n}"], cwd=root, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, OSError):
            print(f"warning: {scout_ref} not available; scout-data/latest not included", file=sys.stderr)
    return out


def summary(files: dict[str, bytes]) -> dict:
    snaps = sorted(k for k in files if k.startswith("data/gpu_pricing/snapshots/") and k.endswith(".json"))
    s: dict = {"snapshot_count": len(snaps), "newest_snapshot": Path(snaps[-1]).stem if snaps else None,
               "snapshot_rows": sum(len(json.loads(files[k]).get("rows") or []) for k in snaps)}
    if "api/v1/gpu-prices.json" in files:
        feed = json.loads(files["api/v1/gpu-prices.json"])
        s["feed_updated_at"] = feed.get("feed_updated_at")
        s["feed_rates"] = len(feed.get("rates") or [])
    if "api/v1/gpu-prices/history.json" in files:
        h = json.loads(files["api/v1/gpu-prices/history.json"])
        s["history_series"] = len(h.get("series") or [])
        s["history_changes"] = len(h.get("changes") or [])
        s["history_last_snapshot"] = h.get("last_snapshot")
    return s


def _backed_up_path(rel: str, files: dict[str, bytes]) -> bool:
    """A repo path this backup carries (or would carry if it still existed): FILES + GLOBS."""
    if rel in files or rel in FILES:
        return True
    if rel.startswith("data/gpu_pricing/") and rel.endswith(".json"):
        return True
    return rel.startswith("data/gpu_availability/") and rel.endswith(".json") and rel.count("/") == 2


def _clean_commit(root: Path, files: dict[str, bytes]) -> tuple[str | None, list[str]]:
    """(HEAD, []) when every backed-up path matches HEAD; (None, changed paths) when the working tree differs.

    Relay 2026-11-17: the manifest used to stamp HEAD even when a collector had just rewritten data/ and api/v1
    without committing, so the archive claimed a commit its bytes did not match and the restore's git
    comparison failed. A dirty backup now records no commit (and --require-git / --expect-commit fail on it)."""
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                         stderr=subprocess.DEVNULL).strip()
        out = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all", "--", "api/v1", "data"],
                                      cwd=root, text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):
        return None, []
    changed = set()
    for line in out.splitlines():
        for rel in line[3:].split(" -> "):
            rel = rel.strip().strip('"')
            if _backed_up_path(rel, files):
                changed.add(rel)
    return (None, sorted(changed)) if changed else (commit or None, [])


def build(root: Path, out_dir: Path, scout_ref: str | None, d1_dir: Path | None, now: datetime) -> Path:
    files = collect(root, scout_ref)
    if d1_dir and d1_dir.is_dir():
        for p in sorted(d1_dir.iterdir()):
            if p.is_file() and (p.name.endswith(".sql") or p.name.endswith(".sql.gpg")):
                files[f"d1/{p.name}"] = p.read_bytes()
    commit, uncommitted = _clean_commit(root, files)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    manifest = {
        "schema": SCHEMA, "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "commit": commit,
        "uncommitted_files": uncommitted, "scout_ref": scout_ref, **summary(files),
        "d1": sorted(k for k in files if k.startswith("d1/")),
        "files": {k: {"sha256": _sha(v), "bytes": len(v)} for k, v in sorted(files.items())},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = out_dir / f"lw-price-history-{stamp}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        for name, data in [("manifest.json", json.dumps(manifest, indent=1).encode())] + sorted(files.items()):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime, ti.mode = len(data), int(now.timestamp()), 0o644
            tf.addfile(ti, io.BytesIO(data))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return tar_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="backup", help="output directory (default ./backup)")
    ap.add_argument("--scout-ref", default="origin/scout-data", help="git ref with Scout's latest/ (empty = skip)")
    ap.add_argument("--d1-dir", help="directory of D1 exports (*.sql / *.sql.gpg) to include")
    a = ap.parse_args(argv)
    tar = build(ROOT, Path(a.out), a.scout_ref or None, Path(a.d1_dir) if a.d1_dir else None,
                datetime.now(timezone.utc))
    m = json.loads((Path(a.out) / "manifest.json").read_text(encoding="utf-8"))
    print(f"{tar}: {len(m['files'])} files, {m['snapshot_count']} snapshots (newest {m['newest_snapshot']}), "
          f"history {m.get('history_series')} series / {m.get('history_changes')} changes, d1={len(m['d1'])}")
    return 0 if m["snapshot_count"] and m.get("feed_updated_at") else 1


if __name__ == "__main__":
    sys.exit(main())
