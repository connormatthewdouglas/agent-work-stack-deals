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
    for text in [receipts_page.FIREWALL, "not security certifications", "not an independent endorsement", "Only the summaries are public", "Deferred means untested"]:
        assert text in page
    assert page.count('<article class="receipt"') == 62
    assert 'href="tests/' not in page


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
