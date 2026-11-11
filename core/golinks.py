"""T136 (plan Task 7): every MCP tool result that names a provider carries a tagged /go/ link and one referral line.

Each dict in a result that names a provider (advertiser or vendor) gets an additive tracked_url:
  - GO_BASE<deal-id>?src=mcp when the row comes from a feed deal (deal_id, or a deal id in id), or
  - GO_BASE v/<vendor-slug>?src=mcp otherwise; the telemetry worker resolves the slug from the served feeds only
    (a disclosed referral_url, else the vendor's checked source_url), never from the caller, so it is not an open redirect.
The result gets one top-level referral_disclosure line. Existing fields are never changed, ranking never reads these
fields, and receipts (signed quote lines) are left exactly as issued.
"""
from __future__ import annotations

import re

from .deals import GO_BASE

SRC = "mcp"
REFERRAL_DISCLOSURE = ("Provider links (tracked_url) go through Lantern Works' counted /go/ redirect (aggregate counts only) to "
                       "the vendor's listed page; links labelled referral may earn Lantern Works a referral reward or credit, which "
                       "never affects ranking.")
PROVIDER_KEYS = ("advertiser", "vendor")
SKIP_KEYS = frozenset({"receipt", "error", "retrieval", "evidence"})
_DEAL_ID_RE = re.compile(r"^deal-[a-z0-9][a-z0-9-]{0,74}$")


def vendor_slug(name: str) -> str:
    """Same rule as collector/src/index.js vendorSlug: lowercase ASCII letters/digits, runs of anything else -> '-'."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:60]


def go_link(row: dict) -> str | None:
    for k in ("deal_id", "id"):
        v = row.get(k)
        if isinstance(v, str) and _DEAL_ID_RE.match(v):
            return f"{GO_BASE}{v}?src={SRC}"
    name = next((row[k] for k in PROVIDER_KEYS if isinstance(row.get(k), str) and row[k].strip()), None)
    slug = vendor_slug(name) if name else ""
    return f"{GO_BASE}v/{slug}?src={SRC}" if slug else None


def annotate(out: dict) -> dict:
    """Add tracked_url to every provider-naming dict (in place, additive) and referral_disclosure once at the top."""
    found = False

    def walk(o):
        nonlocal found
        if isinstance(o, dict):
            if any(isinstance(o.get(k), str) and o[k].strip() for k in PROVIDER_KEYS):
                if not o.get("tracked_url") and (t := go_link(o)):
                    o["tracked_url"] = t
                found = found or bool(o.get("tracked_url"))
            for k, v in o.items():
                if k not in SKIP_KEYS:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    if isinstance(out, dict):
        walk(out)
        if found:
            out.setdefault("referral_disclosure", REFERRAL_DISCLOSURE)
    return out
