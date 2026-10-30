import json, re, pathlib
R = pathlib.Path(__file__).resolve().parent.parent
def _pkg_version():
    for p in [R / "pyproject.toml", R / "mcp_server" / "pyproject.toml"]:
        if p.exists():
            m = re.search(r'^version\s*=\s*"([^"]+)"', p.read_text(), re.M)
            if m: return m.group(1)
def test_lhm_plugin_version_matches_package():  # re22 Q3
    assert json.loads((R / "lhm.plugin.json").read_text())["version"] == _pkg_version()
