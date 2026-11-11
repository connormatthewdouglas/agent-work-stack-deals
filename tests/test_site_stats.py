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
    assert w["external_mcp_tool_calls"] == 2 and w["telemetry_tool_calls"] == 0 and w["beacon_out_events"] == 4
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
    assert rep["weeks"][0]["beacon_out_events"] == 1  # pre-T135 outbound_clicks was the beacon figure


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


def test_generated_at_is_the_collection_clock():
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    rep = S.build({"rows": [{"day": "2026-11-09", "tool": "a", "ref": "x", "n": 1}]}, {}, None, 12, now)
    assert rep["generated_at"] == "2026-11-09T12:00:00Z"
    assert "receipts_funnel" in rep["weeks"][0]


def test_weekly_workflow_rebases_before_push():
    text = (Path(__file__).resolve().parents[1] / ".github/workflows/site-stats.yml").read_text(encoding="utf-8")
    assert "site_stats.py" in text and "git rebase origin/main" in text and "git push origin HEAD:main" in text
    assert text.index("git rebase origin/main") < text.index("git push origin HEAD:main")


def test_p8_demand_daily_copied_bucketed_only():
    now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    hosted = {"rows": [{"day": "2026-11-10", "ref": "x", "n": 1}], "demand_daily": [
        {"day": "2026-11-10", "tool": "compare_gpu_prices", "gpu_family": "H100", "region_group": "any", "price_tier": "on-demand",
         "cheapest_provider": "Hyperstack", "n": 4, "extra": "dropped"},
        {"day": "2026-06-01", "tool": "compare_gpu_prices", "gpu_family": "A100", "region_group": "any", "price_tier": "on-demand",
         "cheapest_provider": "X", "n": 1}]}
    rep = S.build(hosted, {}, None, 12, now)
    S.add_demand(rep, hosted, now)
    assert rep["demand_daily"] == [{"day": "2026-11-10", "tool": "compare_gpu_prices", "gpu_family": "H100", "region_group": "any",
                                    "price_tier": "on-demand", "cheapest_provider": "Hyperstack", "n": 4}]
    assert rep["demand_daily_null_reason"] is None and "raw arguments" in rep["sources"]["demand_daily"]


def test_p8_demand_null_with_reason_before_deploy():
    now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    rep = S.build({"rows": [{"day": "2026-11-10", "ref": "x", "n": 1}]}, {}, None, 12, now)
    S.add_demand(rep, {"rows": []}, now)
    assert rep["demand_daily"] is None and "migration 0005" in rep["demand_daily_null_reason"]

def test_t135_one_agreed_click_count_bots_and_house_excluded():
    """Nov 2 week: 19 feed /go/ redirects (no UA class yet) vs 0 beacon events. One agreed count, nothing hidden."""
    g = [{"count": 3, "dimensions": {"date": "2026-11-02", "requestPath": "/"}}]
    rep = S.build({"rows": [{"day": "2026-11-02", "ref": "x", "n": 1}]}, {}, None, 12, datetime.now(timezone.utc), S.rum_weekly(g))
    legacy = [{"day": "2026-11-03", "provider": f"P{i}", "src": "feed", "ref": "none", "n": 2 if i < 2 else 1} for i in range(17)]
    S.add_go_clicks(rep, {"rows": legacy + [
        {"day": "2026-11-04", "provider": "P0", "src": "mcp", "ref": "none", "ua_class": "browser", "n": 3},
        {"day": "2026-11-04", "provider": "P0", "src": "site", "ref": "none", "ua_class": "bot", "n": 5},
        {"day": "2026-11-04", "provider": "P1", "src": "feed", "ref": "none", "ua_class": "script", "n": 4},
        {"day": "2026-11-04", "provider": "P1", "src": "feed", "ref": "none", "ua_class": "prefetch", "n": 1},
        # Mart's post-deploy verification click: /go/<id>?src=mcp-test&ref=house-t135 with a browser UA
        {"day": "2026-11-04", "provider": "P0", "src": "mcp-test", "ref": "house-t135", "ua_class": "browser", "n": 1}]})
    w = rep["weeks"][0]
    c = w["clicks"]
    assert c["count"] == 22 == w["outbound_clicks"]  # 19 unclassified legacy + 3 browser
    assert c["unclassified_ua"] == 19
    assert c["excluded"] == {"bot": 5, "script": 4, "prefetch": 1, "house": 1}
    assert c["by_source"] == {"feed": 19, "mcp": 3}
    assert c["by_provider"]["P0"] == {"feed": 2, "mcp": 3} and w["go_clicks_by_provider"] is c["by_provider"]
    assert sum(sum(v.values()) for v in c["by_provider"].values()) == c["count"]
    assert w["test_go_clicks_by_provider"] == {"P0": {"mcp": 1}}
    assert w["beacon_out_events"] == 0  # the beacon figure is kept apart, not the click count
    assert "19 /go/ redirects" in rep["sources"]["clicks_reconciliation"]
    assert '"ua"' not in json.dumps(rep) and "Mozilla" not in json.dumps(rep)


def test_t135_clicks_null_with_reason_when_source_down():
    rep = S.build({"rows": [{"day": "2026-11-02", "ref": "x", "n": 1}]}, {}, None, 12, datetime.now(timezone.utc))
    S.add_go_clicks(rep, {"error": "URLError"})
    w = rep["weeks"][0]
    assert w["clicks"] is None and w["outbound_clicks"] is None and w["clicks_null_reason"]


def test_t136_agent_query_to_click_excludes_house_and_bots():
    hosted = {"rows": [{"day": "2026-11-09", "ref": "x", "n": 1}],
              "hits": [{"day": "2026-11-09", "kind": "tool", "name": "a", "ref": "none", "ua_class": "mcp:claude", "src_class": "other", "n": 40},
                       {"day": "2026-11-10", "kind": "tool", "name": "a", "ref": "lobehub", "ua_class": "other", "src_class": "github-actions", "n": 10},
                       {"day": "2026-11-10", "kind": "tool", "name": "a", "ref": "none", "ua_class": "house", "src_class": "house", "n": 99},
                       {"day": "2026-11-10", "kind": "tool", "name": "a", "ref": "t41", "ua_class": "other", "src_class": "other", "n": 7},
                       {"day": "2026-11-10", "kind": "tool", "name": "a", "ref": "none", "ua_class": "known-bot", "src_class": "other", "n": 5},
                       {"day": "2026-11-10", "kind": "feed", "name": "/api", "ref": "none", "ua_class": "other", "src_class": "other", "n": 50}]}
    rep = S.build(hosted, {}, None, 12, datetime.now(timezone.utc))
    S.add_go_clicks(rep, {"rows": [{"day": "2026-11-10", "provider": "A", "src": "mcp", "ref": "none", "ua_class": "browser", "n": 2},
                                   {"day": "2026-11-10", "provider": "A", "src": "mcp-test", "ref": "house-t136", "ua_class": "browser", "n": 3},
                                   {"day": "2026-11-10", "provider": "A", "src": "mcp", "ref": "none", "ua_class": "bot", "n": 4},
                                   {"day": "2026-11-10", "provider": "A", "src": "site", "ref": "none", "ua_class": "browser", "n": 6}]})
    S.add_agent_query_to_click(rep, hosted)
    q = rep["weeks"][0]["agent_query_to_click"]
    assert q == {"agent_tool_calls": 50, "agent_mcp_clicks": 2, "rate": 0.04, "null_reason": None}
    assert "house" in rep["sources"]["agent_query_to_click"]


def test_t136_query_to_click_null_with_reason():
    rep = S.build({"rows": [{"day": "2026-11-09", "ref": "x", "n": 1}]}, {}, None, 12, datetime.now(timezone.utc))
    S.add_go_clicks(rep, {"rows": []})
    S.add_agent_query_to_click(rep, {"hits": []})
    q = rep["weeks"][0]["agent_query_to_click"]
    assert q["rate"] is None and q["agent_tool_calls"] == 0 and q["null_reason"]
