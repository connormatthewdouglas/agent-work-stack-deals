"""Public-safe compliance helpers shared by the site generator and the MCP tools.

Pulled listings are stored as sha256(deal id) so the public repo does not name them. The private compliance
registry decides what reaches the public feed at build time (only status "approved" is published), so anything
absent from the feed is treated as not relistable at runtime too.
"""
from __future__ import annotations

import hashlib

PULLED_ID_SHA256 = frozenset({
    "f483983f5dade785816b1dff9ea0dafdf845cfda1f4dab1d18f7526dc8d67827",
    "37cbce2d8ff08ee5d9c16b5ba3ec1214a5ea81631fdf9d16695aa42359c50f3b",
    "48f2b01deb93e9410c524852b038ab0d24c2f3c559df6d2c1265726ef4b80a5d",
    "39855a1e80d49dd19e11c1986b7607d96fa861d0925f73f05974abb691c409ad",
})
BLOCKED_STATUSES = frozenset({"pulled", "do_not_relist", "held"})


def is_pulled(deal_id: str | None, extra: set | frozenset = frozenset()) -> bool:
    if not deal_id:
        return False
    return deal_id in extra or hashlib.sha256(deal_id.encode()).hexdigest() in PULLED_ID_SHA256


def allowed_deal_ids(deals: list[dict]) -> set[str]:
    """Deal ids that may be recommended: in the public feed, not pulled, no blocked compliance status."""
    return {d["id"] for d in deals if d.get("id") and not is_pulled(d["id"])
            and str(d.get("compliance_status") or "").lower() not in BLOCKED_STATUSES}
