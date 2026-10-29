#!/usr/bin/env python3
"""T30: private per-vendor daily outbound-click counts (aggregate only).

Source: the Cloudflare Web Analytics beacon already on every page (cookieless). site_ui.TRACK_JS turns an outbound
click into one page view of a virtual path: /e/out/<deal-id>/ or /e/out/h-<vendor-hostname>/. Nothing else is sent
(no query strings, search text, cookies, storage or identifiers) and this repo stores no IPs, cookies or user agents.

This script reads only aggregate counts (date x path) from Cloudflare's GraphQL API and maps them to vendors.
It is a PRIVATE view: output goes to stdout or --out (default outside the repo); never commit or publish it.
Needs a read-only Analytics token: CF_API_TOKEN, CF_ACCOUNT_ID, CF_SITE_TAG (the same ones adoption_report.py uses).

  python3 scripts/click_report.py [--days 30] [--out /workspace/mart/private-stats/clicks.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH_RE = re.compile(r"^/e/out/([a-z0-9-]{1,80})/?$", re.I)


def vendor_map() -> dict:
    deals = json.loads((ROOT / "deals.json").read_text(encoding="utf-8"))["deals"]
    return {d["id"]: d.get("advertiser") or d["id"] for d in deals if d.get("id")}


def vendor_for(slug: str, by_deal: dict) -> str:
    if slug.startswith("h-"):
        return slug[2:]  # hostname with dots as dashes, e.g. hyperstack-cloud
    return by_deal.get(slug, slug)


def aggregate(groups: list[dict], by_deal: dict) -> dict:
    """[{count, dimensions:{date, requestPath}}] -> {date: {vendor: clicks}} plus totals; non-/e/out/ paths ignored."""
    daily, totals = {}, {}
    for g in groups:
        dim = g.get("dimensions") or {}
        m = PATH_RE.match(dim.get("requestPath") or "")
        if not m:
            continue
        v, day, n = vendor_for(m.group(1).lower(), by_deal), dim.get("date"), int(g.get("count") or 0)
        daily.setdefault(day, {})
        daily[day][v] = daily[day].get(v, 0) + n
        totals[v] = totals.get(v, 0) + n
    return {"by_day": dict(sorted(daily.items(), reverse=True)),
            "totals": dict(sorted(totals.items(), key=lambda x: (-x[1], x[0])))}


def fetch_groups(days: int) -> list[dict]:
    tok, acct, site = (os.environ.get(k) for k in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_SITE_TAG"))
    if not (tok and acct and site):
        raise SystemExit("not queried: set CF_API_TOKEN, CF_ACCOUNT_ID and CF_SITE_TAG (read-only Account Analytics token)")
    q = {"query": "query($a:String!,$s:String!,$d:Date!){viewer{accounts(filter:{accountTag:$a}){rumPageloadEventsAdaptiveGroups("
                  "limit:5000,filter:{siteTag:$s,date_geq:$d,requestPath_like:\"/e/out/%\"}){count dimensions{date requestPath}}}}}",
         "variables": {"a": acct, "s": site, "d": str(date.today() - timedelta(days=days))}}
    req = urllib.request.Request("https://api.cloudflare.com/client/v4/graphql", data=json.dumps(q).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                          "User-Agent": "LanternWorks-click-report"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    if d.get("errors"):
        raise SystemExit(f"Cloudflare GraphQL error: {d['errors'][0].get('message')}")
    return d["data"]["viewer"]["accounts"][0]["rumPageloadEventsAdaptiveGroups"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", default=None, help="write JSON here (keep it outside the repo)")
    a = ap.parse_args(argv)
    rep = {"schema": "lantern-works-click-report/1", "private": True, "days": a.days,
           "note": "aggregate outbound clicks per vendor per UTC day from the Cloudflare Web Analytics beacon; "
                   "no IPs, cookies or user agents are stored by Lantern Works",
           **aggregate(fetch_groups(a.days), vendor_map())}
    text = json.dumps(rep, indent=2)
    if a.out:
        out = Path(a.out).resolve()
        if ROOT in out.parents:
            raise SystemExit("refusing to write the private click report inside the repo")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        os.chmod(out, 0o600)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
