#!/usr/bin/env python3
"""Brain #247 task 1: public /stats.json with weekly aggregate ref= counts. Aggregate counts only, never PII.

Sources (all aggregate, no visitor-level data):
  - hosted MCP worker /stats.json: tool calls per UTC day x tool x ref, and feed/initialize hits per day x kind x ref
  - opt-in telemetry worker /v1/stats: tool calls per day x tool x version (test version 0.0.0 dropped)
  - Cloudflare Web Analytics beacon (/e/out/<id> virtual page views = outbound clicks): weekly totals only, and only
    when CF_API_TOKEN, CF_ACCOUNT_ID and CF_SITE_TAG are set; otherwise reported as not available
Rows are rolled up to ISO weeks (YYYY-Www). No per-caller or per-key data is published; /go/ redirect clicks are published per provider x src (aggregate).
  python3 scripts/site_stats.py [--out stats.json] [--weeks 12]
"""
from __future__ import annotations

import argparse
import json
import re
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/stats.json"
TELEMETRY = "https://lantern-works-telemetry.lantern-works.workers.dev/v1/stats?days=120"
GO_CLICKS = "https://lantern-works-telemetry.lantern-works.workers.dev/v1/clicks?days=120"
INTERNAL_REFS = {"ci", "qa", "test", "smoke"}  # plus any ref starting with "house-": our own checks


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "LanternWorks-site-stats"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {"error": type(e).__name__}


def week(day: str) -> str:
    y, w, _ = date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


TEST_REF_RE = re.compile(r"^t\d+(-.*)?$")  # QA harness tags: t41, t17-openai-agents, ...


def internal(ref: str) -> bool:
    return ref in INTERNAL_REFS or ref.startswith("house-") or bool(TEST_REF_RE.match(ref))


def _add(d: dict, k, n: int):
    d[k] = d.get(k, 0) + int(n or 0)


REF_PATH_RE = re.compile(r"^/e/ref/([a-z0-9][a-z0-9_-]{0,31})/?$")
OUT_PATH_RE = re.compile(r"^/e/out/[a-z0-9-]{1,80}/?$", re.I)
RECEIPTS_PATH_RE = re.compile(r"^/receipts(/|$)")
RECEIPTS_REF_RE = re.compile(r"^receipts(-|$)")  # T55: Receipts links carry ?ref=receipts-<channel>; GPU traffic never uses it
RECEIPTS_FUNNEL_NOTE = ("T55: Receipts (MCP test summaries) measured apart from GPU demand. page_views = beacon views of /receipts/ "
                        "pages; visits_by_ref / mcp_initialize_by_ref / mcp_tool_calls_by_ref = refs matching receipts or "
                        "receipts-<channel> only. json_fetches and link_visits are counted server-side by the hosted worker (see "
                        "sources.receipts_hosted); direct GitHub Pages fetches publish no counts. Independent inquiries arrive by email and are not published here (null).")
RECEIPTS_JSON_NULL = "not measurable: /api/v1/receipts.json is served by GitHub Pages only (no request counts); not proxied by the hosted worker"
RECEIPTS_INQ_NULL = "not published: inquiries arrive by email; counts stay private (no PII in stats.json)"
BEACON_SINCE_WEEK = "2026-W45"  # site b392c8b3... beacon token 327dc277... shipped 2026-11-02
BEACON_SINCE_REASON = "not measured: this Web Analytics site's beacon went live on 2026-11-02 (ISO week 2026-W45)"
INSTALLS_NULL_REASON = ("not measurable: the opt-in telemetry worker records day x tool x version only, with no install id "
                        "or ref; an install id needs the owner's approval. Hosted connects by ref are in mcp_initialize_by_ref.")


RECEIPTS_JSON_PATHS = ("/api/v1/receipts.json", "/api/v1/receipts-proof-pack.json")
RECEIPTS_HOSTED_NOTE = ("T137: json_fetches counts api/v1/receipts.json and receipts-proof-pack.json fetched through the hosted worker "
                        "(https://lantern-works-mcp.lantern-works.workers.dev/api/v1/receipts.json?ref=receipts-<channel>); direct "
                        "GitHub Pages fetches publish no counts and are not included. link_visits counts tagged Receipts links "
                        "through the hosted worker's /receipts/ redirect (302 to the same page on the site). Both exclude house "
                        "traffic (src_class house or a house ref) and known bots, and are split by ref.")


def add_receipts_hosted(rep: dict, hosted: dict) -> None:
    """T137: server-side Receipts counts from the hosted worker's hits (aggregate day x kind x path x ref x classes)."""
    rep["sources"]["receipts_hosted"] = RECEIPTS_HOSTED_NOTE
    if "error" in hosted:
        return  # stays null with its reason
    per: dict = {}
    for h in hosted.get("hits") or []:
        kind, name = h.get("kind"), str(h.get("name") or "")
        key = ("json" if kind == "feed" and name in RECEIPTS_JSON_PATHS else "link" if kind == "receipts" else None)
        if key is None:
            continue
        ref, srcc, uac = str(h.get("ref") or "none"), str(h.get("src_class") or ""), str(h.get("ua_class") or "")
        if srcc == "house" or uac in ("house", "ci", "known-bot") or internal(ref):
            continue
        w = per.setdefault(week(h["day"]), {"json": {}, "link": {}})
        _add(w[key], ref, h.get("n"))
    for w in rep["weeks"]:
        f = w.get("receipts_funnel")
        if f is None:
            continue
        p = per.get(w["week"], {"json": {}, "link": {}})
        srt = lambda d: dict(sorted(d.items(), key=lambda x: (-x[1], x[0])))  # noqa: E731
        f.update(json_fetches=sum(p["json"].values()), json_fetches_by_ref=srt(p["json"]),
                 json_fetches_null_reason=None, link_visits=sum(p["link"].values()), link_visits_by_ref=srt(p["link"]))


def rum_weekly(groups: list[dict]) -> dict:
    """Cloudflare Web Analytics groups [{count, dimensions:{date, requestPath}}] -> {week: {page_views, visits_by_ref,
    outbound_clicks}}. page_views counts real pages only (virtual /e/ paths excluded); visits_by_ref counts the
    /e/ref/<ref>/ virtual view the beacon sends once per landing with ?ref= (pages built from rel055 on)."""
    w: dict = {}
    for g in groups:
        dim = g.get("dimensions") or {}
        path, day, n = dim.get("requestPath") or "", dim.get("date"), int(g.get("count") or 0)
        if not day:
            continue
        s = w.setdefault(week(day), {"page_views": 0, "visits_by_ref": {}, "outbound_clicks": 0, "receipts_page_views": 0})
        m = REF_PATH_RE.match(path)
        if m:
            _add(s["visits_by_ref"], m.group(1), n)
        elif OUT_PATH_RE.match(path):
            s["outbound_clicks"] += n
        elif not path.startswith("/e/"):
            s["page_views"] += n
            if RECEIPTS_PATH_RE.match(path):
                s["receipts_page_views"] = s.get("receipts_page_views", 0) + n
    return w


def build(hosted: dict, telemetry: dict, clicks: dict | None, weeks: int, now: datetime,
          rum: dict | None = None, rum_reason: str = "") -> dict:
    out: dict = {}

    def slot(w):
        return out.setdefault(w, {"week": w, "mcp_tool_calls_by_ref": {}, "feed_fetches_by_ref": {},
                                  "mcp_initialize_by_ref": {}, "external_mcp_tool_calls": 0, "untagged_mcp_tool_calls": 0,
                                  "telemetry_tool_calls": 0, "outbound_clicks": None, "beacon_out_events": None,
                                  "page_views": None, "visits_by_ref": None,
                                  "visits_null_reason": rum_reason or None, "installs_by_ref": None,
                                  "installs_null_reason": INSTALLS_NULL_REASON})

    for r in hosted.get("rows") or []:
        s, ref = slot(week(r["day"])), str(r.get("ref") or "none")
        _add(s["mcp_tool_calls_by_ref"], ref, r.get("n"))
        if ref == "none":
            s["untagged_mcp_tool_calls"] += int(r.get("n") or 0)
        elif not internal(ref):
            s["external_mcp_tool_calls"] += int(r.get("n") or 0)
    for h in hosted.get("hits") or []:
        key = {"feed": "feed_fetches_by_ref", "initialize": "mcp_initialize_by_ref"}.get(h.get("kind"))
        if key:
            _add(slot(week(h["day"]))[key], str(h.get("ref") or "none"), h.get("n"))
    for r in telemetry.get("rows") or []:
        if r.get("version") != "0.0.0":
            slot(week(r["day"]))["telemetry_tool_calls"] += int(r.get("n") or 0)
    for w, n in (clicks or {}).items():
        slot(w)["beacon_out_events"] = n
    for w, r in (rum or {}).items():
        s = slot(w)
        s["page_views"], s["beacon_out_events"] = r["page_views"], r["outbound_clicks"]
        s["visits_by_ref"] = dict(sorted(r["visits_by_ref"].items(), key=lambda x: (-x[1], x[0])))
        s["visits_null_reason"] = None
    if rum is not None:  # measured, so a week with no beacon rows is a real zero, from the beacon switch on
        for s in out.values():
            if s["week"] < BEACON_SINCE_WEEK and not rum.get(s["week"]):
                s["visits_null_reason"] = BEACON_SINCE_REASON
            elif s["page_views"] is None:
                s.update(page_views=0, visits_by_ref={}, beacon_out_events=s["beacon_out_events"] or 0, visits_null_reason=None)
    for s in out.values():
        r = (rum or {}).get(s["week"]) or {}
        measured = s["page_views"] is not None
        sel = lambda d: {k: v for k, v in sorted((d or {}).items(), key=lambda x: (-x[1], x[0])) if RECEIPTS_REF_RE.match(k)}
        s["receipts_funnel"] = {
            "page_views": int(r.get("receipts_page_views", 0)) if measured else None,
            "visits_by_ref": sel(s["visits_by_ref"]) if measured else None,
            "mcp_initialize_by_ref": sel(s["mcp_initialize_by_ref"]),
            "mcp_tool_calls_by_ref": sel(s["mcp_tool_calls_by_ref"]),
            "json_fetches": None, "json_fetches_null_reason": RECEIPTS_JSON_NULL,
            "json_fetches_by_ref": None, "link_visits": None, "link_visits_by_ref": None,
            "inquiries": None, "inquiries_null_reason": RECEIPTS_INQ_NULL,
            "page_views_null_reason": None if measured else (s["visits_null_reason"] or "Web Analytics not available this run"),
        }
    rows = sorted(out.values(), key=lambda s: s["week"], reverse=True)[:weeks]
    for s in rows:
        for k in ("mcp_tool_calls_by_ref", "feed_fetches_by_ref", "mcp_initialize_by_ref"):
            if s[k] is not None:
                s[k] = dict(sorted(s[k].items(), key=lambda x: (-x[1], x[0])))
    return {
        "schema": "lantern-works-site-stats/1",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Weekly (ISO week, UTC) aggregate counts only. No IP addresses, user agents, cookies, keys or per-caller "
                "data. ref is the ?ref= channel tag. Refs ci, qa, test, smoke, house-* and t<N>/t<N>-* are our own checks and are "
                "excluded from external_mcp_tool_calls. Calls with no ref are counted separately in untagged_mcp_tool_calls "
                "and may include our own checks. feed_fetches_by_ref counts only feed fetches through the hosted worker, not "
                "GitHub Pages feed hits. mcp_initialize_by_ref['mcp-registry'] is probably MCP Registry health checks, not users.",
        "sources": {
            "feed_fetches": "hosted worker only (lantern-works-mcp.lantern-works.workers.dev/api/...); GitHub Pages feed hits are not counted",
            "mcp_initialize_mcp_registry": "probably MCP Registry health checks, not users",
            "hosted_mcp": "https://lantern-works-mcp.lantern-works.workers.dev/stats" + ("" if "error" not in hosted else " (unavailable this run)"),
            "telemetry": "opt-in LANTERN_TELEMETRY=1 aggregate" + ("" if "error" not in telemetry else " (unavailable this run)"),
            "outbound_clicks": CLICKS_SOURCE,
            "beacon_out_events": ("Cloudflare Web Analytics beacon /e/out/ virtual page views (site JavaScript only), weekly total; "
                                  "a cross-check, not the click count" if (clicks is not None or rum is not None) else "not available this run (null)"),
            "clicks_reconciliation": CLICKS_RECONCILIATION,
            "page_views": ("Cloudflare Web Analytics beacon page views (site b392c8b3...), real pages only, weekly total" if rum is not None
                           else f"null: {rum_reason}"),
            "visits_by_ref": ("Cloudflare Web Analytics /e/ref/<ref>/ virtual views, sent once per landing with ?ref= by pages built "
                              "from 2026-11-02 (rel055) on; earlier weeks cannot show refs" if rum is not None else f"null: {rum_reason}"),
            "installs_by_ref": "null: " + INSTALLS_NULL_REASON,
            "receipts_funnel": RECEIPTS_FUNNEL_NOTE,
        },
        "weeks": rows,
    }


CLICKS_SOURCE = ("T135 agreed click count: server-side /go/<deal-id> redirects (telemetry worker D1, aggregate day x deal x "
                 "provider x src x ref x ua_class; no IPs, user agents or cookies), minus known bots, crawlers, link previews, "
                 "HTTP scripts and prefetches (ua_class bot|script|prefetch) and minus our own test traffic (src *-test or "
                 "internal ref). Per week in clicks {count, by_provider, by_source, excluded, unclassified_ua}.")
CLICKS_RECONCILIATION = ("T135: before Nov 11 2026, outbound_clicks was the Web Analytics beacon's /e/out/ count, which only fires "
                         "from site JavaScript, while go_clicks counted every server-side /go/ redirect (mostly src=feed). The week "
                         "of Nov 2 (2026-W45) had 19 /go/ redirects (all src=feed, no ref, 17 providers, Nov 6-7 UTC) and 0 beacon events, "
                         "so the two never measured the same thing. outbound_clicks now equals clicks.count; the beacon figure "
                         "is kept as beacon_out_events. Clicks recorded before the UA filter shipped have no UA class and are "
                         "counted but reported in clicks.unclassified_ua, not dropped or relabelled.")
EXCLUDED_UA = ("bot", "script", "prefetch")


def add_go_clicks(rep: dict, go: dict) -> None:
    """Per-provider /go/ redirect clicks by src (site|mcp|feed|readme), weekly, and the one agreed weekly click count (T135).
    src ending -test and internal refs are our own test traffic (kept in test_go_clicks_by_provider); ua_class
    bot|script|prefetch are automated fetches (counted in clicks.excluded). Neither is in clicks.count or go_clicks_by_provider."""
    ok = "error" not in go
    rep["sources"]["go_clicks"] = ("telemetry worker /go/<deal-id>?src= redirect (aggregate day x deal x provider x src x ref x "
                                   "ua_class in D1; no IPs, user agents or cookies). go_clicks_by_provider = clicks.count split by "
                                   "provider and src. test_go_clicks_by_provider = our own test clicks (src *-test or internal ref)"
                                   if ok else "not available this run")
    weeks = {w["week"]: w for w in rep["weeks"]}
    for w in weeks.values():
        w["go_clicks_by_provider"], w["test_go_clicks_by_provider"] = {}, {}
        if ok:
            w["clicks"] = {"count": 0, "by_provider": w["go_clicks_by_provider"], "by_source": {},
                           "excluded": {"bot": 0, "script": 0, "prefetch": 0, "house": 0}, "unclassified_ua": 0}
            w["outbound_clicks"] = 0
        else:
            w["clicks"], w["outbound_clicks"] = None, None
            w["clicks_null_reason"] = "telemetry worker /v1/clicks not available this run"
    for r in go.get("rows") or [] if ok else []:
        w = weeks.get(week(r["day"]))
        if w is None:
            continue
        src, ref = str(r.get("src") or "none"), str(r.get("ref") or "none")
        uac, n = str(r.get("ua_class") or "unclassified"), int(r.get("n") or 0)
        c = w["clicks"]
        if src.endswith("-test") or internal(ref):
            _add(w["test_go_clicks_by_provider"].setdefault(str(r.get("provider") or "unknown"), {}), src.removesuffix("-test"), n)
            c["excluded"]["house"] += n
            continue
        if uac in EXCLUDED_UA:
            c["excluded"][uac] += n
            continue
        _add(w["go_clicks_by_provider"].setdefault(str(r.get("provider") or "unknown"), {}), src, n)
        _add(c["by_source"], src, n)
        c["count"] += n
        if uac == "unclassified":
            c["unclassified_ua"] += n
    for w in weeks.values():
        if w.get("clicks"):
            w["outbound_clicks"] = w["clicks"]["count"]
            w["clicks"]["by_source"] = dict(sorted(w["clicks"]["by_source"].items(), key=lambda x: (-x[1], x[0])))


AGENT_Q2C_SOURCE = ("T136: agent_query_to_click = agent_mcp_clicks / agent_tool_calls per ISO week. agent_tool_calls = hosted "
                    "worker tool calls (hits kind=tool) minus house traffic (src_class house, or a house ref: ci, qa, test, smoke, "
                    "house-*, t<N>) and known bots. agent_mcp_clicks = clicks.by_source.mcp (the src=mcp /go/ links in MCP "
                    "results), already without bots and house clicks. Clicks also come from local (stdio) installs, whose calls "
                    "the hosted worker cannot see, so the rate can overstate hosted-only conversion. null when no agent calls.")


def add_agent_query_to_click(rep: dict, hosted: dict) -> None:
    """Weekly query-to-click rate for agent (MCP) traffic, house traffic and known bots excluded (T136)."""
    rep["sources"]["agent_query_to_click"] = AGENT_Q2C_SOURCE
    calls: dict = {}
    for h in hosted.get("hits") or []:
        if h.get("kind") != "tool":
            continue
        ref, srcc, uac = str(h.get("ref") or "none"), str(h.get("src_class") or ""), str(h.get("ua_class") or "")
        if srcc == "house" or uac in ("house", "ci", "known-bot") or internal(ref):
            continue
        _add(calls, week(h["day"]), h.get("n"))
    for w in rep["weeks"]:
        n = calls.get(w["week"], 0)
        c = w.get("clicks")
        k = (c or {}).get("by_source", {}).get("mcp", 0) if c is not None else None
        rate = round(k / n, 4) if (n and k is not None) else None
        w["agent_query_to_click"] = {
            "agent_tool_calls": n, "agent_mcp_clicks": k, "rate": rate,
            "null_reason": None if rate is not None else ("click source not available this run" if k is None
                                                          else "no agent tool calls recorded this week"),
        }


DEMAND_SOURCE = ("P8: daily aggregate demand from hosted GPU tool calls (compare_gpu_prices, estimate_job_cost, "
                 "optimize_agent_stack): one count per UTC day x tool x gpu_family x region_group x price_tier x cheapest_provider. "
                 "gpu_family is the requested GPU bucketed to a fixed list of known families (anything else 'other', none 'any'); "
                 "region_group is the requested region bucketed likewise; price_tier and cheapest_provider describe the first-ranked "
                 "result in our answer ('none' when there was none). No caller IDs, raw arguments or free text are stored. House "
                 "traffic and known bots are not counted. Hosted endpoint only; local (stdio) installs are not included.")
DEMAND_DAYS = 84


def add_demand(rep: dict, hosted: dict, now: datetime) -> None:
    """P8: copy the hosted worker's daily demand aggregates (last DEMAND_DAYS days), bucketed fields only."""
    keys = ("day", "tool", "gpu_family", "region_group", "price_tier", "cheapest_provider", "n")
    rep["sources"]["demand_daily"] = DEMAND_SOURCE
    if "error" in hosted or "demand_daily" not in hosted:
        rep["demand_daily"] = None
        rep["demand_daily_null_reason"] = ("hosted stats not available this run" if "error" in hosted
                                           else "not collected yet: the hosted worker has not served demand_daily (deploy + migration 0005 pending)")
        return
    cut = (now.date() - timedelta(days=DEMAND_DAYS)).isoformat()
    rows = [{k: r.get(k) for k in keys} for r in hosted.get("demand_daily") or [] if str(r.get("day") or "") >= cut]
    rep["demand_daily"] = sorted(rows, key=lambda r: (r["day"], -int(r["n"] or 0), r["tool"], r["gpu_family"]), reverse=False)
    rep["demand_daily_null_reason"] = None


def _safe_clicks() -> dict | None:
    try:
        return weekly_clicks()
    except Exception:  # noqa: BLE001  (never fail the stats run)
        return None


def weekly_clicks() -> dict | None:
    if not all(os.environ.get(k) for k in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_SITE_TAG")):
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    import click_report  # same read-only GraphQL query; only weekly totals leave this function
    try:
        groups = click_report.fetch_groups(120)
    except SystemExit:
        return None
    w: dict = {}
    for g in groups:
        dim = g.get("dimensions") or {}
        if click_report.PATH_RE.match(dim.get("requestPath") or "") and dim.get("date"):
            _add(w, week(dim["date"]), g.get("count"))
    return w


RUM_QUERY = ("query($a:String!,$s:String!,$d:Date!){viewer{accounts(filter:{accountTag:$a}){rumPageloadEventsAdaptiveGroups("
             "limit:5000,filter:{siteTag:$s,date_geq:$d}){count dimensions{date requestPath}}}}}")


def fetch_rum(days: int = 84) -> tuple[list | None, str]:
    """Read-only GraphQL (Analytics:Read token). Never raises: returns (groups, "") or (None, reason)."""
    tok, acct, site = (os.environ.get(k) for k in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_SITE_TAG"))
    if not tok:
        return None, ("not queried in this run: CI has no Cloudflare token; page views are filled box-side through the "
                      "Cloudflare connector (scripts/rum_box_fill.py)")
    if not (acct and site):
        return None, "CF_ACCOUNT_ID or CF_SITE_TAG is not set"
    q = {"query": RUM_QUERY, "variables": {"a": acct, "s": site, "d": str(date.today() - timedelta(days=days))}}
    req = urllib.request.Request("https://api.cloudflare.com/client/v4/graphql", data=json.dumps(q).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                          "User-Agent": "LanternWorks-site-stats"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        if d.get("errors"):
            return None, f"Cloudflare GraphQL error: {str(d['errors'][0].get('message'))[:120]}"
        return d["data"]["viewer"]["accounts"][0]["rumPageloadEventsAdaptiveGroups"], ""
    except Exception as e:  # noqa: BLE001  (never fail the stats run)
        return None, f"Cloudflare GraphQL request failed ({type(e).__name__})"


RUM_KEYS = ("page_views", "visits_by_ref", "visits_null_reason")


def _carry_forward(rep: dict, old_path: Path) -> None:
    """A run without Web Analytics access keeps page views measured earlier (box-side fill) instead of nulling them."""
    try:
        old = {w["week"]: w for w in json.loads(old_path.read_text()).get("weeks", [])}
    except Exception:  # noqa: BLE001
        return
    for s in rep.get("weeks", []):
        o = old.get(s["week"])
        if o and o.get("page_views") is not None:
            for k in RUM_KEYS + ("beacon_out_events",):
                if k in o:
                    s[k] = o[k]
            if "beacon_out_events" not in o and "clicks" not in o and "outbound_clicks" in o:
                s["beacon_out_events"] = o["outbound_clicks"]  # pre-T135 file: outbound_clicks was the beacon figure
            orf, rf = o.get("receipts_funnel") or {}, s.get("receipts_funnel")
            if rf is not None and orf.get("page_views") is not None:
                rf.update(page_views=orf["page_views"], visits_by_ref=orf.get("visits_by_ref") or {}, page_views_null_reason=None)
            elif rf is not None and s.get("visits_by_ref") is not None:  # older fill without receipts paths
                rf.update(visits_by_ref={k: v for k, v in s["visits_by_ref"].items() if RECEIPTS_REF_RE.match(k)},
                          page_views_null_reason="not split by path in the last box-side fill; next fill adds it")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "stats.json"))
    ap.add_argument("--weeks", type=int, default=12)
    ap.add_argument("--rum-groups", help="box-side fill: JSON file of rumPageloadEventsAdaptiveGroups rows read via the Cloudflare connector")
    a = ap.parse_args(argv)
    if a.rum_groups:
        groups, reason = json.loads(Path(a.rum_groups).read_text()), ""
    else:
        groups, reason = fetch_rum()
    hosted, telemetry = _get(HOSTED), _get(TELEMETRY)
    if "error" in hosted and "error" in telemetry:
        print("both sources unavailable; keeping the existing stats.json", file=sys.stderr)
        return 0
    if groups == []:  # beacon live but no rows yet: not a measured zero
        groups, reason = None, ("Cloudflare Web Analytics returned no rows yet for site b392c8b3... (beacon live since "
                                "2026-11-02; ingestion can lag), so not counted")
    rum = rum_weekly(groups) if groups is not None else None
    rep = build(hosted, telemetry, None if rum is not None else _safe_clicks(), a.weeks, datetime.now(timezone.utc), rum, reason)
    if rum is None:
        _carry_forward(rep, Path(a.out))
    add_go_clicks(rep, _get(GO_CLICKS))
    add_agent_query_to_click(rep, hosted)
    add_receipts_hosted(rep, hosted)
    add_demand(rep, hosted, datetime.now(timezone.utc))
    Path(a.out).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: {len(rep['weeks'])} weeks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
