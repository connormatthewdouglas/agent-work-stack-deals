"""Brain #247 agent feed: referral links shown as additive fields only (referral_url, referral_label).

Only vendors whose referral terms allow sharing get a link. Ranking never reads these fields: GPU rows are
sorted by cost alone (see tests/test_referrals.py). No payout or commission data lives in the public repo.
"""
from __future__ import annotations

REFERRAL_LABEL = "Referral link"
REFERRALS = {
    "RunPod": "https://runpod.io?ref=wuct08gl&sub=agent-feed",
    "Thunder Compute": "https://console.thundercompute.com/signup?ref=organization-live-94ea517d-20b7-4794-b5b1-6e1b8cd2a5a1&utm_medium=referral&utm_source=agent-feed",
}


def referral_fields(advertiser: str | None) -> dict:
    url = REFERRALS.get(advertiser or "")
    return {"referral_url": url, "referral_label": REFERRAL_LABEL} if url else {}
