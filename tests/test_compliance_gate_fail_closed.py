"""T4 regression: a missing compliance registry must fail closed (only explicitly approved entries publish)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import generate_seo_pages as g  # noqa: E402


def test_missing_registry_excludes_unapproved(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "COMPLIANCE_PATH", tmp_path / "missing_registry.json")
    monkeypatch.setattr(g, "HELD_IDS", set())
    deals_path = tmp_path / "deals.json"
    deals_path.write_text("{}")
    monkeypatch.setattr(g, "DEALS_PATH", deals_path)
    feed = {"deals": [{"id": "deal-ok", "compliance_status": "approved"},
                      {"id": "deal-pending", "compliance_status": "pending"},
                      {"id": "deal-unknown"}]}
    out = g.apply_compliance_gate(feed)
    assert [d["id"] for d in out["deals"]] == ["deal-ok"]
    assert {"deal-pending", "deal-unknown"} <= g.HELD_IDS
    assert deals_path.read_text() == "{}"  # source feed file is not rewritten
    assert len(feed["deals"]) == 3  # caller's feed object is not mutated
