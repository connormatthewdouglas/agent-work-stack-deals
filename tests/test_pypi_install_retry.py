"""Gauge rel042: the published-package install retries while PyPI's index catches up (5 tries, 30 s apart)."""
import subprocess, sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import test_pypi_install as T  # noqa: E402


def _runner(fail_times):
    calls = []
    def r(cmd, **kw):
        calls.append(cmd)
        if len(calls) <= fail_times:
            raise subprocess.CalledProcessError(1, cmd)
        return "ok"
    return r, calls


def test_succeeds_after_index_lag():
    r, calls = _runner(2); slept = []
    assert T.pip_install_retry(["pip"], runner=r, sleep=slept.append) == "ok"
    assert len(calls) == 3 and slept == [30, 30]


def test_gives_up_after_five_attempts():
    r, calls = _runner(99); slept = []
    with pytest.raises(subprocess.CalledProcessError):
        T.pip_install_retry(["pip"], runner=r, sleep=slept.append)
    assert len(calls) == 5 and slept == [30] * 4
