import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import site_stats as S

def test_weekly_aggregate_no_pii():
    hosted = {"rows": [{"day": "2026-11-02", "tool": "a", "ref": "ci", "n": 3}, {"day": "2026-11-03", "tool": "b", "ref": "x", "n": 2},
                       {"day": "2026-11-03", "tool": "b", "ref": "none", "n": 5}, {"day": "2026-11-03", "tool": "b", "ref": "t17-openai-agents", "n": 1},
                       {"day": "2026-11-03", "tool": "b", "ref": "t41", "n": 1}],
              "hits": [{"day": "2026-11-02", "kind": "feed", "name": "/api", "ref": "x", "ua_class": "u", "src_class": "s", "n": 5}],
              "watches": {"weekly_per_key": [{"key": "k_abc"}]}}
    rep = S.build(hosted, {"rows": [{"day": "2026-11-02", "version": "0.0.0", "n": 9}]}, {"2026-W45": 4}, 12, datetime.now(timezone.utc))
    w = rep["weeks"][0]
    assert w["week"] == "2026-W45" and w["mcp_tool_calls_by_ref"]["ci"] == 3
    assert w["untagged_mcp_tool_calls"] == 5
    assert w["external_mcp_tool_calls"] == 2 and w["telemetry_tool_calls"] == 0 and w["outbound_clicks"] == 4
    text = json.dumps(rep)
    for bad in ("k_abc", "ua_class", "src_class", "ip", "email"):
        assert f'"{bad}"' not in text

def test_committed_stats_json_shape():
    p = Path(__file__).resolve().parents[1] / "stats.json"
    d = json.loads(p.read_text())
    assert d["schema"] == "lantern-works-site-stats/1" and isinstance(d["weeks"], list)
