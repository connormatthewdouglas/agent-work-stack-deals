"""P42: scout-data history/probes merge is append-only and the push script publishes it."""
import gzip
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
import merge_probe_archive as m


def _write_line(path: Path, rec: dict, mode="wt"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, mode, encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def test_merge_never_drops_remote_lines(tmp_path):
    local, remote = tmp_path / "local", tmp_path / "remote"
    _write_line(local / "2026-11-11.jsonl.gz", {"source_file": "a.json", "ok": True, "collected_at": "2026-11-11T20:00:00Z"})
    assert m.merge_into_remote(local, remote)["added_lines"] == 1
    # local wipe: only a later (failed) probe remains locally
    local2 = tmp_path / "local2"
    _write_line(local2 / "2026-11-11.jsonl.gz", {"source_file": "b_FAILED.json", "ok": False, "errors": {"vast": "Timeout"}, "rows": []})
    m.merge_into_remote(local2, remote)
    recs = [json.loads(ln) for ln in m.gzip_lines(remote / "2026-11-11.jsonl.gz")]
    assert [r["source_file"] for r in recs] == ["a.json", "b_FAILED.json"]
    assert recs[1]["ok"] is False and recs[1]["rows"] == []
    assert "availability_checked_at" not in recs[1]
    assert m.merge_into_remote(local2, remote)["added_lines"] == 0


def test_push_script_publishes_history_probes_and_is_valid_bash():
    sh = (ROOT / "scripts/push_scout_snapshot.sh").read_text()
    assert "history/probes" in sh
    assert "git add -A latest history/probes" in sh
    assert "never drop" in sh.lower() or "never drops" in sh.lower() or "Never drop" in sh
    r = subprocess.run(["bash", "-n", str(ROOT / "scripts/push_scout_snapshot.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
