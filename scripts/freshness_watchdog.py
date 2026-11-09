#!/usr/bin/env python3
"""Daily outside check: live feed age, availability age, and hosted MCP version.

Fails (and opens or updates one GitHub issue) when any of these is past its threshold:
  * feed_updated_at older than 26h (same bar as scripts/check_gpu_freshness.py; not loosened)
  * availability_collected_at older than 4h
  * hosted /version is not the latest GitHub release version, or its build SHA differs

Reads the public site and the public Worker. Does not edit prices.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

FEED_URL = "https://thelanternworks.com/api/v1/gpu-prices.json"
HOSTED_VERSION_URL = "https://lantern-works-mcp.lantern-works.workers.dev/version"
PYPI_URL = "https://pypi.org/pypi/lantern-works-deals-mcp/json"
FEED_MAX_HOURS = 26
AVAIL_MAX_HOURS = 4
ISSUE_TITLE = "Freshness watchdog: live feed, availability, or hosted MCP is stale"


def _parse(stamp: str | None) -> datetime | None:
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    s = stamp.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_hours(stamp: str | None, now: datetime) -> float | None:
    dt = _parse(stamp)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600


def _builds_match(hosted_build: str | None, expected: str | None) -> bool:
    if not expected:
        return True
    got = (hosted_build or "").strip().lower()
    want = expected.strip().lower()
    if not got or got == "unknown":
        return False
    return got == want or want.startswith(got) or got.startswith(want)


def evaluate(feed: dict, hosted: dict, *, now: datetime, expected_version: str,
             expected_build: str | None = None) -> list[str]:
    """Return human-readable problems. Empty means the live surfaces are fresh."""
    out: list[str] = []
    feed_age = _age_hours(feed.get("feed_updated_at"), now)
    if feed_age is None:
        out.append("feed_updated_at is missing on the live GPU price feed")
    elif feed_age > FEED_MAX_HOURS:
        out.append(f"feed_updated_at {feed.get('feed_updated_at')} is {feed_age:.1f}h old (limit {FEED_MAX_HOURS:g}h)")
    avail_age = _age_hours(feed.get("availability_collected_at"), now)
    if avail_age is None:
        out.append("availability_collected_at is missing on the live GPU price feed")
    elif avail_age > AVAIL_MAX_HOURS:
        out.append(f"availability_collected_at {feed.get('availability_collected_at')} is {avail_age:.1f}h old "
                   f"(limit {AVAIL_MAX_HOURS:g}h)")
    got_version = str(hosted.get("version") or "").strip()
    if got_version != expected_version:
        out.append(f"hosted MCP version {got_version or '(missing)'} != latest release {expected_version}")
    elif not _builds_match(hosted.get("build"), expected_build):
        out.append(f"hosted MCP build {hosted.get('build')} != latest release {expected_build}")
    return out


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "LanternWorks-freshness-watchdog", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def latest_release(repo: str) -> tuple[str, str | None]:
    """(version, commit sha) from the latest GitHub release, else PyPI version and no sha."""
    try:
        rel = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/releases/latest"], text=True))
        version = str(rel.get("tag_name") or "").lstrip("v")
        sha = subprocess.check_output(["gh", "api", f"repos/{repo}/commits/{rel['tag_name']}", "--jq", ".sha"], text=True).strip()
        if version:
            return version, sha or None
    except (subprocess.CalledProcessError, OSError, KeyError, json.JSONDecodeError):
        pass
    info = _get_json(PYPI_URL)["info"]
    return str(info["version"]), None


def _issue_number(repo: str) -> str:
    out = subprocess.check_output(
        ["gh", "issue", "list", "-R", repo, "--state", "open", "--search", f"in:title \"{ISSUE_TITLE}\"",
         "--json", "number", "-q", ".[0].number // empty"],
        text=True).strip()
    return out


def publish(repo: str, problems: list[str], run_url: str) -> None:
    body = "Outside check of the live site and hosted Worker.\n\n" + "\n".join(f"- {p}" for p in problems)
    if run_url:
        body += f"\n\nRun: {run_url}"
    n = _issue_number(repo)
    if n:
        subprocess.check_call(["gh", "issue", "comment", n, "-R", repo, "--body", body])
    else:
        subprocess.check_call(["gh", "issue", "create", "-R", repo, "--title", ISSUE_TITLE, "--body", body])


def close_open(repo: str, run_url: str) -> None:
    n = _issue_number(repo)
    if not n:
        return
    subprocess.check_call(["gh", "issue", "comment", n, "-R", repo, "--body",
                           f"Fresh again.{(' Run: ' + run_url) if run_url else ''} Closing."])
    subprocess.check_call(["gh", "issue", "close", n, "-R", repo, "--reason", "completed"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", help="ISO time for tests; default is UTC now")
    ap.add_argument("--dry-run", action="store_true", help="print problems, do not open an issue")
    a = ap.parse_args(argv)
    now = _parse(a.now) if a.now else datetime.now(timezone.utc)
    assert now is not None
    feed = _get_json(FEED_URL)
    hosted = _get_json(HOSTED_VERSION_URL)
    repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY") or ""
    if repo:
        version, sha = latest_release(repo)
    else:
        version, sha = str(_get_json(PYPI_URL)["info"]["version"]), None
    found = evaluate(feed, hosted, now=now, expected_version=version, expected_build=sha)
    print("\n".join(found) if found else "fresh")
    if a.dry_run or not repo:
        return 1 if found else 0
    run_url = os.environ.get("RUN_URL") or ""
    if found:
        publish(repo, found, run_url)
        return 1
    close_open(repo, run_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
