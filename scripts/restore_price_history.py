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
from pathlib import Path


def verify(tar_path: Path, work: Path, db_path: Path) -> dict:
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
    for rel, meta in man["files"].items():
        p = work / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != meta["sha256"]:
            problems.append(f"sha256 mismatch {rel}")
    con = sqlite3.connect(db_path)
    con.executescript("DROP TABLE IF EXISTS snapshot_rows; DROP TABLE IF EXISTS history_series;"
                      "CREATE TABLE snapshot_rows(date TEXT, advertiser TEXT, gpu TEXT, tier TEXT, price_usd REAL);"
                      "CREATE TABLE history_series(rate_id TEXT, points INTEGER);")
    for p in sorted((work / "data/gpu_pricing/snapshots").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        con.executemany("INSERT INTO snapshot_rows VALUES (?,?,?,?,?)",
                        [(d.get("date") or p.stem, r.get("advertiser") or r.get("vendor"), r.get("gpu"), r.get("tier"),
                          r.get("price_usd")) for r in d.get("rows") or []])
    hp = work / "api/v1/gpu-prices/history.json"
    if hp.is_file():
        h = json.loads(hp.read_text(encoding="utf-8"))
        con.executemany("INSERT INTO history_series VALUES (?,?)",
                        [(s.get("rate_id"), len(s.get("points") or [])) for s in h.get("series") or []])
    con.commit()
    rows, snaps, newest = con.execute("SELECT COUNT(*), COUNT(DISTINCT date), MAX(date) FROM snapshot_rows").fetchone()
    series = con.execute("SELECT COUNT(*) FROM history_series").fetchone()[0]
    con.close()
    if snaps != man.get("snapshot_count"):
        problems.append(f"snapshots {snaps} != manifest {man.get('snapshot_count')}")
    if rows != man.get("snapshot_rows"):
        problems.append(f"snapshot rows {rows} != manifest {man.get('snapshot_rows')}")
    if newest != man.get("newest_snapshot"):
        problems.append(f"newest snapshot {newest} != manifest {man.get('newest_snapshot')}")
    if man.get("history_series") is not None and series != man["history_series"]:
        problems.append(f"history series {series} != manifest {man['history_series']}")
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
    return {"problems": problems, "snapshot_rows": rows, "snapshots": snaps, "newest_snapshot": newest,
            "history_series": series, "feed_updated_at": man.get("feed_updated_at"), "created_at": man.get("created_at"),
            "files": len(man["files"]), "d1": d1}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("backup", help="lw-price-history-*.tar.gz (or a directory holding the newest one)")
    ap.add_argument("--verify", action="store_true", help="verify only (default when --into is not given)")
    ap.add_argument("--db", help="scratch sqlite path (default: inside a temp dir)")
    ap.add_argument("--into", help="after verifying, copy the restored files under this directory")
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
        res = verify(src, work, Path(a.db) if a.db else Path(t) / "scratch.sqlite")
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
