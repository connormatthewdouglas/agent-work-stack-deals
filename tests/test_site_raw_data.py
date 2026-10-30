import pathlib
import json, os, shutil, subprocess, sys
S = os.path.join(os.path.dirname(__file__), "..", "scripts", "guard_site_raw_data.py")
def test_raw_data_removed_and_check_fails_if_it_reappears(tmp_path):
    (tmp_path / "data/gpu_pricing").mkdir(parents=True)
    (tmp_path / "data/gpu_pricing/oblivus.json").write_text(json.dumps({"rows": [{"gpu": "A100", "in_stock": True}]}))
    (tmp_path / "data/deal_gotchas.json").write_text(json.dumps({"x": {"note": "n", "in_stock": True}}))
    assert subprocess.run([sys.executable, S, "--check", str(tmp_path)]).returncode == 1
    assert subprocess.run([sys.executable, S, str(tmp_path)]).returncode == 0
    assert not (tmp_path / "data/gpu_pricing").exists()
    assert json.loads((tmp_path / "data/deal_gotchas.json").read_text()) == {"x": {"note": "n"}}
    assert subprocess.run([sys.executable, S, "--check", str(tmp_path)]).returncode == 0

def test_tampered_manifest_in_subfolder_fails(tmp_path):  # re23 Q2: Gauge's tamper of mcp/tools.manifest.json
    root = pathlib.Path(__file__).resolve().parent.parent
    (tmp_path / "mcp").mkdir()
    m = json.loads((root / "mcp/tools.manifest.json").read_text())
    (tmp_path / "mcp/tools.manifest.json").write_text(json.dumps(m))
    assert subprocess.run([sys.executable, S, "--check", str(tmp_path)]).returncode == 0
    m["in_stock"] = True
    (tmp_path / "mcp/tools.manifest.json").write_text(json.dumps(m))
    assert subprocess.run([sys.executable, S, "--check", str(tmp_path)]).returncode == 1
    (tmp_path / "plugins/x").mkdir(parents=True)
    (tmp_path / "mcp/tools.manifest.json").write_text(json.dumps({"tools": []}))
    (tmp_path / "plugins/x/mcp.json").write_text(json.dumps({"a": [{"availability": {"in_stock": True}}]}))
    assert subprocess.run([sys.executable, S, "--check", str(tmp_path)]).returncode == 1
    (tmp_path / "api/v1").mkdir(parents=True)  # guarded feeds are exempt
    (tmp_path / "plugins/x/mcp.json").write_text("{}")
    (tmp_path / "api/v1/gpu-prices.json").write_text(json.dumps({"rates": [{"in_stock": True}]}))
    assert subprocess.run([sys.executable, S, "--check", str(tmp_path)]).returncode == 0
