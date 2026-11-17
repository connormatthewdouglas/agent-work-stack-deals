"""Sturdiness pass (Relay, 2026-11-17): daily price-history backup, tested restore, 30h watchdog bar."""
import io
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backup_price_history as B  # noqa: E402
import freshness_watchdog as W  # noqa: E402
import restore_price_history as R  # noqa: E402

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def _backup(tmp_path, d1_sql: str | None = None) -> Path:
    d1 = None
    if d1_sql is not None:
        d1 = tmp_path / "d1"
        d1.mkdir()
        (d1 / "stats.sql").write_text(d1_sql, encoding="utf-8")
    return B.build(ROOT, tmp_path / "out", None, d1, NOW)


def test_backup_of_the_checkout_restores_with_matching_counts(tmp_path):
    tar = _backup(tmp_path, "CREATE TABLE hits(k TEXT, n INTEGER);INSERT INTO hits VALUES('a',1);INSERT INTO hits VALUES('b',2);")
    man = json.loads((tmp_path / "out" / "manifest.json").read_text())
    snaps = sorted((ROOT / "data/gpu_pricing/snapshots").glob("*.json"))
    assert man["snapshot_count"] == len(snaps) and man["newest_snapshot"] == snaps[-1].stem
    assert "api/v1/gpu-prices/history.json" in man["files"] and man["feed_updated_at"]
    res = R.verify(tar, tmp_path / "w", tmp_path / "s.sqlite")
    assert res["problems"] == []
    assert res["snapshots"] == man["snapshot_count"] and res["snapshot_rows"] == man["snapshot_rows"]
    assert res["newest_snapshot"] == man["newest_snapshot"] and res["history_series"] == man["history_series"]
    assert res["d1"] == {"d1/stats.sql": {"hits": 2}}
    assert R.main([str(tmp_path / "out")]) == 0


def test_tampered_or_truncated_backup_fails_the_restore_test(tmp_path):
    tar = _backup(tmp_path)
    with tarfile.open(tar, "r:gz") as tf:
        members = [(m, tf.extractfile(m).read()) for m in tf.getmembers()]
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        dropped = False
        for m, data in members:
            if m.name.startswith("data/gpu_pricing/snapshots/") and not dropped:
                dropped = True
                continue  # a snapshot lost from the archive
            if m.name == "api/v1/gpu-prices.json":
                data = data + b" "  # a changed byte
            m.size = len(data)
            tf.addfile(m, io.BytesIO(data))
    res = R.verify(bad, tmp_path / "w", tmp_path / "s.sqlite")
    assert any(p.startswith("missing data/gpu_pricing/snapshots/") for p in res["problems"])
    assert "sha256 mismatch api/v1/gpu-prices.json" in res["problems"]
    assert any(p.startswith("snapshots ") for p in res["problems"])


def test_watchdog_flags_a_backup_older_than_30h():
    assert W.BACKUP_MAX_HOURS == 30
    assert W.backup_problems("2026-11-17T00:00:00Z", NOW) == []
    old = W.backup_problems("2026-11-16T05:00:00Z", NOW)
    assert len(old) == 1 and "31.0h old (limit 30h)" in old[0]
    assert "no successful backup run" in W.backup_problems(None, NOW)[0]


def test_backup_workflow_is_daily_read_only_90_day_artifact_with_restore_test():
    wf = (ROOT / ".github/workflows/price-history-backup.yml").read_text(encoding="utf-8")
    assert 'cron: "37 6 * * *"' in wf and "workflow_dispatch" in wf
    assert "contents: read" in wf and "contents: write" not in wf
    assert "retention-days: 90" in wf and "restore_price_history.py restored --verify --require-git" in wf
    assert "--remote --output" in wf and "> /dev/null 2>&1" in wf  # presigned export URL never reaches the log
    assert "--symmetric" in wf and "shred -u" in wf                 # D1 exports encrypted before upload
