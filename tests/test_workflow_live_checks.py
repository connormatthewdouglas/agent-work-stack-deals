"""T73 F3: a failed live-checks job marks the deploy run failed; pipeline-green never passes it; issue rules unchanged."""
from pathlib import Path

import yaml

WF = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/validate-and-deploy.yml").read_text())


def test_failed_live_checks_fails_the_run():
    job = WF["jobs"]["pipeline-failure-issue"]
    assert "continue-on-error" not in job and "needs.live-checks.outputs.ok == 'false'" in job["if"]
    step = job["steps"][-1]
    assert step["env"]["LIVE_OK"] == "${{ needs.live-checks.outputs.ok }}"
    assert 'sh scripts/pipeline_issue.sh "Validate/deploy"' in step["run"] and "exit 1" in step["run"].split("pipeline_issue.sh")[-1]


def test_green_closes_issue_only_on_real_deploy():
    job = WF["jobs"]["pipeline-green"]
    assert "needs.live-checks.outputs.ok == 'false'" in job["if"]
    assert 'if [ "${{ needs.deploy.outputs.deployed }}" = true ]; then sh scripts/pipeline_issue.sh "Validate/deploy" --green' in job["steps"][-1]["run"]
