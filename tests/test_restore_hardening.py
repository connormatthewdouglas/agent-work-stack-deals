"""Gauge probes on the merged backup restore (#263) that wrongly passed; each must now fail."""
import io
import json
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backup_price_history as B  # noqa: E402
import restore_price_history as R  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from _backup_fixture import NOW, make_repo, snaps  # noqa: E402

# Fixed, committed repo + fixed clock (tests/_backup_fixture.py), never the live checkout or the wall clock:
# the git comparison and the snapshot-lag probe now always run instead of depending on collector state.
HISTORY = "api/v1/gpu-prices/history.json"


def _repo(tmp_path) -> Path:
    return tmp_path / "repo" if (tmp_path / "repo").is_dir() else make_repo(tmp_path)


def _base(tmp_path) -> Path:
    return B.build(_repo(tmp_path), tmp_path / "out", None, None, NOW)


def _rewrite(tar: Path, dest: Path, drop=(), manifest=None) -> Path:
    """Copy an archive, dropping members, and optionally rewriting the manifest (to stay self-consistent)."""
    with tarfile.open(tar, "r:gz") as tf:
        members = [(m, tf.extractfile(m).read()) for m in tf.getmembers()]
    man = json.loads(dict((m.name, d) for m, d in members)["manifest.json"])
    if manifest:
        manifest(man)
    with tarfile.open(dest, "w:gz") as tf:
        for m, data in members:
            if m.name in drop:
                continue
            if m.name == "manifest.json":
                data = json.dumps(man).encode()
            m.size = len(data)
            tf.addfile(m, io.BytesIO(data))
    return dest


def _verify(tar, tmp_path, require_git=False):
    w = tmp_path / f"w{len(list(tmp_path.iterdir()))}"
    w.mkdir()
    return R.verify(tar, w, w / "s.sqlite", root=_repo(tmp_path), require_git=require_git)


def test_clean_backup_passes_including_the_git_comparison(tmp_path):
    res = _verify(_base(tmp_path), tmp_path, require_git=True)
    assert res["problems"] == [], res["problems"]
    assert res["git"].startswith("compared ")


def test_probe_no_history_json_in_archive(tmp_path):
    bad = _rewrite(_base(tmp_path), tmp_path / "p1.tar.gz", drop={HISTORY})
    probs = _verify(bad, tmp_path)["problems"]
    assert f"required file {HISTORY} missing from the backup" in probs


def test_probe_history_removed_from_archive_and_manifest(tmp_path):
    def m(man):
        man["files"].pop(HISTORY)
        for k in ("history_series", "history_changes", "history_last_snapshot"):
            man.pop(k, None)
    bad = _rewrite(_base(tmp_path), tmp_path / "p2.tar.gz", drop={HISTORY}, manifest=m)
    probs = _verify(bad, tmp_path)["problems"]
    assert f"required file {HISTORY} missing from the backup" in probs
    assert any(p.startswith("history series is 0") for p in probs)


def test_probe_wrong_manifest_schema(tmp_path):
    bad = _rewrite(_base(tmp_path), tmp_path / "p3.tar.gz", manifest=lambda man: man.update(schema="something/9"))
    assert any(p.startswith("manifest schema 'something/9'") for p in _verify(bad, tmp_path)["problems"])


def test_probe_newest_five_snapshots_missing_consistently(tmp_path):
    SNAPS = snaps(_repo(tmp_path))
    gone = [f"data/gpu_pricing/snapshots/{p.name}" for p in SNAPS[-5:]]
    keep = SNAPS[:-5]

    def m(man):
        for g in gone:
            man["files"].pop(g)
        man["snapshot_count"] = len(keep)
        man["snapshot_rows"] = sum(len(json.loads(p.read_text()).get("rows") or []) for p in keep)
        man["newest_snapshot"] = keep[-1].stem
    bad = _rewrite(_base(tmp_path), tmp_path / "p4.tar.gz", drop=set(gone), manifest=m)
    res = _verify(bad, tmp_path)
    lag = (NOW.date() - datetime.fromisoformat(keep[-1].stem).date()).days
    assert lag > R.NEWEST_MAX_LAG_DAYS  # fixed fixture: 2026-11-12 vs 2026-11-17
    assert any("days before the backup" in p for p in res["problems"])
    assert any(p == f"{gone[-1]} is in the commit" or "not in the backup" in p for p in res["problems"])
    assert res["problems"]


def test_empty_snapshot_file_still_counts(tmp_path):
    SNAPS = snaps(_repo(tmp_path))
    name = "data/gpu_pricing/snapshots/" + SNAPS[0].name
    empty = json.dumps({"schema": "lantern-works-gpu-snapshot/1", "date": SNAPS[0].stem, "rows": []}).encode()
    tar = _base(tmp_path)
    with tarfile.open(tar, "r:gz") as tf:
        members = [(m, tf.extractfile(m).read()) for m in tf.getmembers()]
    man = json.loads(dict((m.name, d) for m, d in members)["manifest.json"])
    import hashlib
    man["files"][name] = {"sha256": hashlib.sha256(empty).hexdigest(), "bytes": len(empty)}
    man["snapshot_rows"] -= len(json.loads(SNAPS[0].read_text()).get("rows") or [])
    out = tmp_path / "e.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        for m, data in members:
            data = empty if m.name == name else (json.dumps(man).encode() if m.name == "manifest.json" else data)
            m.size = len(data)
            tf.addfile(m, io.BytesIO(data))
    probs = _verify(out, tmp_path)["problems"]
    assert not any(p.startswith("snapshots ") for p in probs), probs  # file count, not distinct row dates
    assert all("differs from commit" in p or "is in commit" in p for p in probs), probs  # only the git compare


def test_tampered_bytes_differ_from_commit(tmp_path):
    import hashlib
    rel = "data/gpu_pricing/aws.json"
    tar = _base(tmp_path)
    with tarfile.open(tar, "r:gz") as tf:
        members = [(m, tf.extractfile(m).read()) for m in tf.getmembers()]
    man = json.loads(dict((m.name, d) for m, d in members)["manifest.json"])
    out = tmp_path / "t.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        for m, data in members:
            if m.name == rel:
                data = data + b"\n"
                man["files"][rel]["sha256"] = hashlib.sha256(data).hexdigest()
            if m.name == "manifest.json":
                continue
            m.size = len(data)
            tf.addfile(m, io.BytesIO(data))
        mi = tarfile.TarInfo("manifest.json")
        md = json.dumps(man).encode()
        mi.size = len(md)
        tf.addfile(mi, io.BytesIO(md))
    probs = _verify(out, tmp_path, require_git=True)["problems"]
    assert f"{rel} differs from commit" in " ".join(probs)
