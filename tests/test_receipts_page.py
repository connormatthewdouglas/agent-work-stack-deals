import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import receipts_page


def test_published_summaries_preserve_verified_source_and_disclose_evidence_limits():
    source = (ROOT / "data/receipts-index.json").read_bytes()
    assert hashlib.sha256(source).hexdigest() == receipts_page.SOURCE_SHA256
    published = json.loads((ROOT / "api/v1/receipts.json").read_text())
    assert published == receipts_page.build(source)
    assert published["tests"] == json.loads(source)["tests"]
    assert sum(published["counts"].values()) == 62
    assert published["counts"]["deferred"] == 16
    page = (ROOT / "receipts/index.html").read_text()
    for text in [receipts_page.FIREWALL, "not security certifications", "not an independent endorsement",
                 "proof-pack page", "Deferred means untested"]:
        assert text in page
    assert page.count('<article class="receipt"') == 62
    assert 'href="tests/' not in page
    assert "House product: made by Lantern Works" in page
    assert 'id="test-000"' in page
    assert "Proof pack v1" in page
    assert "third-party" in page.lower() or "Third-party" in page


def test_bad_source_does_not_publish_ambiguous_results():
    doc = json.loads((ROOT / "data/receipts-index.json").read_text())
    bad = copy.deepcopy(doc)
    bad["tests"].append(bad["tests"][0])
    with pytest.raises(ValueError):
        receipts_page.build(json.dumps(bad).encode())
    bad = copy.deepcopy(doc)
    bad["tests"][0]["category"] = "community"
    with pytest.raises(ValueError):
        receipts_page.build(json.dumps(bad).encode())


def test_proof_pack_v1_stable_pages_and_evidence():
    md = (ROOT / "data" / receipts_page.PROOF_PACK_MD).read_text(encoding="utf-8")
    pack = json.loads((ROOT / "data" / receipts_page.PROOF_PACK_JSON).read_text(encoding="utf-8"))
    assert pack["pack"] == "receipts-proof-pack-v1"
    assert {c["record_id"] for c in pack["cases"]} == {"002", "056", "009"}

    published_pack = json.loads((ROOT / "receipts/proof-pack-v1.json").read_text())
    assert published_pack["pack"] == "receipts-proof-pack-v1"
    assert published_pack["cases"] == pack["cases"]
    assert published_pack["referral_tag"] == "receipts-proofpack"
    api_mirror = json.loads((ROOT / "api/v1/receipts-proof-pack.json").read_text())
    assert api_mirror == published_pack

    index = (ROOT / "receipts/index.html").read_text()
    assert "House product: made by Lantern Works" in index
    assert index.count("House product: made by Lantern Works") == 1

    for spec in receipts_page.PROOF_CASES:
        case = next(c for c in pack["cases"] if c["record_id"] == spec["id"])
        page_path = ROOT / "receipts" / spec["slug"] / "index.html"
        evidence_path = ROOT / "receipts" / spec["slug"] / "evidence.json"
        assert page_path.is_file(), spec["slug"]
        assert evidence_path.is_file(), spec["slug"]
        page = page_path.read_text()
        evidence = json.loads(evidence_path.read_text())
        for key in ("package", "version", "verdict", "tested_at", "observed_summary", "task"):
            assert evidence[key] == case[key]
        assert evidence["third_party"] is True
        assert evidence["house"] is False
        assert evidence["referral_tag"] == "receipts-proofpack"
        assert f"/receipts/{spec['slug']}/" in evidence["stable_url"]
        assert "Third-party MCP server" in page
        assert "House product: made by Lantern Works" not in page
        assert spec["title_verdict"] in page
        assert case["package"] in page
        assert f"ref={receipts_page.REF_PROOF}" in page
        assert f"/receipts/{spec['slug']}/evidence.json" in page
        assert f"/receipts/{spec['slug']}/" in index
        assert "Connor" not in page and "Frosty" not in page
        assert "connormatthew" not in page
        assert "<!-- brand -->" in page
        if spec["id"] == "002":
            assert "+4.0h" in page and "No caveats recorded" in page
        if spec["id"] == "056":
            assert "credential spill" in page and "decoy-password" in page
        if spec["id"] == "009":
            assert "McpError" in page and "traceback, not a weather server" in page


def test_proof_pack_public_pages_scrub_personal_github_handle():
    index = (ROOT / "receipts/index.html").read_text()
    pack = json.loads((ROOT / "receipts/proof-pack-v1.json").read_text())
    assert "connormatthew" not in index
    assert "connormatthew" not in json.dumps(pack)
    # Source data files keep Pax's original wording (including the repo path).
    assert "connormatthewdouglas" in (ROOT / "data" / receipts_page.PROOF_PACK_MD).read_text()
