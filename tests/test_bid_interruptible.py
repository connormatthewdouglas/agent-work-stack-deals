"""Bid-priced tiers (e.g. Vast.ai "Interruptible (bid)", "Bid") count as interruptible; labels stay verbatim."""
import copy

import pytest

from core import gpu

RX = gpu.INTERRUPTIBLE_TIER_RE


@pytest.mark.parametrize("tier", ["Bid", "bid price", "Min bid", "Spot", "Preemptible"])
def test_interruptible_labels(tier):
    assert RX.search(tier)


@pytest.mark.parametrize("tier", ["On-demand", "Community Cloud", "Marketplace on-demand", "Forbidden", "Bidirectional link",
                                  "non-interruptible", "Not interruptible"])
def test_not_interruptible_labels(tier):
    assert not RX.search(tier)


def _doc_with_tier(tier, interruptible):
    doc = copy.deepcopy(next(d for d in gpu.load_vendor_files() if d.get("records") and not gpu.record_problems(d)))
    doc["records"][0].update(tier=tier, interruptible=interruptible)
    return doc


def _intr_problems(doc):
    return [p for p in gpu.record_problems(doc) if "interruptible=" in p]


def test_record_problems_accepts_bid_tier_verbatim():
    doc = _doc_with_tier("Bid", True)
    assert _intr_problems(doc) == [] and doc["records"][0]["tier"] == "Bid"
    assert _intr_problems(_doc_with_tier("Bid", False))
    assert _intr_problems(_doc_with_tier("Community Cloud", True))
