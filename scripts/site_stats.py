#!/usr/bin/env python3
"""Brain #247 task 1: public /stats.json with weekly aggregate ref= counts. Aggregate counts only, never PII.

Sources (all aggregate, no visitor-level data):
  - hosted MCP worker /stats.json: tool calls per UTC day x tool x ref, and feed/initialize hits per day x kind x ref
  - opt-in telemetry worker /v1/stats: tool calls per day x tool x version (test version 0.0.0 dropped)
  - Cloudflare Web Analytics beacon (/e/out/<id> virtual page views = outbound clicks): weekly totals only, and only
    when CF_API_TOKEN, CF_ACCOUNT_ID and CF_SITE_TAG are set; otherwise reported as not available
Rows are rolled up to ISO weeks (YYYY-Www). No per-caller, per-key or per-vendor click data is published.
  python3 scripts/site_stats.py [--out stats.json] [--weeks 12]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/stats.json"
TELEMETRY = "https://lantern-works-telemetry.lantern-works.workers.dev/v1/stats?days=120"
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


def internal(ref: str) -> bool:
    return ref in INTERNAL_REFS or ref.startswith("house-")


def _add(d: dict, k, n: int):
    d[k] = d.get(k, 0) + int(n or 0)


def build(hosted: dict, telemetry: dict, clicks: dict | None, weeks: int, now: datetime) -> dict:
    out: dict = {}

    def slot(w):
        return out.setdefault(w, {"week": w, "mcp_tool_calls_by_ref": {}, "feed_fetches_by_ref": {},
                                  "mcp_initialize_by_ref": {}, "external_mcp_tool_calls": 0,
                                  "telemetry_tool_calls": 0, "outbound_clicks": None})

    for r in hosted.get("rows") or []:
        s, ref = slot(week(r["day"])), str(r.get("ref") or "none")
        _add(s["mcp_tool_calls_by_ref"], ref, r.get("n"))
        if not internal(ref):
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
    rows = sorted(out.values(), key=lambda s: s["week"], reverse=True)[:weeks]
    for s in rows:
        for k in ("mcp_tool_calls_by_ref", "feed_fetches_by_ref", "mcp_initialize_by_ref"):
            s[k] = dict(sorted(s[k].items(), key=lambda x: (-x[1], x[0])))
    return {
        "schema": "lantern-works-site-stats/1",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Weekly (ISO week, UTC) aggregate counts only. No IP addresses, user agents, cookies, keys or per-caller "
                "data. ref is the ?ref= channel tag; refs ci, qa, test, smoke and house-* are our own checks and are "
                "excluded from external_mcp_tool_calls.",
        "sources": {
            "hosted_mcp": "https://lantern-works-mcp.lantern-works.workers.dev/stats" + ("" if "error" not in hosted else " (unavailable this run)"),
            "telemetry": "opt-in LANTERN_TELEMETRY=1 aggregate" + ("" if "error" not in telemetry else " (unavailable this run)"),
            "outbound_clicks": "Cloudflare Web Analytics beacon, /e/out/ virtual page views, weekly total" if clicks is not None
                               else "not available this run (null)",
        },
        "weeks": rows,
    }


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "stats.json"))
    ap.add_argument("--weeks", type=int, default=12)
    a = ap.parse_args(argv)
    hosted, telemetry = _get(HOSTED), _get(TELEMETRY)
    if "error" in hosted and "error" in telemetry:
        print("both sources unavailable; keeping the existing stats.json", file=sys.stderr)
        return 0
    rep = build(hosted, telemetry, weekly_clicks(), a.weeks, datetime.now(timezone.utc))
    Path(a.out).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: {len(rep['weeks'])} weeks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
