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
                       "never affects ranking. Referral links are for a human to open; agents must not open, prefetch or follow them automatically.")
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


RENT_HERE_TOP_N = 3
RENT_HERE_LABEL = "Rent here"
RENT_HERE_LISTS = {
    "compare_gpu_prices": ("results",),
    "find_available_gpus": ("available",),
    "estimate_job_cost": ("results",),
}


def rent_here_line(url: str) -> str:
    return f"{RENT_HERE_LABEL}: {url}"


def add_rent_here(out: dict, tool: str, n: int = RENT_HERE_TOP_N) -> dict:
    """P7: on the top N rows of the booking tools, add a clear Rent here line and rent_url
    (the same counted /go/?src=mcp target as tracked_url). Additive only; ranking never
    reads these fields; receipts are not walked."""
    if not isinstance(out, dict):
        return out
    for key in RENT_HERE_LISTS.get(tool, ()):
        rows = out.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows[:n]:
            if not isinstance(row, dict):
                continue
            url = row.get("tracked_url") or go_link(row)
            if not url:
                continue
            row.setdefault("tracked_url", url)
            row["rent_url"] = url
            row["rent_here"] = rent_here_line(url)
    return out

