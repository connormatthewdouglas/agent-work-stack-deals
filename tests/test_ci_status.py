import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ci_status import problems  # noqa: E402

def _ok(**o):
    return {"result": "success", "outputs": {"ok": "true", **o}}

def _green():
    n = {j: _ok() for j in ("validate", "tests", "latest-scout-import", "release-gate", "pypi-install", "docker", "live-checks")}
    n["deploy"] = _ok(deployed="true")
    return n

def test_green_run_passes():
    assert problems(_green(), "push") == []

def test_run_41473330377_cannot_pass():
    n = _green()  # continue-on-error: result 'success' but ok 'false'; deploy and live-checks skipped
    n["tests"] = _ok(ok="false"); n["latest-scout-import"] = _ok(ok="false")
    n["deploy"] = {"result": "skipped", "outputs": {}}; n["live-checks"] = {"result": "skipped", "outputs": {}}
    p = problems(n, "push")
    assert any(x.startswith("tests") for x in p) and any(x.startswith("latest-scout-import") for x in p)
    assert any(x.startswith("deploy") for x in p)

def test_each_required_failure_or_skip_fails():
    for j in ("validate", "tests", "latest-scout-import", "release-gate"):
        for bad in ({"result": "failure", "outputs": {"ok": "false"}}, {"result": "skipped", "outputs": {}}):
            n = _green(); n[j] = bad
            assert problems(n, "push"), (j, bad)
    n = _green(); n["deploy"] = {"result": "success", "outputs": {"ok": "true", "deployed": "false"}}
    assert problems(n, "push")

def test_superseded_and_schedule_ok():
    n = _green(); n["deploy"] = _ok(deployed="superseded"); n["live-checks"] = {"result": "skipped", "outputs": {}}
    assert problems(n, "push") == []
    n = _green(); n["deploy"] = {"result": "skipped", "outputs": {}}
    assert problems(n, "schedule") == [] and problems(n, "pull_request") == []

def test_workflow_has_gate_job_without_continue_on_error():
    import yaml
    w = yaml.safe_load((ROOT / ".github/workflows/validate-and-deploy.yml").read_text())
    j = w["jobs"]["ci-status"]
    assert j["if"] == "always()" and "continue-on-error" not in j
    assert {"tests", "latest-scout-import", "deploy", "validate", "live-checks"} <= set(j["needs"])
    assert "ci_status.py" in j["steps"][-1]["run"]


def test_premerge_scout_import_check_includes_wider_and_t112():
    """The PR import gate must merge the same Scout extras as the live scout-import.yml job.

    A check that only imported availability left 48h-old wider-GPU batch rows held, so
    V100 / rental-page tests failed even when the live importer (which merges wider)
    would have been green after a fresh snapshot.
    """
    chk = (ROOT / "scripts" / "check_latest_scout_import.sh").read_text(encoding="utf-8")
    live = (ROOT / ".github" / "workflows" / "scout-import.yml").read_text(encoding="utf-8")
    for token in ("import_scout_wider.py", "t112_availability_rate_7d.json", "normalize_gpu_sources.py"):
        assert token in chk and token in live, token
