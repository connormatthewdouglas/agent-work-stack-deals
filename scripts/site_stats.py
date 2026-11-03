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
BEACON_SINCE_WEEK = "2026-W45"  # site b392c8b3... beacon token 327dc277... shipped 2026-11-02
BEACON_SINCE_REASON = "not measured: this Web Analytics site's beacon went live on 2026-11-02 (ISO week 2026-W45)"
INSTALLS_NULL_REASON = ("not measurable: the opt-in telemetry worker records day x tool x version only, with no install id "
                        "or ref; an install id needs the owner's approval. Hosted connects by ref are in mcp_initialize_by_ref.")


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
        s = w.setdefault(week(day), {"page_views": 0, "visits_by_ref": {}, "outbound_clicks": 0})
        m = REF_PATH_RE.match(path)
        if m:
            _add(s["visits_by_ref"], m.group(1), n)
        elif OUT_PATH_RE.match(path):
            s["outbound_clicks"] += n
        elif not path.startswith("/e/"):
            s["page_views"] += n
    return w


def build(hosted: dict, telemetry: dict, clicks: dict | None, weeks: int, now: datetime,
          rum: dict | None = None, rum_reason: str = "") -> dict:
    out: dict = {}

    def slot(w):
        return out.setdefault(w, {"week": w, "mcp_tool_calls_by_ref": {}, "feed_fetches_by_ref": {},
                                  "mcp_initialize_by_ref": {}, "external_mcp_tool_calls": 0, "untagged_mcp_tool_calls": 0,
                                  "telemetry_tool_calls": 0, "outbound_clicks": None,
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
        slot(w)["outbound_clicks"] = n
    for w, r in (rum or {}).items():
        s = slot(w)
        s["page_views"], s["outbound_clicks"] = r["page_views"], r["outbound_clicks"]
        s["visits_by_ref"] = dict(sorted(r["visits_by_ref"].items(), key=lambda x: (-x[1], x[0])))
        s["visits_null_reason"] = None
    if rum is not None:  # measured, so a week with no beacon rows is a real zero, from the beacon switch on
        for s in out.values():
            if s["week"] < BEACON_SINCE_WEEK and not rum.get(s["week"]):
                s["visits_null_reason"] = BEACON_SINCE_REASON
            elif s["page_views"] is None:
                s.update(page_views=0, visits_by_ref={}, outbound_clicks=s["outbound_clicks"] or 0, visits_null_reason=None)
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
            "outbound_clicks": "Cloudflare Web Analytics beacon, /e/out/ virtual page views, weekly total" if (clicks is not None or rum is not None)
                               else "not available this run (null)",
            "page_views": ("Cloudflare Web Analytics beacon page views (site b392c8b3...), real pages only, weekly total" if rum is not None
                           else f"null: {rum_reason}"),
            "visits_by_ref": ("Cloudflare Web Analytics /e/ref/<ref>/ virtual views, sent once per landing with ?ref= by pages built "
                              "from 2026-11-02 (rel055) on; earlier weeks cannot show refs" if rum is not None else f"null: {rum_reason}"),
            "installs_by_ref": "null: " + INSTALLS_NULL_REASON,
        },
        "weeks": rows,
    }


def add_go_clicks(rep: dict, go: dict) -> None:
    """Per-provider /go/ redirect clicks by src (site|mcp|feed|readme), weekly. src ending -test and internal refs are our
    own test traffic: kept apart in test_go_clicks_by_provider and never counted in go_clicks_by_provider."""
    ok = "error" not in go
    rep["sources"]["go_clicks"] = ("telemetry worker /go/<deal-id>?src= redirect (aggregate day x deal x provider x src x ref in D1; "
                                   "no IPs or cookies). test_go_clicks_by_provider = our own test clicks (src *-test or internal ref), "
                                   "excluded from go_clicks_by_provider" if ok else "not available this run")
    weeks = {w["week"]: w for w in rep["weeks"]}
    for w in weeks.values():
        w["go_clicks_by_provider"], w["test_go_clicks_by_provider"] = {}, {}
    for r in go.get("rows") or [] if ok else []:
        w = weeks.get(week(r["day"]))
        if w is None:
            continue
        src, ref = str(r.get("src") or "none"), str(r.get("ref") or "none")
        test = src.endswith("-test") or internal(ref)
        key = "test_go_clicks_by_provider" if test else "go_clicks_by_provider"
        _add(w[key].setdefault(str(r.get("provider") or "unknown"), {}), src.removesuffix("-test"), r.get("n"))


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
            for k in RUM_KEYS + ("outbound_clicks",):
                if k in o:
                    s[k] = o[k]


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
    Path(a.out).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: {len(rep['weeks'])} weeks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
