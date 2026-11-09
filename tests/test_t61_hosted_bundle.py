"""T61 (Gauge 1108 blocker): the hosted Worker bundles only .py modules, so core/assets/gpu_identity.json is NOT on disk
there. Build the bundle the way hosted/build.sh does (its own asset-embedding lines), delete the assets, and call
compare_gpu_prices in a fresh interpreter: prices must come back, never internal_error."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CALL = r'''
import json, sys, types
# the same stand-ins hosted/src/entry.py installs before importing server.py (no mcp SDK, no telemetry in the Worker)
class _FastMCP:
    def __init__(self, name, instructions=None):
        self.name, self._mcp_server = name, types.SimpleNamespace(version=None)
    def tool(self, annotations=None):
        return lambda fn: fn
for name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["mcp.server.fastmcp"].FastMCP = _FastMCP
_tel = types.ModuleType("mcp_server.telemetry"); _tel.record = lambda *a, **k: None
sys.modules["mcp_server.telemetry"] = _tel
from mcp_server import server
from core import gpu_identity
assert "assets" not in str(gpu_identity.ASSET) or not gpu_identity.ASSET.exists()
out = {"plain": server.compare_gpu_prices("H100", mode="full"),
       "filtered": server.compare_gpu_prices("H100", min_usable_memory_gb=40)}
print(json.dumps(out))
'''


def _bundle(tmp: Path, keep_embedded: bool) -> Path:
    h = tmp / "hosted"
    (h / "src" / "mcp_server").mkdir(parents=True)
    shutil.copytree(ROOT / "core", h / "src" / "core", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "mcp_server" / "server.py", h / "src" / "mcp_server" / "server.py")
    (h / "src" / "mcp_server" / "__init__.py").write_text("")
    # run exactly build.sh's asset-embedding lines (the python3 -c ... _asset_*.py writers)
    lines = [ln for ln in (ROOT / "hosted" / "build.sh").read_text().splitlines() if re.match(r"python3 -c .*_asset_gpu_", ln)]
    assert any("gpu_identity" in ln for ln in lines) and any("gpu_throughput" in ln for ln in lines), lines
    for ln in lines:
        subprocess.run(["sh", "-c", ln], cwd=h, check=True)
    assert (h / "src" / "core" / "_asset_gpu_identity.py").is_file()
    shutil.rmtree(h / "src" / "core" / "assets")  # Workers ship .py modules only
    if not keep_embedded:
        (h / "src" / "core" / "_asset_gpu_identity.py").unlink()
    return h / "src"


def _run(src: Path, tmp: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": str(src), "LANTERN_GPU_PRICES_FILE": str(ROOT / "api" / "v1" / "gpu-prices.json")}
    p = subprocess.run([sys.executable, "-c", CALL], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_hosted_bundle_compare_without_asset_file_uses_embedded_identity(tmp_path):
    out = _run(_bundle(tmp_path, keep_embedded=True), tmp_path)
    plain = out["plain"]
    assert plain["ok"] is True and plain["results"], plain.get("error")
    assert plain["model_identity"] and plain["model_identity"]["model"] == "H100"
    assert "model_identity_note" not in plain
    f = out["filtered"]
    assert f["ok"] is True and f["usable_memory_filter"]["unknown"] > 0


def test_hosted_bundle_compare_survives_missing_identity_entirely(tmp_path):
    out = _run(_bundle(tmp_path, keep_embedded=False), tmp_path)
    plain = out["plain"]
    assert plain["ok"] is True and plain["results"], plain.get("error")  # prices still returned, no internal_error
    assert plain["model_identity"] is None and "unavailable" in plain["model_identity_note"]
    f = out["filtered"]  # filter on: never fatal, every row unknown, nothing matched on nominal memory
    assert f["ok"] is True and f["results"] == [] and f["usable_memory_filter"]["identity_unavailable"] is True
    assert f["usable_memory_filter"]["matched"] == 0 and f["usable_memory_filter"]["unknown"] > 0
    assert "model_identity_note" in f  # brief mode keeps the note
