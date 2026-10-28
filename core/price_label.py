"""Honest price labels for deals without a single verified price_usd.

Never invents a number. Order of preference:
  1. price_usd (rendered by the caller as $X / unit).
  2. Verified GPU rates for the deal (data/gpu_pricing, ranked only): "From $X/GPU-hr (GPU), checked YYYY-MM-DD".
  3. Plan prices already written in the deal's pricing_note / unit (vendor-page text): "Plan prices listed (see details)".
  4. A label from the offer type: e.g. "Free tier; paid plans on vendor site", "Contact sales / see vendor site".
Validator rule (scripts/check_no_unknown_prices.py): rendered pages and API output must never say a price is
"unknown", "n/a", "null" or leave it blank.
"""
from __future__ import annotations

import re

PRICE_RE = re.compile(r"\$\s?\d|¢|₹|€\s?\d|\d\s?€|£\s?\d", re.I)

OFFER_LABELS = {
    "free_tier": "Free tier; paid plans on vendor site",
    "trial": "Free trial; paid plans on vendor site",
    "verified_discount": "Discount on vendor pricing; see vendor site",
    "listed_discount": "Discount on vendor pricing; see vendor site",
    "credit_only_referral": "Usage-based; referral credit, see vendor site",
}
DEFAULT_LABEL = "Pricing on vendor site"


def has_plan_prices(deal: dict) -> bool:
    return any(PRICE_RE.search(deal.get(k) or "") for k in ("pricing_note", "unit"))


def gpu_from(deal: dict, rates: list[dict] | None) -> dict | None:
    rs = [r for r in (rates or []) if r.get("deal_id") == deal.get("id") and r.get("hourly_equiv_usd") is not None]
    return min(rs, key=lambda r: r["hourly_equiv_usd"]) if rs else None


def price_label(deal: dict, gpu_rates: list[dict] | None = None) -> tuple[str, str]:
    """(label, kind) for a deal with price_usd None. kind: gpu | plans | offer."""
    g = gpu_from(deal, gpu_rates)
    if g:
        return (f"From ${g['hourly_equiv_usd']:.2f}/GPU-hr ({g['gpu']}), checked {str(g.get('verified_at') or g['checked_at'])[:10]}", "gpu")
    if has_plan_prices(deal):
        return ("Plan prices listed (see details)", "plans")
    return (OFFER_LABELS.get(deal.get("offer_type") or "", DEFAULT_LABEL), "offer")
