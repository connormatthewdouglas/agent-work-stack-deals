"""Gauge rel054 #3: the served feed's updated_at moves whenever its content changes."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_seo_pages as g  # noqa: E402


def test_content_change_bumps_updated_at(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "FEED_STATE_PATH", tmp_path / "s.json")
    src = (ROOT / "deals.json").read_bytes()
    st = g.refresh_feed_state(src, datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
    out = json.loads(g.api_v1_bytes(src, st))
    assert out["updated_at"] == "2026-11-02T12:00+00:00"
    d = json.loads(src); d["deals"][0]["title"] += " x"
    src2 = json.dumps(d).encode()
    st2 = g.refresh_feed_state(src2, datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc))
    assert json.loads(g.api_v1_bytes(src2, st2))["updated_at"] == "2026-11-03T12:00+00:00"
    assert g.refresh_feed_state(src2, datetime(2026, 11, 9, tzinfo=timezone.utc)) == st2  # unchanged content: no bump


def test_committed_feed_matches_state():
    feed = json.loads((ROOT / "api" / "v1" / "deals.json").read_text())
    st = json.loads((ROOT / "data" / "feed_state.json").read_text())
    assert g._feed_hash(feed) == st["content_sha256"] and feed["updated_at"] >= "2026-11-02"
