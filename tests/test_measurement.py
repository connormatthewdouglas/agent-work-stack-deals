"""T51: house/CI tagging, ua_class buckets, no raw IP/UA stored, utm on outbound links."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "hosted/src/entry.py").read_text()


def _fns():
    tree = ast.parse(SRC)
    keep = [n for n in tree.body if (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("HOUSE_UA", "BOT_RE", "MCP_CLIENTS") for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "_ua_class")]
    ns = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "entry", "exec"), ns)
    return ns["_ua_class"]


def test_ua_classes():
    c = _fns()
    assert c("lantern-works-ci") == "ci"
    assert c("lantern-works-gauge/2") == "house"
    assert c("Mozilla/5.0 (compatible; Googlebot/2.1)") == "known-bot"
    assert c("lantern-works-deals-mcp/0.3.40 (pypi-client)") == "mcp:lantern-works-pypi"
    assert c("claude-code/1.0") == "mcp:claude"
    assert c("Mozilla/5.0 (X11; Linux) Firefox/130") == "browser"
    assert c("") == "other" and c("curl/8") == "other"


def test_hits_store_no_raw_ip_or_ua():
    insert = re.search(r'INSERT INTO hits\(([^)]*)\)', SRC).group(1)
    assert "ip" not in insert.replace("ua_class", "") and "agent" not in insert
    assert "HITS_RETENTION_DAYS = 120" in SRC


def test_outbound_utm_and_client_ua():
    assert 'searchParams.set("utm_source","lanternworks")' in (ROOT / "scripts/site_ui.py").read_text()
    from core import USER_AGENT
    assert USER_AGENT.endswith("(pypi-client)")
