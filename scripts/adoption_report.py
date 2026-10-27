#!/usr/bin/env python3
"""Aggregate MCP/agent adoption signals for Lantern Works. Read-only; prints a report.

Sources (all free, aggregate, no visitor-level data):
  - PyPI downloads: pypistats.org public API (daily data, lags about a day; 404 until the package has stats)
  - GitHub repo traffic (views, clones; 14-day window) and stars: `gh api` (needs push access to the repo)
  - MCP Registry presence: registry.modelcontextprotocol.io public API
Usage: python3 scripts/adoption_report.py [--json]
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

PACKAGE = "lantern-works-deals-mcp"
REPO = "connormatthewdouglas/agent-work-stack-deals"
REGISTRY_NAME = "io.github.connormatthewdouglas/lantern-works-deals"
UA = {"User-Agent": "lantern-works-adoption-report"}


def _get(url: str):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {"error": str(e)}


def pypi() -> dict:
    recent = _get(f"https://pypistats.org/api/packages/{PACKAGE}/recent")
    if "error" in recent:
        note = "no stats yet (pypistats returns 404 until it has indexed downloads, ~1 day)" if recent["error"] == "HTTP 404" else recent["error"]
        return {"available": False, "note": note}
    overall = _get(f"https://pypistats.org/api/packages/{PACKAGE}/overall?mirrors=false")
    total = sum(r["downloads"] for r in overall.get("data", [])) if "data" in overall else None
    return {"available": True, **recent.get("data", {}), "total_without_mirrors": total}


def _gh(path: str):
    try:
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": str(e)}
    if out.returncode:
        return {"error": (out.stderr or out.stdout).strip()[:200]}
    return json.loads(out.stdout)


def github() -> dict:
    repo, views, clones = _gh(f"repos/{REPO}"), _gh(f"repos/{REPO}/traffic/views"), _gh(f"repos/{REPO}/traffic/clones")
    refs = _gh(f"repos/{REPO}/traffic/popular/referrers")
    return {
        "stars": repo.get("stargazers_count"), "forks": repo.get("forks_count"), "watchers": repo.get("subscribers_count"),
        "views_14d": views.get("count"), "unique_viewers_14d": views.get("uniques"),
        "clones_14d": clones.get("count"), "unique_cloners_14d": clones.get("uniques"),
        "top_referrers_14d": [(r["referrer"], r["count"]) for r in refs] if isinstance(refs, list) else [],
        "errors": [x["error"] for x in (repo, views, clones) if isinstance(x, dict) and "error" in x],
    }


def registry() -> dict:
    d = _get(f"https://registry.modelcontextprotocol.io/v0/servers?search={REGISTRY_NAME.split('/')[-1]}")
    if "error" in d:
        return {"present": None, "note": d["error"]}
    hits = [s for s in d.get("servers", []) if s["server"]["name"] == REGISTRY_NAME]
    meta = lambda s: s.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
    latest = [s["server"]["version"] for s in hits if meta(s).get("isLatest")]
    return {"present": bool(hits), "versions": [s["server"]["version"] for s in hits], "latest": latest[0] if latest else None,
            "status": meta(hits[-1]).get("status") if hits else None}


NOT_AVAILABLE = {
    "api_v1_requests": "Not measurable without a new service: the site is served directly by GitHub Pages (no request logs), and "
                       "Cloudflare Web Analytics only counts browser page views that run its JavaScript, not JSON fetches.",
    "site_usage": "Cloudflare Web Analytics dashboard (page views, visits, referrers; virtual paths /e/search/, /e/calculator/, "
                  "/e/compare/, /e/out/<deal-id>/). Not queried here.",
}


def main() -> int:
    rep = {"pypi": pypi(), "github": github(), "registry": registry(), "not_in_this_report": NOT_AVAILABLE}
    if "--json" in sys.argv:
        print(json.dumps(rep, indent=2))
        return 0
    p, g, r = rep["pypi"], rep["github"], rep["registry"]
    print(f"Lantern Works adoption report")
    print(f"PyPI {PACKAGE}: " + (f"last day {p.get('last_day')}, last week {p.get('last_week')}, last month {p.get('last_month')}, "
                                  f"total (no mirrors) {p.get('total_without_mirrors')}" if p["available"] else p["note"]))
    print(f"GitHub {REPO}: stars {g['stars']}, forks {g['forks']}, watchers {g['watchers']}")
    print(f"  views (14d) {g['views_14d']} ({g['unique_viewers_14d']} unique), clones (14d) {g['clones_14d']} ({g['unique_cloners_14d']} unique; includes this repo's own CI checkouts)")
    if g["top_referrers_14d"]:
        print("  top referrers: " + ", ".join(f"{a} {b}" for a, b in g["top_referrers_14d"][:5]))
    for e in g["errors"]:
        print(f"  error: {e}")
    print(f"MCP Registry {REGISTRY_NAME}: " + ("present, versions " + ", ".join(r["versions"]) + f"; latest {r['latest']} ({r['status']})"
                                                if r["present"] else ("not found" if r["present"] is False else r["note"])))
    for k, v in NOT_AVAILABLE.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
