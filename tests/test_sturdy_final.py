"""Sturdiness final follow-up. Bjorn 2026-11-17: a vendor in meta.nonfatal_errors with last good rows on main
warns as stale and hard-fails after 7 days; an empty vendor with no nonfatal entry fails. Scout snapshot > 168h
fails. A backup manifest pinned to a different commit fails the restore."""
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backup_price_history as B  # noqa: E402
import check_scout_snapshot_rows as C  # noqa: E402
import restore_price_history as R  # noqa: E402

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def _iso(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


SNAP = {"rows": [{"vendor": "Civo", "availability_checked_at": _iso(1)}]}


def _main_rows(hyperstack_age_h):
    return {"rows": [{"vendor": "Civo", "availability_checked_at": _iso(2)},
                     {"vendor": "Hyperstack", "availability_checked_at": _iso(hyperstack_age_h)}]}


def test_nonfatal_vendor_at_40h_warns():
    f, w = C.check(SNAP, _main_rows(40), nonfatal={"Hyperstack": "RuntimeError: 503"}, now=NOW)
    assert f == [] and len(w) == 1 and "Hyperstack" in w[0] and "40.0h" in w[0]


def test_nonfatal_vendor_at_200h_fails():
    f, w = C.check(SNAP, _main_rows(200), nonfatal={"Hyperstack": "RuntimeError: 503"}, now=NOW)
    assert w == [] and len(f) == 1 and "200.0h" in f[0] and "hard cap" in f[0]


def test_vendor_at_zero_without_nonfatal_entry_fails():
    f, w = C.check(SNAP, _main_rows(2), nonfatal={"Lambda": "second read failed"}, now=NOW)
    assert w == [] and len(f) == 1 and "no nonfatal_errors entry" in f[0] and "Hyperstack" in f[0]
    assert C.check(SNAP, _main_rows(2), now=NOW)[0]  # no nonfatal_errors at all


def _import_block() -> str:
    sh = (ROOT / "scripts" / "check_latest_scout_import.sh").read_text(encoding="utf-8")
    a = sh.index("  if grep -Eq '^Scout snapshot ")
    b = sh.index("  exit 1\nfi\n", a)
    return sh[a:b] + "  exit 1\n"


def _run_block(tmp_path, line):
    (tmp_path / "import.log").write_text(line + "\n")
    p = subprocess.run(["sh", "-c", "T=\"$1\"; " + _import_block(), "sh", str(tmp_path)], capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin"})
    return p.returncode, p.stdout


def test_scout_snapshot_at_200h_fails_and_40h_warns(tmp_path):
    rc, out = _run_block(tmp_path, "Scout snapshot 2026-11-09T04:00:00Z is 200.0h old (> 8h); refusing to import")
    assert rc == 1 and "168h hard cap" in out
    rc, out = _run_block(tmp_path, "Scout snapshot 2026-11-09T04:00:00Z is 1130.4h old (> 8h); refusing to import")
    assert rc == 1
    rc, out = _run_block(tmp_path, "Scout snapshot 2026-11-15T20:00:00Z is 40.0h old (> 8h); refusing to import")
    assert rc == 0 and "LATEST_SCOUT_IMPORT_STALE_SKIPPED" in out
    rc, _ = _run_block(tmp_path, "Scout snapshot (no checked_at) is ?h old (> 8h); refusing to import")
    assert rc == 1


def test_restore_with_mismatched_commit_fails(tmp_path):
    snaps = sorted((ROOT / "data/gpu_pricing/snapshots").glob("*.json"))
    now = datetime.fromisoformat(snaps[-1].stem).replace(tzinfo=timezone.utc) + timedelta(hours=12)
    tar = B.build(ROOT, tmp_path / "out", None, None, now)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for i, (want, ok) in enumerate(((commit, True), ("0" * 40, False), ("", False))):
        w = tmp_path / f"w{i}"
        w.mkdir()
        res = R.verify(tar, w, w / "s.sqlite", expect_commit=want)
        mism = [p for p in res["problems"] if p.startswith("manifest commit")]
        assert (not mism) if ok else mism, (want, res["problems"])
    assert re.search(r'--expect-commit "\$GITHUB_SHA"',
                     (ROOT / ".github/workflows/price-history-backup.yml").read_text(encoding="utf-8"))
