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


HOLD_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "owner_hold_vendors.json"


@pytest.fixture
def fixed_owner_hold(monkeypatch):
    """Point core.owner_hold at the frozen Hyperstack/Verda hold list, not the live data/owner_hold.json."""
    import core.owner_hold as oh
    monkeypatch.setattr(oh, "CONFIG", HOLD_FIXTURE)
    monkeypatch.setenv("LW_OWNER_HOLD", str(HOLD_FIXTURE))
    return HOLD_FIXTURE
