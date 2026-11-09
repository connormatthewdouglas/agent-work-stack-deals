"""CI: a pinned regenerate must not change committed pages. See scripts/check_generated_pages.py."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_committed_pages_match_pinned_generator():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_generated_pages.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]
