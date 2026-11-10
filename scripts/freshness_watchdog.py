#!/usr/bin/env python3
"""Outside check of the live GPU feed, availability, stats, hosted MCP build, and collector runs.

Fails, and opens or updates one GitHub issue labeled freshness-watchdog, when any of these is true:
  * feed_updated_at older than 26h (same bar as scripts/check_gpu_freshness.py; not loosened)
  * availability_collected_at older than 8h (AVAIL_MAX_AGE_H; 2x the 4h Scout cadence)
  * any ranked row's verified_at/checked_at older than 48h (T41-12)
  * stats.json generated_at older than 192h (weekly stats plus a day of cron slack)
  * a timestamp is in the future
  * the rates list is empty or has shrunk to under half the committed feed
  * hosted /version is not pyproject's version, or its build is not a >=7 hex prefix of the
    commit that last changed that version line
  * the latest completed gpu-refresh, scout-import, or lium-collect run is not success,
    or the last successful run is older than 30h / 10h / 6h respectively (queued and
    in-progress runs are ignored)

A fetch or gh error is itself a failure and still updates the issue. Does not edit prices.
Collector-run failures are titled and listed separately from data staleness.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FEED_URL = "https://thelanternworks.com/api/v1/gpu-prices.json"
STATS_URL = "https://thelanternworks.com/stats.json"
HOSTED_VERSION_URL = "https://lantern-works-mcp.lantern-works.workers.dev/version"
FEED_MAX_HOURS = 26
AVAIL_MAX_HOURS = 8  # AVAIL_MAX_AGE_H; 2x the 4h Scout cadence
ROW_MAX_HOURS = 48  # T41-12: oldest verified row
STATS_MAX_HOURS = 192  # weekly site-stats plus a day of cron slack
SHRINK_RATIO = 0.5
FETCH_ATTEMPTS = 3
FETCH_TIMEOUT_SEC = 30
FETCH_BACKOFF_SEC = (1, 2)
GH_TIMEOUT_SEC = 60
LABEL = "freshness-watchdog"
WORKFLOW_SUCCESS_MAX_HOURS = {
    "gpu-refresh.yml": 30,
    "scout-import.yml": 10,
    "lium-collect.yml": 6,
}
TITLE_DATA = "Freshness watchdog: live feed, availability, stats, or hosted MCP is stale"
TITLE_COLLECTOR = "Freshness watchdog: a collector run failed or is too old"
TITLE_BOTH = "Freshness watchdog: stale data and a collector-run failure"


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


def age_problems(label: str, stamp: str | None, limit: float, now: datetime, *, missing: str | None = None) -> list[str]:
    age = _age_hours(stamp, now)
    if age is None:
        return [missing or f"{label} is missing"]
    if age < 0:
        return [f"{label} {stamp} is in the future"]
    if age > limit:
        return [f"{label} {stamp} is {age:.1f}h old (limit {limit:g}h)"]
    return []


def _hex_build(value: str | None) -> str:
    got = (value or "").strip().lower()
    return got if HEX_BUILD.fullmatch(got) else ""


HEX_BUILD = re.compile(r"^[0-9a-f]{7,}$")


def builds_match(hosted_build: str | None, expected: str | None) -> bool:
    """True only when both are hex of at least 7 characters and one is a prefix of the other."""
    got, want = _hex_build(hosted_build), _hex_build(expected)
    if not got or not want:
        return False
    return want.startswith(got) or got.startswith(want)


def _row_stamp(row: dict) -> str | None:
    return row.get("verified_at") or row.get("checked_at")


def _row_id(row: dict) -> str:
    return "|".join(str(row.get(k) or "?") for k in ("advertiser", "vendor", "gpu", "tier") if row.get(k) or k in ("gpu", "tier"))


def _owner_names() -> list[str]:
    path = ROOT / "data" / "owner_hold.json"
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    names = doc.get("vendors") if isinstance(doc, dict) else None
    return [x.strip() for x in names if isinstance(x, str) and x.strip()] if isinstance(names, list) else []


def _is_owner_held(vendor: str | None) -> bool:
    v = " ".join(str(vendor or "").split()).casefold()
    if not v:
        return False
    for raw in _owner_names():
        key = " ".join(raw.split()).casefold()
        if v == key or v.startswith(key + " ") or v.startswith(key + "("):
            return True
    return False


def hold_lines(feed: dict, now: datetime) -> list[str]:
    """Held and owner-held rows with age. Informational; emptiness is a separate failure."""
    lines = []
    for h in feed.get("held_stale") or []:
        if not isinstance(h, dict):
            continue
        age = _age_hours(h.get("checked_at"), now)
        age_s = "missing" if age is None else f"{age:.1f}h"
        owner = " owner-held" if _is_owner_held(h.get("vendor")) else ""
        lines.append(f"held{owner} {h.get('vendor')}: {age_s} ({h.get('reason')})")
    for r in feed.get("rates") or []:
        if isinstance(r, dict) and _is_owner_held(r.get("advertiser") or r.get("vendor")):
            age = _age_hours(_row_stamp(r), now)
            age_s = "missing" if age is None else f"{age:.1f}h"
            lines.append(f"owner-held rate {_row_id(r)}: {age_s}")
    return lines


def evaluate(feed: dict, hosted: dict, *, now: datetime, expected_version: str, expected_build: str | None,
             committed_rate_count: int | None = None, stats: dict | None = None,
             check_hosted: bool = True) -> list[str]:
    """Data-freshness problems that fail the run. Empty means the checked data surfaces are fresh.

    Collector-run notes are produced separately by notes_for_workflow / workflow_notes.
    """
    out: list[str] = []
    out.extend(age_problems(
        "feed_updated_at", feed.get("feed_updated_at"), FEED_MAX_HOURS, now,
        missing="feed_updated_at is missing on the live GPU price feed"))
    out.extend(age_problems(
        "availability_collected_at", feed.get("availability_collected_at"), AVAIL_MAX_HOURS, now,
        missing="availability_collected_at is missing on the live GPU price feed"))
    rates = feed.get("rates")
    if not isinstance(rates, list) or not rates:
        out.append("rates list is empty")
        n_held = len(feed.get("held_stale") or [])
        if n_held:
            out.append(f"all tracked rows are held ({n_held}); none are ranked")
    else:
        old, future = [], []
        for r in rates:
            if not isinstance(r, dict):
                future.append("non-object rate")
                continue
            stamp = _row_stamp(r)
            age = _age_hours(stamp, now)
            if age is None:
                old.append(f"{_row_id(r)} missing verified_at/checked_at")
            elif age < 0:
                future.append(f"{_row_id(r)} {stamp}")
            elif age > ROW_MAX_HOURS:
                old.append((age, f"{_row_id(r)} {stamp} is {age:.1f}h old"))
        if future:
            out.append(f"{len(future)} ranked row timestamp(s) in the future: " + "; ".join(future[:5]))
        if old:
            described = [x if isinstance(x, str) else x[1] for x in old]
            oldest = max((x[0] for x in old if isinstance(x, tuple)), default=None)
            tail = f"; oldest {oldest:.1f}h (limit {ROW_MAX_HOURS:g}h, T41-12)" if oldest is not None else ""
            out.append(f"{len(old)} ranked row(s) older than {ROW_MAX_HOURS:g}h{tail}: " + "; ".join(described[:5]))
    if isinstance(rates, list) and committed_rate_count and len(rates) < committed_rate_count * SHRINK_RATIO:
        out.append(f"rates shrank from {committed_rate_count} to {len(rates)}")
    if stats is not None:
        out.extend(age_problems(
            "stats generated_at", stats.get("generated_at"), STATS_MAX_HOURS, now,
            missing="stats generated_at is missing on the live stats.json"))
    if check_hosted:
        got_version = str(hosted.get("version") or "").strip()
        if got_version != expected_version:
            out.append(f"hosted MCP version {got_version or '(missing)'} != pyproject {expected_version or '(missing)'}")
        if not builds_match(hosted.get("build"), expected_build):
            if not _hex_build(expected_build):
                out.append(f"expected build is unresolvable ({expected_build!r}); a build check requires a hex prefix of at least 7")
            elif not _hex_build(hosted.get("build")):
                out.append(f"hosted MCP build is unresolvable ({hosted.get('build')!r}); need a hex prefix of at least 7")
            else:
                out.append(f"hosted MCP build {hosted.get('build')} != version commit {expected_build}")
    return out


def expected_from_checkout(root: Path | None = None) -> tuple[str, str]:
    """Version from pyproject.toml and the commit that last changed that version line."""
    root = root or ROOT
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^version = "([^"]+)"', text)
    if not m:
        raise RuntimeError("pyproject.toml has no version")
    version = m.group(1)
    sha = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "-G", f'^version = "{version}"', "--", "pyproject.toml"],
        cwd=root, text=True).strip()
    if not _hex_build(sha):
        raise RuntimeError(f"commit that set version {version} is unresolvable ({sha!r})")
    return version, sha


def committed_rate_count(root: Path | None = None) -> int:
    root = root or ROOT
    doc = json.loads((root / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    rates = doc.get("rates") or []
    return len(rates) if isinstance(rates, list) else 0


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "LanternWorks-freshness-watchdog", "Cache-Control": "no-cache"})
    last: Exception | None = None
    for attempt in range(FETCH_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001  (retry transient network and HTTP errors)
            last = e
            if attempt < FETCH_ATTEMPTS - 1:
                time.sleep(FETCH_BACKOFF_SEC[attempt])
    assert last is not None
    raise last


def notes_for_workflow(name: str, runs: list[dict], now: datetime, limit: float) -> list[str]:
    """Ignore queued and in-progress runs. Flag a non-success latest completed run, and a last success older than limit."""
    completed = [r for r in runs if isinstance(r, dict) and r.get("status") == "completed"]
    if not completed:
        return [f"{name}: no completed runs"]
    notes: list[str] = []
    latest = completed[0]
    if latest.get("conclusion") != "success":
        notes.append(f"{name}: conclusion {latest.get('conclusion') or latest.get('status')} ({latest.get('url')})")
    successes = [r for r in completed if r.get("conclusion") == "success"]
    if not successes:
        notes.append(f"{name}: no successful run in the listed window (limit {limit:g}h)")
        return notes
    last_ok = successes[0]
    stamp = last_ok.get("updatedAt") or last_ok.get("completedAt") or last_ok.get("createdAt")
    age = _age_hours(stamp, now)
    if age is None:
        notes.append(f"{name}: last successful run has no timestamp ({last_ok.get('url')})")
    elif age > limit:
        notes.append(f"{name}: last success is {age:.1f}h old (limit {limit:g}h) ({last_ok.get('url')})")
    return notes


def workflow_notes(repo: str, now: datetime) -> list[str]:
    notes: list[str] = []
    for name, limit in WORKFLOW_SUCCESS_MAX_HOURS.items():
        try:
            raw = _gh(
                "run", "list", "-R", repo, "--workflow", name, "--status", "completed",
                "--limit", "20", "--json", "conclusion,status,url,updatedAt,createdAt")
            runs = json.loads(raw)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
            notes.append(f"{name}: could not read the latest run ({type(e).__name__})")
            continue
        notes.extend(notes_for_workflow(name, runs if isinstance(runs, list) else [], now, limit))
    return notes


def _gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True, timeout=GH_TIMEOUT_SEC).strip()


def _gh_ok(*args: str) -> None:
    subprocess.check_call(["gh", *args], timeout=GH_TIMEOUT_SEC)


def issue_title(data_problems: list[str], collector_problems: list[str]) -> str:
    if data_problems and collector_problems:
        return TITLE_BOTH
    if collector_problems:
        return TITLE_COLLECTOR
    return TITLE_DATA


def format_body(data_problems: list[str], collector_problems: list[str], holds: list[str], run_url: str) -> str:
    parts = ["Outside check of the live site, the hosted Worker, and the collector runs.", ""]
    if data_problems:
        parts.append("Data freshness:")
        parts.extend(f"- {p}" for p in data_problems)
        parts.append("")
    if collector_problems:
        parts.append("Collector runs:")
        parts.extend(f"- {p}" for p in collector_problems)
        parts.append("")
    if holds:
        parts.append("Held rows:")
        parts.extend(f"- {h}" for h in holds)
        parts.append("")
    if run_url:
        parts.append(f"Run: {run_url}")
    return "\n".join(parts).rstrip() + "\n"


def publish(repo: str, data_problems: list[str], collector_problems: list[str], run_url: str, holds: list[str]) -> None:
    try:
        _gh_ok("label", "create", LABEL, "--repo", repo, "--color", "B60205",
               "--description", "Live feed, availability, stats, hosted MCP, or a collector run needs attention")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass  # label already exists, or create timed out; issue create still carries --label
    title = issue_title(data_problems, collector_problems)
    body = format_body(data_problems, collector_problems, holds, run_url)
    listed = _gh("issue", "list", "-R", repo, "--label", LABEL, "--state", "open",
                 "--json", "number", "-q", ".[0].number // empty")
    if listed:
        _gh_ok("issue", "comment", listed, "-R", repo, "--body", body)
        _gh_ok("issue", "edit", listed, "-R", repo, "--title", title)
    else:
        _gh_ok("issue", "create", "-R", repo, "--title", title, "--label", LABEL, "--body", body)


def close_open(repo: str, run_url: str) -> None:
    listed = _gh("issue", "list", "-R", repo, "--label", LABEL, "--state", "open",
                 "--json", "number", "-q", ".[0].number // empty")
    if not listed:
        return
    _gh_ok("issue", "comment", listed, "-R", repo, "--body",
           f"Fresh again.{(' Run: ' + run_url) if run_url else ''} Closing.")
    _gh_ok("issue", "close", listed, "-R", repo, "--reason", "completed")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", help="ISO time for tests; default is UTC now")
    ap.add_argument("--dry-run", action="store_true", help="print problems, do not open an issue")
    a = ap.parse_args(argv)
    now = _parse(a.now) if a.now else datetime.now(timezone.utc)
    if now is None:
        print("bad --now")
        return 1
    data_problems: list[str] = []
    collector_problems: list[str] = []
    feed: dict | None = None
    hosted: dict | None = None
    stats: dict | None = None
    try:
        feed = _get_json(FEED_URL)
    except Exception as e:  # noqa: BLE001  (network and HTTP errors must still open the issue)
        data_problems.append(f"fetch {FEED_URL} failed: {type(e).__name__}: {e}")
    try:
        hosted = _get_json(HOSTED_VERSION_URL)
    except Exception as e:  # noqa: BLE001
        data_problems.append(f"fetch {HOSTED_VERSION_URL} failed: {type(e).__name__}: {e}")
    try:
        stats = _get_json(STATS_URL)
    except Exception as e:  # noqa: BLE001
        data_problems.append(f"fetch {STATS_URL} failed: {type(e).__name__}: {e}")
    try:
        version, sha = expected_from_checkout()
    except Exception as e:  # noqa: BLE001
        version, sha = "", ""
        data_problems.append(f"expected build is unresolvable: {type(e).__name__}: {e}")
    repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY") or ""
    try:
        collector_problems = workflow_notes(repo, now) if repo else []
    except Exception as e:  # noqa: BLE001
        collector_problems = [f"workflow run lookup failed: {type(e).__name__}: {e}"]
    holds: list[str] = []
    if feed is not None:
        try:
            baseline = committed_rate_count()
        except (OSError, ValueError) as e:
            baseline = None
            data_problems.append(f"committed gpu-prices.json unreadable: {type(e).__name__}")
        data_problems.extend(evaluate(
            feed, hosted or {}, now=now, expected_version=version, expected_build=sha or None,
            committed_rate_count=baseline, stats=stats,
            check_hosted=bool(hosted is not None and version and sha)))
        holds = hold_lines(feed, now)
    elif stats is not None:
        data_problems.extend(age_problems(
            "stats generated_at", stats.get("generated_at"), STATS_MAX_HOURS, now,
            missing="stats generated_at is missing on the live stats.json"))
    problems = data_problems + collector_problems
    if not problems:
        print("fresh")
    else:
        if data_problems:
            print("Data freshness:")
            print("\n".join(data_problems))
        if collector_problems:
            print("Collector runs:")
            print("\n".join(collector_problems))
    if holds:
        print("held:")
        print("\n".join(holds))
    if a.dry_run or not repo:
        return 1 if problems else 0
    run_url = os.environ.get("RUN_URL") or ""
    try:
        if problems:
            publish(repo, data_problems, collector_problems, run_url, holds)
            return 1
        close_open(repo, run_url)
    except Exception as e:  # noqa: BLE001
        print(f"could not update the freshness-watchdog issue: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
