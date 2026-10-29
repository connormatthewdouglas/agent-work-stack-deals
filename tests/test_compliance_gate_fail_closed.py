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
    feed = {"deals": [{"id": "deal-ok", "publish_status": "approved"},
                      {"id": "deal-pending", "publish_status": "pending"},
                      {"id": "deal-unknown"}]}
    out = g.apply_compliance_gate(feed)
    assert [d["id"] for d in out["deals"]] == ["deal-ok"]
    assert {"deal-pending", "deal-unknown"} <= g.HELD_IDS
    assert deals_path.read_text() == "{}"  # source feed file is not rewritten
    assert len(feed["deals"]) == 3  # caller's feed object is not mutated


def test_registry_sets_publish_status_only_on_approved(tmp_path, monkeypatch):
    import json
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"entries": {g.slug_for("deal-a"): {"status": "approved"}, g.slug_for("deal-b"): {"status": "pending"}}}))
    monkeypatch.setattr(g, "COMPLIANCE_PATH", reg)
    monkeypatch.setattr(g, "HELD_PATH", tmp_path / "held.json")
    monkeypatch.setattr(g, "DEALS_PATH", tmp_path / "deals.json")
    monkeypatch.setattr(g, "HELD_IDS", set())
    monkeypatch.setattr(g, "remove_pulled_pages", lambda ids: None)
    feed = {"deals": [{"id": "deal-a"}, {"id": "deal-b", "publish_status": "approved"}]}
    out = g.apply_compliance_gate(feed)
    assert [(d["id"], d.get("publish_status")) for d in out["deals"]] == [("deal-a", "approved")]
    held = json.loads((tmp_path / "held.json").read_text())
    assert held[0]["id"] == "deal-b" and "publish_status" not in held[0]


def test_public_feed_has_no_compliance_fields_and_all_published():
    import json
    feed = json.loads((ROOT / "deals.json").read_text())
    assert all(not k.startswith("compliance_") for d in feed["deals"] for k in d)
    assert all(d.get("publish_status") == "approved" for d in feed["deals"])
