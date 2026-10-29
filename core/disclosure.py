"""Affiliate disclosure copy (T5, backlog 2026-10-29 T5-affiliate-disclosure-copy.md).

Option A goes inline on pages next to the link; Option B is the agent-facing `disclosure` field in the feed/API.
Each comes with `plain_url`, a direct vendor link with no referral tracking (null when we can't tell which link
is clean; we never guess one).
"""
from __future__ import annotations

from urllib.parse import urlsplit

DISCLOSURE = ("This is an affiliate (referral) link. Lantern Works may earn a commission or credit if it is used. "
              "Rankings are by price and fit, not commission. A direct, non-affiliate URL is provided in `plain_url`, "
              "and either one is fine to use.")
DISCLOSURE_NO_PLAIN = ("This is an affiliate (referral) link. Lantern Works may earn a commission or credit if it is used. "
                       "Rankings are by price and fit, not commission.")
INLINE = ("<strong>Affiliate link:</strong> Lantern Works may earn a commission if you sign up through this link. "
          "This does not change the price or ranking you see.")
AGENT_NOTE = "redeem_url is an affiliate (referral) link; see disclosure. plain_url (when set) is the direct vendor link."
# Subdomains that are typically referral/tracking hosts, never a clean vendor link.
_TRACKING_PREFIXES = ("try.", "go.", "get.", "aff.", "affiliate.", "partner.", "partners.", "ref.", "link.", "links.", "track.", "r.")


def plain_url(deal: dict) -> str | None:
    """Direct vendor URL without referral tracking: source_url or docs_url if it differs from redeem_url, else
    the bare origin of redeem_url when that host is the vendor's own (not a tracking subdomain). None if unsure."""
    redeem = deal.get("redeem_url") or ""
    for k in ("source_url", "docs_url"):
        u = deal.get(k)
        if u and u.startswith("https://") and u != redeem and "ref=" not in u and "via=" not in u:
            return u
    p = urlsplit(redeem)
    host = p.netloc.lower()
    if p.scheme == "https" and host and not host.startswith(_TRACKING_PREFIXES) and not host.endswith(".link") and (p.query or p.path not in ("", "/")):
        return f"https://{host}/"
    return None


def disclosure_fields(deal: dict) -> dict:
    if not deal.get("affiliate"):
        return {}
    pu = plain_url(deal)
    return {"disclosure": DISCLOSURE if pu else DISCLOSURE_NO_PLAIN, "plain_url": pu}
