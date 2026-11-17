#!/usr/bin/env python3
"""Restore (and prove) a price-history backup made by scripts/backup_price_history.py.

  python3 scripts/restore_price_history.py BACKUP.tar.gz --verify [--db scratch.sqlite]
      Extract to a scratch directory, check every file's sha256 against the manifest, load the snapshots and the
      published history into a scratch sqlite database, and check the row counts and newest snapshot against the
      manifest. Plain D1 exports (d1/*.sql) are loaded into their own scratch sqlite and their tables counted.
      Encrypted D1 exports (*.sql.gpg) are decrypted only when BACKUP_PASSPHRASE is set.
      Exit 1 on any mismatch.
  python3 scripts/restore_price_history.py BACKUP.tar.gz --into DIR
      After --verify passes, also copy the files back under DIR (for example a fresh worktree of main), then
      review and open a PR. It never writes to Cloudflare. To put a D1 export back, use
      `wrangler d1 execute <db> --local --file d1/<db>.sql` first, and only a human runs --remote.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
import backup_price_history as B  # noqa: E402  (SCHEMA, FILES: one source of truth)


NEWEST_MAX_LAG_DAYS = 2  # the newest snapshot must be within ~2 days of the manifest's created_at


def _blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324  (git object id, not security)


def _tracked(rel: str) -> bool:
    """A repo path the backup must carry (backup_price_history.FILES + GLOBS)."""
    if rel in B.FILES:
        return True
    if rel.startswith("data/gpu_pricing/") and rel.endswith(".json"):
        return True
    return rel.startswith("data/gpu_availability/") and rel.endswith(".json") and rel.count("/") == 2


def git_problems(man: dict, work: Path, root: Path, require: bool) -> tuple[list[str], str]:
    """Compare restored repo files with the tree of manifest.commit (`git show <commit>:<path>`, by blob id).
    Every tracked file in that commit must be in the backup with the same bytes. Returns (problems, status)."""
    commit = man.get("commit") or ""
    if not commit:
        return (["manifest has no commit to compare against"] if require else []), "skipped (no commit)"

    def has() -> bool:
        return subprocess.call(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=root,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    if not has():
        subprocess.call(["git", "fetch", "-q", "--depth=1", "origin", commit], cwd=root,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not has():
        return ([f"commit {commit[:12]} not available to compare against"] if require else []), "skipped (commit not available)"
    out = subprocess.check_output(["git", "ls-tree", "-r", commit, "--", "api/v1", "data"], cwd=root, text=True)
    want = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        if _tracked(path):
            want[path] = meta.split()[2]
    problems = []
    for path, oid in sorted(want.items()):
        p = work / path
        if path not in man["files"] or not p.is_file():
            problems.append(f"{path} is in commit {commit[:12]} but not in the backup")
        elif _blob_sha1(p.read_bytes()) != oid:
            problems.append(f"{path} differs from commit {commit[:12]}")
    return problems, f"compared {len(want)} files with {commit[:12]}"


def verify(tar_path: Path, work: Path, db_path: Path, root: Path | None = None, require_git: bool = False,
           expect_commit: str | None = None) -> dict:
    with tarfile.open(tar_path, "r:gz") as tf:
        for m in tf.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts or not m.isfile():
                raise SystemExit(f"refusing unsafe tar member {m.name!r}")
        try:
            tf.extractall(work, filter="data")  # members checked above too
        except TypeError:  # Python < 3.12 without extraction filters
            tf.extractall(work)  # noqa: S202
    man = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    if expect_commit is not None:  # CI: the backup must be pinned to the commit this run checked out
        got = str(man.get("commit") or "").lower()
        want = expect_commit.strip().lower()
        if not want or not got or not (got.startswith(want) or want.startswith(got)) or min(len(got), len(want)) < 7:
            problems.append(f"manifest commit {got[:12] or '(none)'} != expected {want[:12] or '(none)'}")
    if man.get("schema") != B.SCHEMA:
        problems.append(f"manifest schema {man.get('schema')!r} != {B.SCHEMA!r}")
    files = man.get("files") if isinstance(man.get("files"), dict) else {}
    for rel in B.FILES:  # every fixed file is required, in the manifest and in the archive
        if rel not in files or not (work / rel).is_file():
            problems.append(f"required file {rel} missing from the backup")
    for rel, meta in files.items():
        p = work / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != (meta or {}).get("sha256"):
            problems.append(f"sha256 mismatch {rel}")
    con = sqlite3.connect(db_path)
    con.executescript("DROP TABLE IF EXISTS snapshot_rows; DROP TABLE IF EXISTS history_series;"
                      "DROP TABLE IF EXISTS snapshot_files;"
                      "CREATE TABLE snapshot_files(date TEXT);"
                      "CREATE TABLE snapshot_rows(date TEXT, advertiser TEXT, gpu TEXT, tier TEXT, price_usd REAL);"
                      "CREATE TABLE history_series(rate_id TEXT, points INTEGER);")
    for p in sorted((work / "data/gpu_pricing/snapshots").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        con.execute("INSERT INTO snapshot_files VALUES (?)", (p.stem,))  # a legitimately empty snapshot still counts
        con.executemany("INSERT INTO snapshot_rows VALUES (?,?,?,?,?)",
                        [(d.get("date") or p.stem, r.get("advertiser") or r.get("vendor"), r.get("gpu"), r.get("tier"),
                          r.get("price_usd")) for r in d.get("rows") or []])
    hp = work / "api/v1/gpu-prices/history.json"
    if hp.is_file():
        h = json.loads(hp.read_text(encoding="utf-8"))
        con.executemany("INSERT INTO history_series VALUES (?,?)",
                        [(s.get("rate_id"), len(s.get("points") or [])) for s in h.get("series") or []])
    con.commit()
    snaps, newest = con.execute("SELECT COUNT(*), MAX(date) FROM snapshot_files").fetchone()
    rows = con.execute("SELECT COUNT(*) FROM snapshot_rows").fetchone()[0]
    series = con.execute("SELECT COUNT(*) FROM history_series").fetchone()[0]
    con.close()
    for label, got in (("snapshot files", snaps), ("snapshot rows", rows), ("history series", series),
                       ("files", len(files))):
        if not got:
            problems.append(f"{label} is 0 (an empty backup is a failed backup)")
    if snaps != man.get("snapshot_count"):
        problems.append(f"snapshots {snaps} != manifest {man.get('snapshot_count')}")
    if rows != man.get("snapshot_rows"):
        problems.append(f"snapshot rows {rows} != manifest {man.get('snapshot_rows')}")
    if newest != man.get("newest_snapshot"):
        problems.append(f"newest snapshot {newest} != manifest {man.get('newest_snapshot')}")
    if series != man.get("history_series"):
        problems.append(f"history series {series} != manifest {man.get('history_series')}")
    try:
        created = datetime.fromisoformat(str(man.get("created_at")).replace("Z", "+00:00"))
        lag = created.date() - date.fromisoformat(str(newest))
        if lag > timedelta(days=NEWEST_MAX_LAG_DAYS):
            problems.append(f"newest snapshot {newest} is {lag.days} days before the backup ({man.get('created_at')}); "
                            f"limit {NEWEST_MAX_LAG_DAYS} days")
    except ValueError:
        problems.append(f"cannot compare newest snapshot {newest!r} with created_at {man.get('created_at')!r}")
    gp, git_status = git_problems(man, work, root or ROOT, require_git)
    problems += gp
    d1 = {}
    for rel in man.get("d1") or []:
        p = work / rel
        if rel.endswith(".gpg"):
            if not os.environ.get("BACKUP_PASSPHRASE"):
                d1[rel] = "encrypted (set BACKUP_PASSPHRASE to test)"
                continue
            plain = p.with_suffix("")
            subprocess.run(["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase-fd", "0",
                            "--output", str(plain), "--decrypt", str(p)],
                           input=os.environ["BACKUP_PASSPHRASE"].encode(), check=True)
            p = plain
        dcon = sqlite3.connect(work / (p.name + ".sqlite"))
        try:
            dcon.executescript(p.read_text(encoding="utf-8"))
            tables = [t for (t,) in dcon.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                 "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'")]
            d1[rel] = {t: dcon.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        except sqlite3.Error as e:
            problems.append(f"{rel} does not load into sqlite: {e}")
        finally:
            dcon.close()
    return {"problems": problems, "git": git_status, "snapshot_rows": rows, "snapshots": snaps, "newest_snapshot": newest,
            "history_series": series, "feed_updated_at": man.get("feed_updated_at"), "created_at": man.get("created_at"),
            "files": len(man["files"]), "d1": d1}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("backup", help="lw-price-history-*.tar.gz (or a directory holding the newest one)")
    ap.add_argument("--verify", action="store_true", help="verify only (default when --into is not given)")
    ap.add_argument("--db", help="scratch sqlite path (default: inside a temp dir)")
    ap.add_argument("--into", help="after verifying, copy the restored files under this directory")
    ap.add_argument("--expect-commit", help="fail unless manifest.commit is this commit (CI passes $GITHUB_SHA)")
    ap.add_argument("--require-git", action="store_true",
                    help="fail when manifest.commit cannot be compared (CI); default skips that comparison")
    a = ap.parse_args(argv)
    src = Path(a.backup)
    if src.is_dir():
        found = sorted(src.rglob("lw-price-history-*.tar.gz"))
        if not found:
            print(f"no lw-price-history-*.tar.gz under {src}")
            return 1
        src = found[-1]
    with tempfile.TemporaryDirectory() as t:
        work = Path(t) / "restore"
        work.mkdir()
        res = verify(src, work, Path(a.db) if a.db else Path(t) / "scratch.sqlite", require_git=a.require_git,
                     expect_commit=a.expect_commit)
        print(json.dumps({"backup": src.name, **res}, indent=1))
        if res["problems"]:
            print("RESTORE TEST FAILED")
            return 1
        print("RESTORE TEST OK")
        if a.into:
            dest = Path(a.into)
            for p in work.rglob("*"):
                rel = p.relative_to(work)
                if p.is_file() and rel.parts[0] not in ("manifest.json",) and not rel.name.endswith(".sqlite"):
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest / rel)
            print(f"restored files under {dest}; review with git status and open a PR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
