"""dispatch_deploy_after_push.sh: wait for main, then dispatch; retry a stale run.

No live GitHub calls. gh is a stub on PATH. Covers the 2026-11-25 scout-import
race (push 604562fc8, run 45619454895 resolved 030301b589).
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dispatch_deploy_after_push.sh"
TARGET = "604562fc8b54d6ef32df2544d2d03c012ae01a75"
STALE = "030301b589bf61dc359958da4b9d0fef990fa1d4"
WORKFLOWS = (
    "scout-import.yml",
    "lium-collect.yml",
    "gpu-refresh.yml",
)

GH_STUB = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

state_path = Path(os.environ["GH_STUB_STATE"])
log_path = Path(os.environ["GH_STUB_LOG"])
state = json.loads(state_path.read_text(encoding="utf-8"))
argv = sys.argv[1:]
log_path.write_text(
    log_path.read_text(encoding="utf-8") + json.dumps(argv) + "\n",
    encoding="utf-8",
)

def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")

if argv[:1] == ["api"] and argv[1:2] and str(argv[1]).endswith("/commits/main"):
    queue = state.setdefault("main_shas", [])
    if queue:
        sha = queue.pop(0)
        state["main_shas"] = queue or [sha]
    else:
        sha = state.get("main_sha", "")
    save()
    sys.stdout.write(sha + "\n")
    sys.exit(0)

if argv[:3] == ["workflow", "run", "validate-and-deploy.yml"]:
    state["dispatches"] = int(state.get("dispatches") or 0) + 1
    save()
    sys.exit(0)

if argv[:2] == ["run", "list"]:
    n = int(state.get("dispatches") or 0)
    by = state.get("runs_by_dispatch") or {}
    # "0" = before any dispatch; "1" = after first dispatch, ...
    runs = by.get(str(n), by.get(n, []))
    sys.stdout.write(json.dumps(runs) + "\n")
    sys.exit(0)

sys.stderr.write("gh-stub: unexpected argv %s\n" % (argv,))
sys.exit(2)
'''


def _setup(tmp_path: Path, *, main_shas, runs_by_dispatch, **env_extra):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state.json"
    log = tmp_path / "gh.log"
    log.write_text("", encoding="utf-8")
    state.write_text(
        json.dumps({"main_shas": list(main_shas), "dispatches": 0, "runs_by_dispatch": runs_by_dispatch}),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["GH_REPO"] = "connormatthewdouglas/agent-work-stack-deals"
    env["GH_STUB_STATE"] = str(state)
    env["GH_STUB_LOG"] = str(log)
    env["LW_DISPATCH_WAIT_SECONDS"] = "2"
    env["LW_DISPATCH_POLL_SECONDS"] = "0"
    env["LW_DISPATCH_RUN_WAIT_SECONDS"] = "2"
    env["LW_DISPATCH_MAX_REDISPATCH"] = "2"
    # Token stays in the env for a real gh; the stub never needs it, and the
    # script must not put it on argv or in stdout/stderr.
    env["GH_TOKEN"] = "should-never-appear-in-logs-or-argv"
    env.update(env_extra)
    return env, state, log


def _run(env, sha=TARGET):
    return subprocess.run(
        ["sh", str(SCRIPT), sha],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def _argv_log(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def _dispatches(log: Path) -> list[list[str]]:
    return [row for row in _argv_log(log) if row[:2] == ["workflow", "run"]]


def test_match_dispatches_once_on_pushed_sha(tmp_path):
    env, _, log = _setup(
        tmp_path,
        main_shas=[TARGET],
        runs_by_dispatch={
            "0": [],
            "1": [{"databaseId": 45619454896, "headSha": TARGET, "status": "queued", "event": "workflow_dispatch"}],
        },
    )
    proc = _run(env)
    assert proc.returncode == 0, proc.stderr
    assert f"main is at {TARGET}" in proc.stdout
    assert f"run 45619454896 is on {TARGET}" in proc.stdout
    assert _dispatches(log) == [["workflow", "run", "validate-and-deploy.yml", "--ref", "main"]]
    blob = proc.stdout + proc.stderr + log.read_text(encoding="utf-8")
    assert "should-never-appear-in-logs-or-argv" not in blob


def test_timeout_fails_loudly_without_dispatch(tmp_path):
    env, _, log = _setup(
        tmp_path,
        main_shas=[STALE],
        runs_by_dispatch={"0": []},
        LW_DISPATCH_WAIT_SECONDS="0",
    )
    proc = _run(env)
    assert proc.returncode == 1
    assert "timed out after 0s waiting for main to reach" in proc.stderr
    assert TARGET in proc.stderr
    assert STALE in proc.stderr
    assert _dispatches(log) == []
    assert "should-never-appear-in-logs-or-argv" not in proc.stdout + proc.stderr


def test_stale_run_is_redispatched_then_matches(tmp_path):
    env, _, log = _setup(
        tmp_path,
        main_shas=[TARGET],
        runs_by_dispatch={
            "0": [],
            "1": [{"databaseId": 111, "headSha": STALE, "status": "queued", "event": "workflow_dispatch"}],
            "2": [
                {"databaseId": 222, "headSha": TARGET, "status": "queued", "event": "workflow_dispatch"},
                {"databaseId": 111, "headSha": STALE, "status": "queued", "event": "workflow_dispatch"},
            ],
        },
    )
    proc = _run(env)
    assert proc.returncode == 0, proc.stderr
    assert "run 111 is on stale head" in proc.stderr
    assert f"run 222 is on {TARGET}" in proc.stdout
    assert len(_dispatches(log)) == 2


def test_stale_run_gives_up_after_bounded_redispatch(tmp_path):
    env, _, log = _setup(
        tmp_path,
        main_shas=[TARGET],
        runs_by_dispatch={
            "0": [],
            "1": [{"databaseId": 1, "headSha": STALE, "status": "queued", "event": "workflow_dispatch"}],
            "2": [
                {"databaseId": 2, "headSha": STALE, "status": "queued", "event": "workflow_dispatch"},
                {"databaseId": 1, "headSha": STALE, "status": "queued", "event": "workflow_dispatch"},
            ],
            "3": [
                {"databaseId": 3, "headSha": STALE, "status": "queued", "event": "workflow_dispatch"},
                {"databaseId": 2, "headSha": STALE, "status": "queued", "event": "workflow_dispatch"},
            ],
        },
        LW_DISPATCH_MAX_REDISPATCH="2",
    )
    proc = _run(env)
    assert proc.returncode == 1
    assert "gave up after 3 dispatch(es)" in proc.stderr
    assert len(_dispatches(log)) == 3


def test_collector_workflows_call_the_helper_not_a_bare_dispatch():
    needle = 'sh scripts/dispatch_deploy_after_push.sh "$(git rev-parse HEAD)"'
    bare = "gh workflow run validate-and-deploy.yml --ref main"
    for name in WORKFLOWS:
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert needle in text, name
        assert bare not in text, name
        # Still after a successful push, not instead of it.
        assert text.find("rebase_push_main.sh") < text.find(needle)


def test_script_rejects_a_short_sha(tmp_path):
    env, _, log = _setup(tmp_path, main_shas=[TARGET], runs_by_dispatch={"0": []})
    proc = _run(env, sha="604562fc8")
    assert proc.returncode == 2
    assert "full 40-character" in proc.stderr
    assert _dispatches(log) == []
