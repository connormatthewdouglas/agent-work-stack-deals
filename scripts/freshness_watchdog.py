#!/usr/bin/env python3
"""Outside check of the live GPU feed, availability, hosted MCP build, and collector runs.

Fails, and opens or updates one GitHub issue labeled freshness-watchdog, when any of these is true:
  * feed_updated_at older than 26h (same bar as scripts/check_gpu_freshness.py; not loosened)
  * availability_collected_at older than 4h (not loosened)
  * any ranked row's verified_at/checked_at older than 48h (T41-12). Owner-held rows are held,
    not ranked, and do not fail this bar.
  * a timestamp is in the future
  * the rates list is empty or has shrunk to under half the committed feed
  * hosted /version is not pyproject's version, or its build is neither the commit that last changed
    that version line nor a later commit on main that descends from it (#816: hosted/build.sh stamps
    the commit it was built from, so a code-only hotfix redeploy between releases is not a mismatch;
    a build older than the version commit, off main, or unknown still fails)
  * the latest gpu-refresh, scout-import, or lium-collect run is not success
  * that collector's last successful run is older than twice its schedule interval
  * the daily price-history backup (price-history-backup.yml) has no successful run in the last 30h

A fetch or gh error is itself a failure and still updates the issue. Does not edit prices.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FEED_URL = "https://thelanternworks.com/api/v1/gpu-prices.json"
HOSTED_VERSION_URL = "https://lantern-works-mcp.lantern-works.workers.dev/version"
FEED_MAX_HOURS = 26
AVAIL_MAX_HOURS = 4
ROW_MAX_HOURS = 48  # T41-12: oldest verified row
SHRINK_RATIO = 0.5
ISSUE_TITLE = "Freshness watchdog: live feed, availability, or hosted MCP is stale"
LABEL = "freshness-watchdog"
# Hours between expected successful runs. gpu-refresh's 14:47 cron is the same-day fallback, not a
# second required success (daily). scout-import's */10 cron is a backstop; the import runs on a 4-hour slot.
# A last success older than 2x this interval fails the watchdog. The 26h/4h/48h bars are unchanged.
COLLECTORS = (("gpu-refresh.yml", 24), ("lium-collect.yml", 2), ("scout-import.yml", 4))
SUCCESS_WINDOW = 2
WORKFLOWS = tuple(name for name, _h in COLLECTORS)
HEX_BUILD = re.compile(r"^[0-9a-f]{7,}$")


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


def _hex_build(value: str | None) -> str:
    got = (value or "").strip().lower()
    return got if HEX_BUILD.fullmatch(got) else ""


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


def _is_owner_held(vendor: str | None) -> bool:
    """data/owner_hold.json via core.owner_hold (the list merged in #116)."""
    from core.owner_hold import is_held
    return is_held(vendor)


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


def deployed_descends(hosted_build: str, version_sha: str, root: Path | None = None, base: str = "origin/main") -> bool:
    """#816: True when the hosted build is a commit on origin/main's history that has the version commit as an
    ancestor. The baseline is origin/main explicitly (not HEAD), so a workflow_dispatch from another branch cannot
    move it. git errors (unknown commit, missing origin/main, shallow clone) are False, so they still alarm."""
    root = root or ROOT
    got, want = _hex_build(hosted_build), _hex_build(version_sha)
    if not got or not want:
        return False
    try:
        full = subprocess.check_output(["git", "rev-parse", "--verify", "--quiet", f"{got}^{{commit}}"],
                                       cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        for anc, desc in ((want, full), (full, base)):
            if subprocess.call(["git", "merge-base", "--is-ancestor", anc, desc], cwd=root,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
                return False
    except (subprocess.CalledProcessError, OSError):
        return False
    return True


def evaluate(feed: dict, hosted: dict, *, now: datetime, expected_version: str, expected_build: str | None,
             committed_rate_count: int | None = None, workflow_notes: list[str] | None = None,
             deployed_ok: Callable[[str, str], bool] | None = None) -> list[str]:
    """Problems that fail the run. Empty means the checked surfaces are fresh."""
    out: list[str] = []
    for note in workflow_notes or []:
        out.append(note)
    for label, stamp, limit in (
        ("feed_updated_at", feed.get("feed_updated_at"), FEED_MAX_HOURS),
        ("availability_collected_at", feed.get("availability_collected_at"), AVAIL_MAX_HOURS),
    ):
        age = _age_hours(stamp, now)
        if age is None:
            out.append(f"{label} is missing on the live GPU price feed")
        elif age < 0:
            out.append(f"{label} {stamp} is in the future")
        elif age > limit:
            out.append(f"{label} {stamp} is {age:.1f}h old (limit {limit:g}h)")
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
            if _is_owner_held(r.get("advertiser") or r.get("vendor")):
                continue  # held, same as held_stale: not a ranked row that can fail the 48h bar
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
    got_version = str(hosted.get("version") or "").strip()
    if got_version != expected_version:
        out.append(f"hosted MCP version {got_version or '(missing)'} != pyproject {expected_version or '(missing)'}")
    later_ok = (deployed_ok is not None and bool(_hex_build(hosted.get("build"))) and bool(_hex_build(expected_build))
                and deployed_ok(str(hosted.get("build")), str(expected_build)))
    if not builds_match(hosted.get("build"), expected_build) and not later_ok:
        if not _hex_build(expected_build):
            out.append(f"expected build is unresolvable ({expected_build!r}); a build check requires a hex prefix of at least 7")
        elif not _hex_build(hosted.get("build")):
            out.append(f"hosted MCP build is unresolvable ({hosted.get('build')!r}); need a hex prefix of at least 7")
        else:
            out.append(f"hosted MCP build {hosted.get('build')} is neither version commit {expected_build} "
                       "nor a later commit on main descending from it")
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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def collector_problems(latest: dict | None, last_success_at: str | None, *, name: str, interval_h: float,
                       now: datetime) -> list[str]:
    """Latest-run conclusion, plus a failure when the last success is older than 2x the schedule interval."""
    out = []
    if not latest:
        out.append(f"{name}: no runs")
    elif latest.get("conclusion") != "success":
        out.append(f"{name}: conclusion {latest.get('conclusion') or latest.get('status')} ({latest.get('url')})")
    limit = interval_h * SUCCESS_WINDOW
    ts = _parse(last_success_at)
    if ts is None:
        out.append(f"{name}: no successful run within {limit:g}h (2x the {interval_h:g}h schedule)")
    else:
        age = (now - ts).total_seconds() / 3600
        if age > limit:
            out.append(f"{name}: last success is {age:.1f}h old (limit {limit:g}h, 2x the {interval_h:g}h schedule)")
    return out


def workflow_notes(repo: str, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    notes = []
    for name, interval_h in COLLECTORS:
        try:
            latest_raw = subprocess.check_output(
                ["gh", "run", "list", "-R", repo, "--workflow", name, "--limit", "1",
                 "--json", "conclusion,status,url,updatedAt"],
                text=True)
            ok_raw = subprocess.check_output(
                ["gh", "run", "list", "-R", repo, "--workflow", name, "--limit", "1", "--status", "success",
                 "--json", "conclusion,updatedAt,url"],
                text=True)
            latest = (json.loads(latest_raw) or [None])[0]
            ok = (json.loads(ok_raw) or [None])[0]
        except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as e:
            notes.append(f"{name}: could not read the latest run ({type(e).__name__})")
            continue
        notes.extend(collector_problems(latest, (ok or {}).get("updatedAt") if ok else None,
                                        name=name, interval_h=interval_h, now=now))
    return notes


BACKUP_WORKFLOW = "price-history-backup.yml"
BACKUP_MAX_HOURS = 30  # daily backup plus 6h slack


def backup_problems(last_success_at: str | None, now: datetime) -> list[str]:
    ts = _parse(last_success_at)
    if ts is None:
        return [f"{BACKUP_WORKFLOW}: no successful backup run (limit {BACKUP_MAX_HOURS}h)"]
    age = (now - ts).total_seconds() / 3600
    if age > BACKUP_MAX_HOURS:
        return [f"{BACKUP_WORKFLOW}: last successful backup is {age:.1f}h old (limit {BACKUP_MAX_HOURS}h)"]
    return []


def backup_notes(repo: str, now: datetime) -> list[str]:
    try:
        raw = subprocess.check_output(["gh", "run", "list", "-R", repo, "--workflow", BACKUP_WORKFLOW, "--limit", "1",
                                       "--status", "success", "--json", "updatedAt"], text=True)
        ok = (json.loads(raw) or [None])[0]
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as e:
        return [f"{BACKUP_WORKFLOW}: could not read the latest successful run ({type(e).__name__})"]
    return backup_problems((ok or {}).get("updatedAt"), now)


def _gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True).strip()


def publish(repo: str, problems: list[str], run_url: str, holds: list[str]) -> None:
    try:
        subprocess.check_call(["gh", "label", "create", LABEL, "--repo", repo, "--color", "B60205",
                               "--description", "Live feed, availability, or hosted MCP is stale"])
    except subprocess.CalledProcessError:
        pass  # label already exists
    body = "Outside check of the live site, the hosted Worker, and the collector runs.\n\n"
    body += "\n".join(f"- {p}" for p in problems)
    if holds:
        body += "\n\nHeld rows:\n" + "\n".join(f"- {h}" for h in holds)
    if run_url:
        body += f"\n\nRun: {run_url}"
    listed = _gh("issue", "list", "-R", repo, "--label", LABEL, "--state", "open",
                 "--json", "number", "-q", ".[0].number // empty")
    if listed:
        subprocess.check_call(["gh", "issue", "comment", listed, "-R", repo, "--body", body])
    else:
        subprocess.check_call(["gh", "issue", "create", "-R", repo, "--title", ISSUE_TITLE,
                               "--label", LABEL, "--body", body])


CI_STALE_HEADER = "CI staleness (non-blocking: a stale-data check in validate-and-deploy warned instead of failing):"


def publish_ci_stale(repo: str, notes: list[str], run_url: str) -> bool:
    """Route a CI stale-data warning to the freshness-watchdog issue. Deduped: skipped when one of the open issue's
    last 10 comments (or its body) already carries the same notes. Returns True when it posted."""
    notes = [n.strip() for n in notes if n.strip()]
    if not notes:
        return False
    text = CI_STALE_HEADER + "\n" + "\n".join(f"- {n}" for n in notes)
    listed = _gh("issue", "list", "-R", repo, "--label", LABEL, "--state", "open",
                 "--json", "number", "-q", ".[0].number // empty")
    if listed:
        seen = json.loads(_gh("issue", "view", listed, "-R", repo, "--json", "body,comments"))
        bodies = [seen.get("body") or ""] + [c.get("body") or "" for c in (seen.get("comments") or [])[-10:]]
        if any(text in b for b in bodies):
            print(f"freshness-watchdog issue #{listed} already has these notes; not posting again")
            return False
    body = text + (f"\n\nRun: {run_url}" if run_url else "")
    try:
        subprocess.check_call(["gh", "label", "create", LABEL, "--repo", repo, "--color", "B60205",
                               "--description", "Live feed, availability, or hosted MCP is stale"])
    except subprocess.CalledProcessError:
        pass
    if listed:
        subprocess.check_call(["gh", "issue", "comment", listed, "-R", repo, "--body", body])
    else:
        subprocess.check_call(["gh", "issue", "create", "-R", repo, "--title", ISSUE_TITLE, "--label", LABEL,
                               "--body", body])
    return True


def close_open(repo: str, run_url: str) -> None:
    listed = _gh("issue", "list", "-R", repo, "--label", LABEL, "--state", "open",
                 "--json", "number", "-q", ".[0].number // empty")
    if not listed:
        return
    subprocess.check_call(["gh", "issue", "comment", listed, "-R", repo, "--body",
                           f"Fresh again.{(' Run: ' + run_url) if run_url else ''} Closing."])
    subprocess.check_call(["gh", "issue", "close", listed, "-R", repo, "--reason", "completed"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", help="ISO time for tests; default is UTC now")
    ap.add_argument("--dry-run", action="store_true", help="print problems, do not open an issue")
    ap.add_argument("--ci-stale", metavar="FILE",
                    help="post the stale-data notes in FILE (one per line) to the issue and exit; never fails CI")
    a = ap.parse_args(argv)
    if a.ci_stale:
        repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY") or ""
        try:
            notes = Path(a.ci_stale).read_text(encoding="utf-8").splitlines() if Path(a.ci_stale).is_file() else []
            print("\n".join(notes) or "no stale-data notes")
            if notes and repo and not a.dry_run:
                publish_ci_stale(repo, notes, os.environ.get("RUN_URL") or "")
        except Exception as e:  # noqa: BLE001  (routing a warning must never turn CI red)
            print(f"::warning::could not route stale-data notes to the freshness-watchdog issue: {type(e).__name__}")
        return 0
    now = _parse(a.now) if a.now else datetime.now(timezone.utc)
    if now is None:
        print("bad --now")
        return 1
    problems: list[str] = []
    feed: dict | None = None
    hosted: dict | None = None
    try:
        feed = _get_json(FEED_URL)
    except Exception as e:  # noqa: BLE001  (network and HTTP errors must still open the issue)
        problems.append(f"fetch {FEED_URL} failed: {type(e).__name__}: {e}")
    try:
        hosted = _get_json(HOSTED_VERSION_URL)
    except Exception as e:  # noqa: BLE001
        problems.append(f"fetch {HOSTED_VERSION_URL} failed: {type(e).__name__}: {e}")
    try:
        version, sha = expected_from_checkout()
    except Exception as e:  # noqa: BLE001
        version, sha = "", ""
        problems.append(f"expected build is unresolvable: {type(e).__name__}: {e}")
    repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY") or ""
    try:
        notes = workflow_notes(repo, now) if repo else []
    except Exception as e:  # noqa: BLE001
        notes = [f"workflow run lookup failed: {type(e).__name__}: {e}"]
    problems.extend(notes)
    if repo:
        problems.extend(backup_notes(repo, now))
    holds: list[str] = []
    if feed is not None and hosted is not None and version and sha:
        try:
            baseline = committed_rate_count()
        except (OSError, ValueError) as e:
            baseline = None
            problems.append(f"committed gpu-prices.json unreadable: {type(e).__name__}")
        problems.extend(evaluate(feed, hosted, now=now, expected_version=version, expected_build=sha,
                                 committed_rate_count=baseline, workflow_notes=[],
                                 deployed_ok=deployed_descends))
        holds = hold_lines(feed, now)
    elif feed is not None:
        holds = hold_lines(feed, now)
    print("\n".join(problems) if problems else "fresh")
    if holds:
        print("held:")
        print("\n".join(holds))
    if a.dry_run or not repo:
        return 1 if problems else 0
    run_url = os.environ.get("RUN_URL") or ""
    try:
        if problems:
            publish(repo, problems, run_url, holds)
            return 1
        close_open(repo, run_url)
    except Exception as e:  # noqa: BLE001
        print(f"could not update the freshness-watchdog issue: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
