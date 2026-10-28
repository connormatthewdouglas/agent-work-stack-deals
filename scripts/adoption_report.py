#!/usr/bin/env python3
"""Aggregate MCP/agent adoption signals for Lantern Works. Read-only; prints a report.

Sources (all free, aggregate, no visitor-level data):
  - PyPI downloads: pypistats.org public API (daily data, lags about a day; 404 until the package has stats)
  - GitHub repo traffic (views, clones; 14-day window) and stars: `gh api` (needs push access to the repo)
  - MCP Registry presence: registry.modelcontextprotocol.io public API
  - Opt-in telemetry Worker /v1/stats (aggregate per day/tool/version; test rows with version 0.0.0 excluded)
  - Our own CI's PyPI installs, counted from GitHub Actions job history, subtracted from PyPI downloads
  - Cloudflare Web Analytics (the site beacon): only if CF_API_TOKEN, CF_ACCOUNT_ID and CF_SITE_TAG are set
Goal metrics: installs (target 50) and repeat operators (target 10; an install seen on 2+ distinct days).
Nothing here adds tracking; telemetry stays opt-in (LANTERN_TELEMETRY=1) and stores no IDs.
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


TELEMETRY_STATS = "https://lantern-works-telemetry.lantern-works.workers.dev/v1/stats?days=365"
TEST_VERSIONS = {"0.0.0"}
GOALS = {"installs": 50, "repeat_operators": 10}
CI_WORKFLOW = "validate-and-deploy.yml"
# PyPI downloads our own CI makes per job run (see .github/workflows/validate-and-deploy.yml + scripts/test_pypi_install.py):
# pypi-install = fresh-venv pip install + `uvx --no-cache`; docker = the Dockerfile's pip install.
CI_DOWNLOADS_PER_JOB = {"pypi-install": 2, "docker": 1}


def pypi_daily(overall: dict, system: dict, ci_by_day: dict | None) -> dict:
    """Per-day downloads without mirrors, minus downloads with no OS in the user agent (scanners/bots/mirroring
    tools, not installers), minus our own CI. Pure function (tested)."""
    days = {}
    for r in (overall or {}).get("data", []):
        if r.get("category") == "without_mirrors":
            days.setdefault(r["date"], {})["without_mirrors"] = r["downloads"]
    for r in (system or {}).get("data", []):
        d = days.setdefault(r["date"], {})
        key = "no_os" if r.get("category") in (None, "null") else "with_os"
        d[key] = d.get(key, 0) + r["downloads"]
    out = []
    for day in sorted(days):
        d = days[day]
        ci = (ci_by_day or {}).get(day)
        with_os = d.get("with_os")
        est = None if with_os is None or ci is None else max(0, with_os - ci)
        out.append({"day": day, "without_mirrors": d.get("without_mirrors"), "no_os_user_agent": d.get("no_os", 0),
                    "with_os_user_agent": with_os, "own_ci_downloads": ci, "est_external_installs": est})
    known = [r["est_external_installs"] for r in out if r["est_external_installs"] is not None]
    return {"days": out, "est_external_installs_total": sum(known) if known else None,
            "complete": bool(out) and len(known) == len(out)}


def ci_downloads_by_day(jobs_by_run: list[list[dict]]) -> dict:
    """{UTC day: our CI's PyPI downloads} from Actions job lists (skipped/cancelled-before-start jobs don't count)."""
    out = {}
    for jobs in jobs_by_run:
        for j in jobs:
            n = CI_DOWNLOADS_PER_JOB.get(j.get("name"))
            if n and j.get("conclusion") not in ("skipped", None) and j.get("started_at"):
                day = j["started_at"][:10]
                out[day] = out.get(day, 0) + n
    return out


def own_ci(days: list[str]) -> dict | None:
    jobs = []
    for day in days:
        runs = _gh(f"repos/{REPO}/actions/workflows/{CI_WORKFLOW}/runs?created={day}&per_page=100")
        if not isinstance(runs, dict) or "error" in runs:
            return None
        for r in runs.get("workflow_runs", []):
            j = _gh(f"repos/{REPO}/actions/runs/{r['id']}/jobs?per_page=50")
            if not isinstance(j, dict) or "error" in j:
                return None
            jobs.append(j.get("jobs", []))
    res = ci_downloads_by_day(jobs)
    return {d: res.get(d, 0) for d in days}


def telemetry_summary(stats: dict) -> dict:
    """Opt-in telemetry, test rows (version 0.0.0) dropped. distinct installs / repeat operators need an install_id,
    which the collector does not store (by design), so they are None unless rows carry one. Pure function (tested)."""
    if not isinstance(stats, dict) or "error" in stats:
        return {"available": False, "note": (stats or {}).get("error", "no data")}
    rows = [r for r in stats.get("rows", []) if r.get("version") not in TEST_VERSIONS]
    out = {"available": True, "calls": sum(r.get("n", 0) for r in rows),
           "test_rows_excluded": sum(1 for r in stats.get("rows", []) if r.get("version") in TEST_VERSIONS),
           "days_with_calls": len({r["day"] for r in rows}), "versions": sorted({r["version"] for r in rows}),
           "by_tool": {}}
    for r in rows:
        out["by_tool"][r["tool"]] = out["by_tool"].get(r["tool"], 0) + r.get("n", 0)
    if any("install_id" in r for r in rows):
        seen = {}
        for r in rows:
            if r.get("install_id"):
                seen.setdefault(r["install_id"], set()).add(r["day"])
        out["distinct_installs"] = len(seen)
        out["repeat_operators"] = sum(1 for d in seen.values() if len(d) >= 2)
    else:
        out["distinct_installs"] = None
        out["repeat_operators"] = None
        out["why_none"] = ("The collector stores only aggregate counts per (day, tool, version), no install_id, so distinct "
                           "installs and repeat operators (an install seen on 2+ distinct days) can't be computed.")
    return out


def cloudflare_beacon() -> dict:
    """Page views of /install/ and /stack/ from Cloudflare Web Analytics (GraphQL), only when credentials are set."""
    import os
    tok, acct, site = (os.environ.get(k) for k in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_SITE_TAG"))
    if not (tok and acct and site):
        return {"available": False, "note": "not queried: set CF_API_TOKEN, CF_ACCOUNT_ID and CF_SITE_TAG (read-only Analytics token); "
                                            "otherwise read the Cloudflare Web Analytics dashboard"}
    from datetime import date, timedelta
    q = {"query": "query($a:String!,$s:String!,$d:Date!){viewer{accounts(filter:{accountTag:$a}){rumPageloadEventsAdaptiveGroups("
                  "limit:100,filter:{siteTag:$s,date_geq:$d}){count dimensions{requestPath}}}}}",
         "variables": {"a": acct, "s": site, "d": str(date.today() - timedelta(days=30))}}
    req = urllib.request.Request("https://api.cloudflare.com/client/v4/graphql", data=json.dumps(q).encode(),
                                 headers={**UA, "Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        groups = d["data"]["viewer"]["accounts"][0]["rumPageloadEventsAdaptiveGroups"]
    except Exception as e:  # noqa: BLE001 - report, never crash
        return {"available": False, "note": f"query failed: {type(e).__name__}"}
    pv = {}
    for g in groups:
        pv[g["dimensions"]["requestPath"]] = pv.get(g["dimensions"]["requestPath"], 0) + g["count"]
    return {"available": True, "page_views_30d": {k: pv.get(k, 0) for k in ("/install/", "/stack/", "/e/out/")}}


def goals(p: dict, t: dict) -> dict:
    inst = p.get("est_external_installs_total") if p else None
    return {"installs": {"value": inst, "target": GOALS["installs"], "basis": "PyPI downloads (no mirrors) with an OS in the "
                         "user agent, minus our own CI; an upper bound on real installs"},
            "repeat_operators": {"value": t.get("repeat_operators"), "target": GOALS["repeat_operators"],
                                 "basis": "opt-in telemetry install seen on 2+ distinct days" + ("" if t.get("repeat_operators") is not None else "; not measurable today")}}


CAVEATS = [
    "PyPI counts file downloads, not people: one user can download many times, uvx caches (repeat runs don't count), and other "
    "people's CI, registry scanners and container builds that send an OS still count. Treat installs as an upper bound.",
    "pypistats has about a day of lag and keeps ~180 days; 'no OS in user agent' downloads are mostly mirrors/scanners and are excluded.",
    "Our CI downloads are counted from Actions job history (pypi-install = 2, docker = 1 per run); manual local test installs are not subtracted.",
    "Telemetry is opt-in (LANTERN_TELEMETRY=1), off by default, and our CI strips LANTERN_* env, so CI never reports. Most users "
    "never opt in, so telemetry is a floor, not a count.",
    "Repeat operators can't be measured: no install ID exists anywhere (by design). Adding one would be new tracking and needs approval.",
]


NOT_AVAILABLE = {
    "api_v1_requests": "Not measurable without a new service: the site is served directly by GitHub Pages (no request logs), and "
                       "Cloudflare Web Analytics only counts browser page views that run its JavaScript, not JSON fetches.",
    "site_usage": "Cloudflare Web Analytics dashboard (page views, visits, referrers; virtual paths /e/search/, /e/calculator/, "
                  "/e/compare/, /e/out/<deal-id>/). Not queried here.",
}


def main() -> int:
    rep = {"pypi": pypi(), "github": github(), "registry": registry(), "not_in_this_report": NOT_AVAILABLE}
    overall = _get(f"https://pypistats.org/api/packages/{PACKAGE}/overall?mirrors=false")
    system = _get(f"https://pypistats.org/api/packages/{PACKAGE}/system?mirrors=false")
    days = sorted({r["date"] for r in overall.get("data", [])}) if "data" in overall else []
    rep["pypi_installs"] = pypi_daily(overall, system, own_ci(days) if days else {})
    rep["telemetry"] = telemetry_summary(_get(TELEMETRY_STATS))
    rep["cloudflare_beacon"] = cloudflare_beacon()
    rep["goals"] = goals(rep["pypi_installs"], rep["telemetry"])
    rep["caveats"] = CAVEATS
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
    pi, t, cf, gl = rep["pypi_installs"], rep["telemetry"], rep["cloudflare_beacon"], rep["goals"]
    print("Installs (PyPI, per UTC day): " + "; ".join(
        f"{d['day']}: {d['without_mirrors']} no-mirror downloads - {d['no_os_user_agent']} with no OS - {d['own_ci_downloads']} our CI = "
        f"{d['est_external_installs']}" for d in pi["days"]) if pi["days"] else "Installs: no pypistats data yet")
    print(f"Opt-in telemetry: " + (f"{t['calls']} calls on {t['days_with_calls']} day(s) ({t['test_rows_excluded']} test rows excluded); "
                                   f"distinct installs {t['distinct_installs']}, repeat operators {t['repeat_operators']}" if t["available"] else t["note"]))
    print("Cloudflare beacon: " + (json.dumps(cf["page_views_30d"]) if cf["available"] else cf["note"]))
    for k, v in gl.items():
        print(f"Goal {k}: {v['value'] if v['value'] is not None else 'not measurable'} / {v['target']} ({v['basis']})")
    for c in CAVEATS:
        print(f"caveat: {c}")
    for k, v in NOT_AVAILABLE.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
