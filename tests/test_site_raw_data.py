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
