import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _restore_build_horizon_env():
    """Importing scripts.generate_seo_pages setdefaults LW_BUILD_HORIZON_MIN=25 for the whole process; restore it after
    each test so later tests don't depend on which test imported the generator first (Gauge nov1_mart4 fix 2)."""
    import os
    before = {k: os.environ.get(k) for k in ("LW_BUILD_HORIZON_MIN", "LW_AVAIL_NOW")}
    yield
    for k, v in before.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
