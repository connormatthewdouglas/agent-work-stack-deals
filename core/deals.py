"""Filter + rank logic for the Lantern Works public deal feed.

Stdlib only. Ranking is by customer value: offer type (verified_discount > free_tier > others),
query relevance, known price, and verified_at freshness. Affiliate status and any commission or
payout data are never ranking inputs, and only an allow-list of public fields is ever returned.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FEED_URL = "https://thelanternworks.com/api/v1/deals.json"
OFFER_TYPES = ("verified_discount", "free_tier", "trial", "standard_referral", "credit_only_referral")
OFFER_TYPE_SCORE = {"verified_discount": 3.0, "free_tier": 2.5, "trial": 1.0,
                    "standard_referral": 0.0, "credit_only_referral": -0.5}
# Allow-list: anything not here (e.g. commission/payout/internal fields) is dropped.
PUBLIC_FIELDS = ("id", "title", "advertiser", "category", "offer_type", "tags", "affiliate", "agent_only",
                 "price_usd", "list_price_usd", "currency", "unit", "billing_period", "promo_code",
                 "redeem_url", "expires_at", "verified_at", "updated_at", "agent_instructions",
                 "docs_url", "source_url", "pricing_note", "claim_note")
SUMMARY_FIELDS = ("id", "title", "advertiser", "category", "offer_type", "price_usd", "unit",
                  "verified_at", "redeem_url", "affiliate")
MAX_LIMIT = 25
DEFAULT_LIMIT = 10
CACHE_TTL_S = 300


class DealError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class FeedLoader:
    """Fetch the public feed with a short in-memory cache. LANTERN_DEALS_FILE overrides (tests/offline)."""

    def __init__(self, url: str | None = None, file: str | None = None, ttl: float = CACHE_TTL_S):
        self.url = url or os.environ.get("LANTERN_DEALS_URL", FEED_URL)
        self.file = file or os.environ.get("LANTERN_DEALS_FILE") or None
        self.ttl = ttl
        self._cache: tuple[float, dict] | None = None

    def load(self) -> dict:
        now = time.monotonic()
        if self._cache and now - self._cache[0] < self.ttl:
            return self._cache[1]
        try:
            if self.file:
                feed = json.loads(Path(self.file).read_text(encoding="utf-8"))
            else:
                req = urllib.request.Request(self.url, headers={"User-Agent": "lantern-works-mcp/0.1"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    feed = json.loads(r.read().decode("utf-8"))
        except Exception as e:  # network, file, or JSON errors
            if self._cache:  # serve stale rather than fail
                return self._cache[1]
            raise DealError("feed_unavailable", f"Could not load deal feed: {type(e).__name__}") from None
        if not isinstance(feed, dict) or not isinstance(feed.get("deals"), list):
            raise DealError("feed_invalid", "Feed is missing a deals[] array")
        self._cache = (now, feed)
        return feed

    def deals(self) -> list[dict]:
        return [d for d in self.load()["deals"] if isinstance(d, dict) and not d.get("example")]


def public_view(deal: dict, fields: tuple[str, ...] = PUBLIC_FIELDS) -> dict:
    return {k: deal.get(k) for k in fields if k in deal}


def _parse_dt(s: Any) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _terms(q: str | None) -> list[str]:
    return [t for t in (q or "").lower().split() if t]


def relevance(deal: dict, terms: list[str]) -> float:
    if not terms:
        return 0.0
    title = (deal.get("title") or "").lower()
    adv = (deal.get("advertiser") or "").lower()
    tags = [t.lower() for t in deal.get("tags") or []]
    other = " ".join(str(deal.get(k) or "") for k in ("unit", "pricing_note", "category")).lower()
    score = 0.0
    for t in terms:
        if t == adv or t in adv.split():
            score += 3
        if t in tags:
            score += 2
        if t in title:
            score += 1.5
        elif t in other:
            score += 0.5
    return score


def rank_key(deal: dict, terms: list[str] | None = None, now: datetime | None = None) -> tuple:
    """Higher customer value sorts first. Never reads affiliate/commission fields."""
    now = now or datetime.now(timezone.utc)
    s = OFFER_TYPE_SCORE.get(deal.get("offer_type") or "standard_referral", 0.0)
    s += relevance(deal, terms or [])
    price = deal.get("price_usd")
    if isinstance(price, (int, float)):
        s += 1.0 if price == 0 else max(0.0, 0.8 - min(price, 200) / 250)  # cheaper is better
    v = _parse_dt(deal.get("verified_at"))
    if v:
        age_days = max(0.0, (now - v).total_seconds() / 86400)
        s += max(0.0, 1.0 - age_days / 90)  # fresh verification up to +1, decays over 90 days
    exp = _parse_dt(deal.get("expires_at"))
    if exp and exp < now:
        s -= 10  # expired offers sink
    return (-round(s, 6), (deal.get("advertiser") or "").lower(), deal.get("id") or "")


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    try:
        pad = "=" * (-len(cursor) % 4)
        o = json.loads(base64.urlsafe_b64decode(cursor + pad))["o"]
        if not isinstance(o, int) or o < 0:
            raise ValueError
        return o
    except Exception:
        raise DealError("invalid_cursor", "cursor is malformed; pass next_cursor from a previous result") from None


def search(deals: list[dict], query: str | None = None, category: str | None = None,
           offer_type: str | None = None, max_price: float | None = None, tags: list[str] | None = None,
           limit: int = DEFAULT_LIMIT, cursor: str | None = None, now: datetime | None = None) -> dict:
    if offer_type and offer_type not in OFFER_TYPES:
        raise DealError("invalid_argument", f"offer_type must be one of {', '.join(OFFER_TYPES)}")
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        raise DealError("invalid_argument", f"limit must be 1..{MAX_LIMIT}")
    if max_price is not None and (not isinstance(max_price, (int, float)) or max_price < 0):
        raise DealError("invalid_argument", "max_price must be a non-negative number")
    terms = _terms(query)
    want_tags = {t.lower() for t in tags or []}
    out = []
    for d in deals:
        if category and (d.get("category") or "").lower() != category.lower():
            continue
        if offer_type and d.get("offer_type") != offer_type:
            continue
        if max_price is not None:
            p = d.get("price_usd")
            if not isinstance(p, (int, float)) or p > max_price:  # null = unknown, excluded
                continue
        if want_tags and not want_tags <= {t.lower() for t in d.get("tags") or []}:
            continue
        if terms and relevance(d, terms) == 0:
            continue
        out.append(d)
    out.sort(key=lambda d: rank_key(d, terms, now))
    offset = _decode_cursor(cursor) if cursor else 0
    page = out[offset:offset + limit]
    nxt = offset + limit
    return {"total": len(out), "count": len(page),
            "results": [public_view(d, SUMMARY_FIELDS) for d in page],
            "next_cursor": _encode_cursor(nxt) if nxt < len(out) else None}


def get_deal(deals: list[dict], deal_id: str) -> dict:
    if not deal_id or not isinstance(deal_id, str):
        raise DealError("invalid_argument", "id is required")
    for d in deals:
        if d.get("id") == deal_id:
            return public_view(d)
    raise DealError("not_found", f"No deal with id {deal_id!r}")


def compare(deals: list[dict], ids: list[str]) -> dict:
    if not isinstance(ids, list) or not 2 <= len(ids) <= 5:
        raise DealError("invalid_argument", "ids must contain 2-5 deal ids")
    if len(set(ids)) != len(ids):
        raise DealError("invalid_argument", "ids must be unique")
    by_id = {d.get("id"): d for d in deals}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise DealError("not_found", f"Unknown deal id(s): {', '.join(missing)}")
    rows = sorted((by_id[i] for i in ids), key=lambda d: rank_key(d))
    cols = ("id", "advertiser", "category", "offer_type", "price_usd", "list_price_usd", "unit",
            "billing_period", "promo_code", "expires_at", "verified_at", "redeem_url", "pricing_note")
    return {"order": "customer_value", "deals": [public_view(d, cols) for d in rows],
            "note": "price_usd null = unknown, not free. Confirm terms on the vendor page before spending."}
