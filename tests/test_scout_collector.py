"""Run Lantern Scout's own scripts with cwd=scout/.

Scripts that read the work-box out/ tree are skipped when that tree is absent. Their assertions are unchanged.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCOUT = Path(__file__).resolve().parents[1] / "scout"
# These read out/*.json or out/RUN_LOG.txt (test_v32 starts by running test_v31, which does too).
NEED_OUT = {
    "test_v30.py", "test_v31.py", "test_v32.py", "test_v33.py", "test_v33d_tamper.py",
    "test_v34.py", "test_v35.py", "test_v35c.py",
}
SCRIPTS = sorted(p.name for p in SCOUT.glob("test_*.py"))


@pytest.mark.parametrize("name", SCRIPTS)
def test_scout_script(name):
    if name in NEED_OUT and not (SCOUT / "out" / "availability_v2_latest.json").is_file():
        pytest.skip("scout out/ snapshot is not in the checkout")
    if name == "test_t113.py" and not (SCOUT / "backup_orig" / "enrich_feed_v2.py").is_file():
        pytest.skip("backup_orig/enrich_feed_v2.py was excluded from the source drop; the script also reads out/ and feed-src")
    # lambda_first() opens secrets/lambda.env before the stubbed fetch. The key is not sent. A gitignored stand-in
    # lets the script run where the work-box file is absent; a file already there is left alone.
    created = None
    if name == "test_t113_lambda.py":
        lam = SCOUT / "secrets" / "lambda.env"
        if not lam.is_file():
            lam.parent.mkdir(exist_ok=True)
            lam.write_text("LAMBDA_API_KEY=scout-test\n")
            created = lam
    try:
        proc = subprocess.run([sys.executable, name], cwd=SCOUT, capture_output=True, text=True, timeout=180)
    finally:
        if created is not None:
            created.unlink(missing_ok=True)
    assert proc.returncode == 0, (proc.stdout[-4000:] + "\n" + proc.stderr[-4000:])
