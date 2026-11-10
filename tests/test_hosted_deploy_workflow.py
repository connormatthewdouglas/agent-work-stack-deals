"""Hosted MCP deploy: live /version must match the commit, and CI reuses hosted/deploy.sh."""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_hosted_version as H  # noqa: E402

WF_PATH = ROOT / ".github" / "workflows" / "deploy-hosted-mcp.yml"
SHA = "21684cc5ca768c928e4ecc1d3c957b71c091efbe"


def _workflow():
    # PyYAML 1.1 would treat the key "on" as boolean true. Rename it before loading.
    text = WF_PATH.read_text(encoding="utf-8").replace("\non:", "\ntrigger:")
    return yaml.safe_load(text)


def test_versions_match_requires_a_real_prefix():
    assert H.versions_match({"version": "0.6.2", "build": "21684cc5"}, "0.6.2", SHA)
    assert H.versions_match({"version": "0.6.2", "build": SHA}, "0.6.2", SHA)
    assert not H.versions_match({"version": "0.6.0", "build": "21684cc5"}, "0.6.2", SHA)
    assert not H.versions_match({"version": "0.6.2", "build": "2767db56"}, "0.6.2", SHA)
    assert not H.versions_match({"version": "0.6.2", "build": "21684c"}, "0.6.2", SHA)
    assert not H.versions_match({"version": "0.6.2", "build": ""}, "0.6.2", SHA)


def test_poll_accepts_the_second_sample_and_times_out():
    clock = {"t": 0.0}
    seen = {"n": 0}

    def now():
        return clock["t"]

    def sleep(seconds):
        clock["t"] += seconds

    def fetch():
        seen["n"] += 1
        if seen["n"] < 2:
            return {"version": "0.6.0", "build": "2767db56"}
        return {"version": "0.6.2", "build": SHA}

    assert H.poll_version(fetch, "0.6.2", SHA, timeout_s=30, interval_s=10, sleep=sleep, now=now)["build"] == SHA
    assert seen["n"] == 2

    def stuck():
        return {"version": "0.6.0", "build": "2767db56"}

    clock["t"] = 0.0
    with pytest.raises(SystemExit, match="did not match"):
        H.poll_version(stuck, "0.6.2", SHA, timeout_s=25, interval_s=10, sleep=sleep, now=now)


def test_workflow_dispatches_only_on_main_and_reuses_deploy_sh():
    wf = _workflow()
    job = wf["jobs"]["deploy"]
    assert job["if"] == "github.event_name != 'workflow_dispatch' || github.ref == 'refs/heads/main'"
    assert "published" in wf["trigger"]["release"]["types"]
    assert wf["trigger"]["push"]["tags"] == ["v*"]
    runs = [step.get("run") or "" for step in job["steps"]]
    assert any("sh hosted/deploy.sh" in run for run in runs)
    assert not any("check_benchmark_asset.py" in run or "check_error_contract.py" in run for run in runs)
    env = next(step["env"] for step in job["steps"] if "env" in step)
    assert env["CLOUDFLARE_API_TOKEN"] == "${{ secrets.CLOUDFLARE_API_TOKEN }}"
    assert env["CLOUDFLARE_ACCOUNT_ID"] == "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
    script = (ROOT / "hosted" / "deploy.sh").read_text(encoding="utf-8")
    assert "check_hosted_version.py" in script
    assert "check_benchmark_asset.py --hosted" in script
    assert "check_error_contract.py --hosted" in script
    assert script.index("wrangler deploy") < script.index("check_hosted_version.py") < script.index("check_benchmark_asset.py")
