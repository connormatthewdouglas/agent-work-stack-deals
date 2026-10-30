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
