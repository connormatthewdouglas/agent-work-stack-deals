import hashlib, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_importer_refuses_sha256_mismatch(tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps({"version": "3.1", "generation_id": "x", "rows": []}))
    good = hashlib.sha256(feed.read_bytes()).hexdigest()
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": {"sha256": "0" * 64}}}))
    env = dict(os.environ, LW_SCOUT_MANIFESTS=str(bad))
    r = subprocess.run([sys.executable, "-c", "import runpy,sys;sys.argv=['x',sys.argv[1]];"
                        "import scripts.import_scout_availability as m;m.verify_manifests(open(sys.argv[1],'rb').read())", str(feed)],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "sha256 mismatch" in r.stderr
    bad.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": good}}))
    r = subprocess.run(r.args, cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_31_plus_requires_manifest(tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps({"version": "3.2", "rows": []}))
    env = {k: v for k, v in os.environ.items() if k != "LW_SCOUT_MANIFESTS"}
    r = subprocess.run([sys.executable, "scripts/import_scout_availability.py", str(feed)], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "no manifest" in r.stderr


def test_held_and_expired_rows_never_available():
    from datetime import datetime, timezone
    from core import gpu_availability as g
    now = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    held = g._scout("Vast.ai", {"in_stock": True, "availability_checked_at": "2026-10-30T14:50:00Z",
                                "availability_expires_at": "2026-10-30T18:50:00Z", "feed_status": "held_below_min_offers"})
    held = g.stale_guard(held, now)
    assert held["in_stock"] is None and held["feed_status"] == "held_below_min_offers" and held["availability_expires_at"]
    short = g._scout("Verda", {"in_stock": True, "availability_checked_at": "2026-10-30T14:40:00Z",
                               "availability_expires_at": "2026-10-30T14:55:00Z", "feed_status": None})
    assert short["availability_expires_at"] == "2026-10-30T14:55:00Z"
    out = g.stale_guard(short, now)
    assert out["in_stock"] is None and out["availability_expires_at"] == "2026-10-30T14:55:00Z"
    ok = g.stale_guard(short, datetime(2026, 10, 30, 14, 50, tzinfo=timezone.utc))
    assert ok["in_stock"] is True
