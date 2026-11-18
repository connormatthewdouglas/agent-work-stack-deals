"""Sturdiness pass (Relay, 2026-11-17): daily price-history backup, tested restore, 30h watchdog bar."""
import io
import json
import sys
import tarfile

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backup_price_history as B  # noqa: E402
import freshness_watchdog as W  # noqa: E402
import restore_price_history as R  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from _backup_fixture import NOW, make_repo, snaps as _snaps  # noqa: E402

# Fixed repo + fixed clock (tests/_backup_fixture.py): no dependence on the live checkout or the time of day.


def _backup(tmp_path, d1_sql: str | None = None) -> Path:
    d1 = None
    if d1_sql is not None:
        d1 = tmp_path / "d1"
        d1.mkdir()
        (d1 / "stats.sql").write_text(d1_sql, encoding="utf-8")
    return B.build(tmp_path / "repo", tmp_path / "out", None, d1, NOW)


def test_backup_of_the_checkout_restores_with_matching_counts(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    tar = _backup(tmp_path, "CREATE TABLE hits(k TEXT, n INTEGER);INSERT INTO hits VALUES('a',1);INSERT INTO hits VALUES('b',2);")
    man = json.loads((tmp_path / "out" / "manifest.json").read_text())
    snaps = _snaps(repo)
    assert man["commit"] and man["uncommitted_files"] == []
    assert man["snapshot_count"] == len(snaps) and man["newest_snapshot"] == snaps[-1].stem
    assert "api/v1/gpu-prices/history.json" in man["files"] and man["feed_updated_at"]
    res = R.verify(tar, tmp_path / "w", tmp_path / "s.sqlite", root=repo, require_git=True, expect_commit=man["commit"])
    assert res["problems"] == []
    assert res["git"].startswith("compared ")
    assert res["snapshots"] == man["snapshot_count"] and res["snapshot_rows"] == man["snapshot_rows"]
    assert res["newest_snapshot"] == man["newest_snapshot"] and res["history_series"] == man["history_series"]
    assert res["d1"] == {"d1/stats.sql": {"hits": 2}}
    monkeypatch.setattr(R, "ROOT", repo)
    assert R.main([str(tmp_path / "out"), "--require-git", "--expect-commit", man["commit"]]) == 0


def test_tampered_or_truncated_backup_fails_the_restore_test(tmp_path):
    repo = make_repo(tmp_path)
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
    res = R.verify(bad, tmp_path / "w", tmp_path / "s.sqlite", root=repo)
    assert any(p.startswith("missing data/gpu_pricing/snapshots/") for p in res["problems"])
    assert "sha256 mismatch api/v1/gpu-prices.json" in res["problems"]
    assert any(p.startswith("snapshots ") for p in res["problems"])


def test_uncommitted_collector_output_is_not_stamped_with_head(tmp_path):
    """The 2026-11-17 collector failures: data rewritten after checkout, backup still claimed HEAD."""
    repo = make_repo(tmp_path)
    (repo / "data/gpu_pricing/aws.json").write_text('{"vendor": "AWS", "records": []}\n', encoding="utf-8")
    (repo / "data/gpu_pricing/snapshots/2026-11-18.json").write_text(
        '{"schema": "lantern-works-gpu-snapshot/1", "date": "2026-11-18", "rows": [{"advertiser": "AWS"}]}\n',
        encoding="utf-8")
    tar = _backup(tmp_path)
    man = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert man["commit"] is None
    assert man["uncommitted_files"] == ["data/gpu_pricing/aws.json", "data/gpu_pricing/snapshots/2026-11-18.json"]
    assert R.verify(tar, tmp_path / "w", tmp_path / "s.sqlite", root=repo)["problems"] == []  # self-consistent
    strict = R.verify(tar, tmp_path / "w2", tmp_path / "s2.sqlite", root=repo, require_git=True)["problems"]
    assert "manifest has no commit to compare against" in strict  # CI (--require-git) still fails closed


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
    assert "retention-days: 90" in wf and "restore_price_history.py restored --verify --require-git --expect-commit \"$GITHUB_SHA\"" in wf
    assert "--remote --output" in wf and "> /dev/null 2>&1" in wf  # presigned export URL never reaches the log
    assert "--symmetric" in wf and "shred -u" in wf                 # D1 exports encrypted before upload
