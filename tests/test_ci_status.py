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
