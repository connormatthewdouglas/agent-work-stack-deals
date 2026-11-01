import json, re, pathlib
R = pathlib.Path(__file__).resolve().parent.parent
def _pkg_version():
    for p in [R / "pyproject.toml", R / "mcp_server" / "pyproject.toml"]:
        if p.exists():
            m = re.search(r'^version\s*=\s*"([^"]+)"', p.read_text(), re.M)
            if m: return m.group(1)
def test_lhm_plugin_version_matches_package():  # re22 Q3
    assert json.loads((R / "lhm.plugin.json").read_text())["version"] == _pkg_version()


def _readme_versions():
    """Every 'vX.Y.Z' in the README headings that state the package version (Gauge rel041 fix 1)."""
    out = {}
    for rel, line in (("README.md", "## MCP server ("), ("mcp_server/README.md", "# Lantern Works GPU prices")):
        hits = [l for l in (R / rel).read_text().splitlines() if l.startswith(line)]
        assert hits, f"{rel}: version heading not found"
        out[rel] = [v for l in hits for v in re.findall(r"\bv(\d+\.\d+\.\d+)\b", l)]
    return out


def test_readme_versions_match_pyproject():
    want = _pkg_version()
    for rel, vs in _readme_versions().items():
        assert vs and all(v == want for v in vs), (rel, vs, want)


def test_mcp_readme_lists_every_tool():
    """mcp_server/README.md (the PyPI long description) has a Tools-table row per registered tool."""
    src = (R / "mcp_server" / "server.py").read_text()
    tools = re.findall(r"@mcp\.tool\([^\n]*\)\s*\n(?:@\w+\s*\n)*def (\w+)\(", src)
    readme = (R / "mcp_server" / "README.md").read_text()
    assert len(tools) == 9, tools
    missing = [t for t in tools if f"| `{t}` |" not in readme]
    assert not missing, missing
