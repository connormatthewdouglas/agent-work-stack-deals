#!/usr/bin/env python3
"""v3.3d standalone: prepush must verify the matched set before pruning/rewriting. Runs on a temp copy of $SCOUT_DIR/out only."""
import json, os, subprocess, tempfile, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scout_io
# ---- 18 (v3.3d): tampered file + expired row -> prepush exits 3 BEFORE any rewrite (no laundering through a new manifest)
import hashlib as _hl
_here = os.path.dirname(os.path.abspath(__file__)); _src = os.path.join(os.environ.get("SCOUT_DIR", _here), "out")
_d = tempfile.mkdtemp()
for _f in ("availability_v2_latest.json", "feed_enriched_v2_latest.json", "availability_v2_latest.csv", "feed_enriched_v2_latest.csv", "latest_manifest.json"):
    if os.path.exists(os.path.join(_src, _f)): shutil.copy(os.path.join(_src, _f), _d)
assert scout_io.verify_generation(_d) == [], "precondition: copied set must verify"
_a = json.load(open(_d + "/availability_v2_latest.json"))
_reg = [r for r in _a["rows"] if r.get("region") not in (None, "all")]
_a["rows"][0]["hourly_usd"] = 0.01  # tamper
(_reg[0] if _reg else _a["rows"][1])["availability_expires_at"] = "2020-01-01T00:00:00Z"  # expired row prepush would prune
json.dump(_a, open(_d + "/availability_v2_latest.json", "w"))
_snap = lambda: {f: (_hl.sha256(open(os.path.join(_d, f), "rb").read()).hexdigest(), os.stat(os.path.join(_d, f)).st_mtime_ns) for f in sorted(os.listdir(_d))}
_before = _snap()
_p = subprocess.run(["python3", os.path.join(_here, "scout_io.py"), _d], capture_output=True, text=True, timeout=60, env=dict(os.environ, NO_PUSH="1", PUSH_DRY_RUN="1"))
assert _p.returncode == 3 and "not a matched set" in _p.stdout and "dropped" not in _p.stdout, (_p.returncode, _p.stdout, _p.stderr)
assert _snap() == _before, "files were rewritten"
assert scout_io.verify_generation(_d) != []  # still detectably tampered
shutil.rmtree(_d)
print("test_v33d_tamper OK")
