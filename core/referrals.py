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


import re
from urllib.parse import parse_qsl, urlsplit

# Query parameters that carry an affiliate or referral code (any URL with one gets the label; codes are never stripped).
REF_PARAMS = frozenset({"ref", "ref_id", "referral", "referral_code", "aff", "aff_id", "affiliate", "via", "fpr", "fp_ref",
                        "invitecode", "invite", "code", "r", "a_aid", "atp", "red", "deal", "partner", "coupon", "promo"})
_REF_PATH = re.compile(r"/(a|r|aff|invite|join|share|go|refer)/[^/]+", re.I)


def has_ref_code(url: str | None) -> bool:
    if not url:
        return False
    u = urlsplit(url)
    return any(k.lower() in REF_PARAMS for k, _ in parse_qsl(u.query, keep_blank_values=True)) or bool(_REF_PATH.search(u.path))


def referral_fields_for(row: dict) -> dict:
    """Gauge strat2 #4: every row whose link carries an affiliate/referral code is labelled 'Referral link'.
    referral_url is the code-carrying URL as published (RunPod/Thunder Compute: their agent-feed link). Never a ranking input."""
    if row.get("referral_url"):
        return {"referral_url": row["referral_url"], "referral_label": REFERRAL_LABEL}
    adv = row.get("advertiser") or row.get("vendor")
    if adv in REFERRALS:
        return referral_fields(adv)
    url = row.get("redeem_url")
    if row.get("affiliate") or has_ref_code(url):
        return {"referral_url": url, "referral_label": REFERRAL_LABEL}
    return {}
