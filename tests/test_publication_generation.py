"""T68: the published generation agrees across the full feed, the small per-model views and coverage."""
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_one_generation_across_feed_views_and_coverage():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    gen, upd = feed["generation_id"], feed["feed_updated_at"]
    assert gen and upd
    cov = json.loads((ROOT / "api/v1/coverage.json").read_text())
    assert cov["feed_updated_at"] == upd and cov["generation_id"] == gen
    views = glob.glob(str(ROOT / "api/v1/gpu/*.json"))
    assert views
    for f in views:
        d = json.loads(Path(f).read_text())
        assert d.get("generation_id") == gen and d.get("feed_updated_at") == upd, f
