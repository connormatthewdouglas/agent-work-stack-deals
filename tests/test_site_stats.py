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


def test_rum_weekly_refs_and_pages():
    g = [{"count": 5, "dimensions": {"date": "2026-11-02", "requestPath": "/"}},
         {"count": 2, "dimensions": {"date": "2026-11-02", "requestPath": "/e/ref/forum-hn/"}},
         {"count": 1, "dimensions": {"date": "2026-11-02", "requestPath": "/e/out/deal-x/"}},
         {"count": 3, "dimensions": {"date": "2026-11-02", "requestPath": "/e/search/"}}]
    w = S.rum_weekly(g)["2026-W45"]
    assert w == {"page_views": 5, "visits_by_ref": {"forum-hn": 2}, "outbound_clicks": 1, "receipts_page_views": 0}


def test_no_token_is_null_with_reason_not_zero(monkeypatch):
    monkeypatch.delenv("CF_API_TOKEN", raising=False)
    groups, reason = S.fetch_rum()
    assert groups is None and "box-side" in reason
    from datetime import datetime, timezone
    rep = S.build({"rows": [{"day": "2026-11-02", "ref": "install", "n": 1}]}, {}, None, 12, datetime.now(timezone.utc), None, reason)
    wk = rep["weeks"][0]
    assert wk["page_views"] is None and wk["visits_by_ref"] is None and reason in wk["visits_null_reason"]
    assert wk["installs_by_ref"] is None and "install id" in wk["installs_null_reason"]


def test_weeks_before_beacon_are_null_not_zero():
    from datetime import datetime, timezone
    rep = S.build({"rows": [{"day": "2026-10-28", "ref": "x", "n": 1}, {"day": "2026-11-02", "ref": "x", "n": 1}]}, {}, None, 12,
                  datetime.now(timezone.utc), {}, "")
    w = {x["week"]: x for x in rep["weeks"]}
    assert w["2026-W44"]["page_views"] is None and "2026-11-02" in w["2026-W44"]["visits_null_reason"]
    assert w["2026-W45"]["page_views"] == 0 and w["2026-W45"]["visits_by_ref"] == {}


def test_carry_forward_keeps_box_filled_page_views(tmp_path):
    import site_stats as ss
    old = tmp_path / "stats.json"
    old.write_text(json.dumps({"weeks": [{"week": "2026-W45", "page_views": 12, "visits_by_ref": {"forum-x": 2},
                                          "visits_null_reason": None, "outbound_clicks": 1}]}))
    rep = {"weeks": [{"week": "2026-W45", "page_views": None, "visits_by_ref": None, "visits_null_reason": "x",
                      "outbound_clicks": None}, {"week": "2026-W46", "page_views": None}]}
    ss._carry_forward(rep, old)
    assert rep["weeks"][0]["page_views"] == 12 and rep["weeks"][0]["visits_by_ref"] == {"forum-x": 2}
    assert rep["weeks"][1]["page_views"] is None


def test_go_clicks_per_provider_test_traffic_apart():
    rep = S.build({"rows": [{"day": "2026-11-02", "ref": "x", "n": 1}]}, {}, None, 12, datetime.now(timezone.utc))
    S.add_go_clicks(rep, {"rows": [{"day": "2026-11-03", "provider": "A", "src": "site", "ref": "none", "n": 2},
                                   {"day": "2026-11-03", "provider": "A", "src": "mcp-test", "ref": "none", "n": 1},
                                   {"day": "2026-11-03", "provider": "B", "src": "feed", "ref": "qa", "n": 1}]})
    w = rep["weeks"][0]
    assert w["go_clicks_by_provider"] == {"A": {"site": 2}}
    assert w["test_go_clicks_by_provider"] == {"A": {"mcp": 1}, "B": {"feed": 1}}


def test_receipts_funnel_separate_from_gpu():
    g = [{"count": 4, "dimensions": {"date": "2026-11-03", "requestPath": "/receipts/"}},
         {"count": 6, "dimensions": {"date": "2026-11-03", "requestPath": "/gpu/h100-rental-price/"}},
         {"count": 2, "dimensions": {"date": "2026-11-03", "requestPath": "/e/ref/receipts-colony/"}},
         {"count": 3, "dimensions": {"date": "2026-11-03", "requestPath": "/e/ref/github-readme/"}}]
    hosted = {"rows": [{"day": "2026-11-03", "tool": "a", "ref": "receipts-colony", "n": 1}, {"day": "2026-11-03", "tool": "a", "ref": "x", "n": 9}],
              "hits": [{"day": "2026-11-03", "kind": "initialize", "name": "m", "ref": "receipts", "n": 2}]}
    w = S.build(hosted, {}, None, 12, datetime.now(timezone.utc), S.rum_weekly(g))["weeks"][0]
    f = w["receipts_funnel"]
    assert f["page_views"] == 4 and f["visits_by_ref"] == {"receipts-colony": 2}
    assert f["mcp_tool_calls_by_ref"] == {"receipts-colony": 1} and f["mcp_initialize_by_ref"] == {"receipts": 2}
    assert f["json_fetches"] is None and f["json_fetches_null_reason"] and f["inquiries"] is None
    assert w["page_views"] == 10  # existing totals unchanged (additive)


def test_receipts_funnel_null_with_reason_without_beacon():
    w = S.build({"rows": [{"day": "2026-11-03", "tool": "a", "ref": "x", "n": 1}]}, {}, None, 12, datetime.now(timezone.utc))["weeks"][0]
    f = w["receipts_funnel"]
    assert f["page_views"] is None and f["page_views_null_reason"] and f["visits_by_ref"] is None
