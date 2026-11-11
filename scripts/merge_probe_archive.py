"""P42: merge local daily gzipped JSONL probe archives into a remote history/probes dir.

Never drops lines already on the remote side (a wiped local out/ must not erase
the durable scout-data archive). Local-only lines are appended. No secrets are
invented here; the writer redacts before append.
"""
from __future__ import annotations

import gzip
import os
import sys
import tempfile
from pathlib import Path


def gzip_lines(path: Path) -> list[str]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [ln if ln.endswith("\n") else ln + "\n" for ln in f]


def write_gzip_lines(path: Path, lines: list[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
            f.writelines(lines)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def merge_into_remote(src_dir, dst_dir) -> dict:
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    added_total = 0
    files = 0
    if src_dir.is_dir():
        for src in sorted(src_dir.glob("*.jsonl.gz")):
            dst = dst_dir / src.name
            old = gzip_lines(dst)
            seen = set(old)
            new = list(old)
            added = 0
            for ln in gzip_lines(src):
                if ln not in seen:
                    new.append(ln)
                    seen.add(ln)
                    added += 1
            if added or not dst.exists():
                write_gzip_lines(dst, new)
            added_total += added
            files += 1
    return {"files": files, "added_lines": added_total}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: merge_probe_archive.py <local probe_archive dir> <remote history/probes dir>", file=sys.stderr)
        return 2
    print(merge_into_remote(argv[0], argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
