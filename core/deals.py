"""Filter + rank logic for the Lantern Works public deal feed.

Stdlib only. Ranking is by customer value: offer type (verified_discount > free_tier > others),
query relevance, known price, and verified_at freshness. Affiliate status and any commission or
payout data are never ranking inputs, and only an allow-list of public fields is ever returned.
"""
from __future__ import annotations

import re
import base64
import json
import os
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any



def usd(x) -> str:
    """Gauge G7: at least 2 decimals, up to 4 when the source has them ($2.60, $0.555, $0.8045)."""
    t = f"{float(x):.4f}".rstrip("0")
    return "$" + (t + "0" * (2 - len(t.split(".")[1])))

VERSION = "0.6.3"  # package version (pyproject + server.json must match; tests enforce)
# Non-identifying: product/version only, no host, user, or install id.
USER_AGENT = f"lantern-works-deals-mcp/{VERSION} (pypi-client)"  # T51: distinct UA for the installed client's own fetches
FEED_URL = "https://thelanternworks.com/api/v1/deals.json"
GPU_PRICES_URL = "https://thelanternworks.com/api/v1/gpu-prices.json"
STACK_PRICING_URL = "https://thelanternworks.com/api/v1/stack-pricing.json"
GPU_HISTORY_URL = "https://thelanternworks.com/api/v1/gpu-prices/history.json"
GPU_CHANGES_URL = "https://thelanternworks.com/api/v1/gpu-price-changes.json"
REFRESH_UTC = (10, 23)  # .github/workflows/gpu-refresh.yml cron "23 10 * * *"
OFFER_TYPES = ("verified_discount", "listed_discount", "free_tier", "trial", "standard_referral", "credit_only_referral")
OFFER_TYPE_SCORE = {"verified_discount": 3.0, "free_tier": 2.5, "trial": 1.0, "listed_discount": 1.0,
                    "standard_referral": 0.0, "credit_only_referral": -0.5}
# Allow-list: anything not here (e.g. commission/payout/internal fields) is dropped.
PUBLIC_FIELDS = ("id", "title", "advertiser", "category", "offer_type", "tags", "affiliate", "agent_only",
                 "price_usd", "list_price_usd", "currency", "unit", "billing_period", "promo_code",
                 "redeem_url", "expires_at", "verified_at", "updated_at", "agent_instructions",
                 "docs_url", "source_url", "pricing_note", "claim_note", "signup", "signup_note", "price_null_reason", "tracked_url")
SUMMARY_FIELDS = ("id", "title", "advertiser", "category", "offer_type", "price_usd", "unit",
                  "verified_at", "redeem_url", "affiliate", "signup", "price_null_reason", "source_url")
NO_CITED_PRICE = "no cited price"


def cite_guard(deal: dict) -> dict:
    """Gauge rel053/Fly: a price with no source_url plus check date (verified_at/checked_at) is never served. Such a deal
    gets price_usd/list_price_usd null and an additive price_null_reason, so an uncited 0 never reads as free."""
    if not isinstance(deal, dict) or (deal.get("source_url") and (deal.get("verified_at") or deal.get("checked_at"))):
        return deal
    return {**deal, "price_usd": None, "list_price_usd": None, "price_null_reason": NO_CITED_PRICE}


# /go/<deal-id> click redirect (telemetry worker): 302s to the deal's stored redeem_url, counting day x deal x src
# (no IP, cookie or id). Additive field: redeem_url stays the direct link.
GO_BASE = "https://lantern-works-telemetry.lantern-works.workers.dev/go/"


def tracked_url(deal: dict, src: str) -> str | None:
    if not isinstance(deal, dict) or not deal.get("id") or not deal.get("redeem_url") or deal.get("example"):
        return None
    return f"{GO_BASE}{deal['id']}?src={src}"


def _with_tracked(deal: dict, src: str) -> dict:
    t = tracked_url(deal, src)
    return {**deal, "tracked_url": t} if t else deal


def cite_guard_feed(feed: dict) -> dict:
    return {**feed, "deals": [_with_tracked(cite_guard(d), "feed") for d in feed.get("deals") or []]}


MAX_LIMIT = 25
DEFAULT_LIMIT = 10
CACHE_TTL_S = 300


class DealError(Exception):
    def __init__(self, code: str, message: str, reason: str | None = None):
        super().__init__(message)
        self.code, self.message = code, message
        self.reason = reason  # machine-readable cause for callers (e.g. "min_gpus": every row needs more GPUs)

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


STALE_CURRENT_MAX_S = 3600  # T45 policy: after a failed refresh, cached data serves *current* answers for at most 1 h


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if ts else None


class FeedLoader:
    """Fetch the public feed with a short in-memory cache. LANTERN_DEALS_FILE overrides (tests/offline).

    T45: every refresh attempt is recorded. If a refresh fails (outage) or returns an unusable feed (partial
    refresh), the last good copy is served and status() reports retrieval="degraded" with the last successful
    retrieval time and the failure. Current-price loaders (CURRENT=True) refuse cached data whose last successful
    retrieval is older than STALE_CURRENT_MAX_S (feed_unavailable); history loaders keep serving it. A later
    successful refresh clears the degraded state. Price verification times stay in the feed's own fields."""

    DEFAULT_URL, URL_ENV, FILE_ENV, LIST_KEY, LABEL = FEED_URL, "LANTERN_DEALS_URL", "LANTERN_DEALS_FILE", "deals", "deal feed"
    CURRENT = True

    def __init__(self, url: str | None = None, file: str | None = None, ttl: float = CACHE_TTL_S, clock=None):
        self.url = url or os.environ.get(self.URL_ENV, self.DEFAULT_URL)
        self.file = file or os.environ.get(self.FILE_ENV) or None
        self.ttl = ttl
        self.clock = clock or time.time
        self._cache: tuple[float, dict] | None = None   # (wall time of last successful retrieval, feed)
        self._attempt_at: float | None = None
        self._outcome: str | None = None

    def _fetch(self) -> Any:
        if self.file:
            return json.loads(Path(self.file).read_text(encoding="utf-8"))
        req = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))

    def status(self) -> dict:
        ok_at = self._cache[0] if self._cache else None
        degraded = self._outcome not in (None, "ok")
        age = round(self.clock() - ok_at) if ok_at else None
        return {"feed": self.LABEL, "retrieval": "degraded" if degraded else ("ok" if ok_at else "not_loaded"),
                "last_successful_retrieval_at": _iso(ok_at), "last_refresh_attempt_at": _iso(self._attempt_at),
                "last_refresh_outcome": self._outcome, "stale_cache": bool(degraded and ok_at), "cache_age_s": age}

    def load(self) -> dict:
        now = self.clock()
        if self._cache and self._outcome == "ok" and now - self._cache[0] < self.ttl:
            return self._cache[1]
        self._attempt_at = now
        try:
            feed = self._fetch()
            if not isinstance(feed, dict) or not isinstance(feed.get(self.LIST_KEY), list):
                raise DealError("feed_invalid", f"Feed is missing a {self.LIST_KEY}[] array")
        except Exception as e:  # network, file, JSON or shape errors
            code = e.code if isinstance(e, DealError) else "feed_unavailable"
            self._outcome = ("invalid" if code == "feed_invalid" else "failed") + f": {type(e).__name__}"
            if self._cache:  # serve the last good copy, visibly degraded
                age = now - self._cache[0]
                if self.CURRENT and age > STALE_CURRENT_MAX_S:
                    raise DealError("feed_unavailable",
                                    f"Could not refresh {self.LABEL} ({self._outcome}); last successful retrieval "
                                    f"{_iso(self._cache[0])} is {int(age // 60)} min old, past the "
                                    f"{STALE_CURRENT_MAX_S // 60} min limit for current prices") from None
                return self._cache[1]
            if code == "feed_invalid":
                raise DealError("feed_invalid", f"Feed is missing a {self.LIST_KEY}[] array") from None
            raise DealError("feed_unavailable", f"Could not load {self.LABEL}: {type(e).__name__}") from None
        self._cache = (now, feed)
        self._outcome = "ok"
        return feed

    def deals(self) -> list[dict]:
        return [cite_guard(d) for d in self.load()["deals"] if isinstance(d, dict) and not d.get("example")]


class GpuPricesLoader(FeedLoader):
    """The published /api/v1/gpu-prices.json (same file the site serves). LANTERN_GPU_PRICES_FILE overrides."""
    DEFAULT_URL, URL_ENV, FILE_ENV, LIST_KEY, LABEL = (GPU_PRICES_URL, "LANTERN_GPU_PRICES_URL",
                                                       "LANTERN_GPU_PRICES_FILE", "rates", "GPU prices")



class GpuHistoryLoader(FeedLoader):
    """The published /api/v1/gpu-prices/history.json (daily snapshots as change points). LANTERN_GPU_HISTORY_FILE overrides."""
    DEFAULT_URL, URL_ENV, FILE_ENV, LIST_KEY, LABEL = (GPU_HISTORY_URL, "LANTERN_GPU_HISTORY_URL",
                                                       "LANTERN_GPU_HISTORY_FILE", "series", "GPU price history")
    CURRENT = False  # T45: historical evidence stays readable from cache


class GpuChangesLoader(FeedLoader):
    """The published /api/v1/gpu-price-changes.json (moves between the two latest daily snapshots). LANTERN_GPU_CHANGES_FILE overrides."""
    DEFAULT_URL, URL_ENV, FILE_ENV, LIST_KEY, LABEL = (GPU_CHANGES_URL, "LANTERN_GPU_CHANGES_URL",
                                                       "LANTERN_GPU_CHANGES_FILE", "changes", "GPU price changes")
    CURRENT = False  # T45: historical evidence stays readable from cache


def next_refresh_utc(now: datetime | None = None) -> str:
    """Next scheduled daily price refresh (10:23 UTC). GitHub cron can start a few minutes late."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    nxt = now.replace(hour=REFRESH_UTC[0], minute=REFRESH_UTC[1], second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return nxt.strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_checked_at(values) -> str | None:
    """Newest timestamp among values (ISO strings), returned in UTC."""
    best = None
    for v in values:
        dt = _parse_dt(v)
        if dt and dt.tzinfo and (best is None or dt > best):
            best = dt
    return best.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if best else None


def freshness(data_checked_at: str | None, now: datetime | None = None) -> dict:
    since = (data_checked_at or "")[:10] or None
    return {"data_checked_at": data_checked_at, "next_refresh_utc": next_refresh_utc(now),
            "refresh_hint": "Prices refresh daily; call get_price_changes(" + (f"since='{since}'" if since else "") +
                            ") to see what moved."}


CHANGE_KINDS = ("down", "up", "new", "removed", "same")


def _key_vram(key: str | None):
    parts = (key or "").split("|")
    return parts[3] if len(parts) >= 5 and parts[3] not in ("", "None") else None


def _cursor_page(history: dict, cursor: str, gpu: str | None, kinds: set | None, limit: int) -> tuple[list, dict]:
    """Rows after `cursor`, oldest first (lossless catch-up), plus paging fields."""
    from .ids import decode_cursor, encode_cursor
    c = decode_cursor(cursor)
    if c is None:
        raise DealError("invalid_cursor", "cursor is not a valid get_price_changes cursor; pass next_cursor exactly as returned")
    events = sorted((e for e in history.get("changes") or [] if isinstance(e.get("seq"), int)), key=lambda e: e["seq"])
    by_seq = {e["seq"]: e for e in events}
    last_seq = events[-1]["seq"] if events else 0
    anchor = by_seq.get(c["seq"])
    if c["seq"] > last_seq or (c["seq"] > 0 and (anchor is None or anchor.get("event_id") != c["eid"])):
        day = (c.get("eid") or "").split(":")[0] or history.get("first_snapshot")
        raise DealError("cursor_expired",
                        f"cursor no longer matches the published history (rebuilt or rolled back). Re-sync with "
                        f"get_price_changes(since='{day}') and dedupe by event_id; then continue with its next_cursor.")
    out, scanned_to, more = [], c["seq"], False
    for e in events:
        if e["seq"] <= c["seq"]:
            continue
        row = _history_row(e)
        if gpu and gpu.lower() not in (row.get("gpu") or "").lower():
            scanned_to = e["seq"]
            continue
        if kinds and row["direction"] not in kinds:
            scanned_to = e["seq"]
            continue
        if len(out) >= limit:
            more = True
            break
        out.append(row)
        scanned_to = e["seq"]
    nxt = encode_cursor(scanned_to, by_seq[scanned_to]["event_id"] if scanned_to else None)
    return out, {"next_cursor": nxt, "has_more": more, "order": "oldest first (seq ascending)", "last_seq": last_seq}


def _direction(a, b, kind=None):
    if a is not None and b is not None:
        return "down" if b < a else "up" if b > a else "same"
    return kind if kind in ("new", "removed") else "new" if a is None else "removed"


def _history_row(c: dict) -> dict:
    r = {"date": c.get("date"), "event_id": c.get("event_id"), "seq": c.get("seq"), "key": c.get("key"),
         "rate_id": c.get("rate_id"), "snapshot_id": c.get("snapshot_id"), "vendor": c.get("vendor"), "gpu": c.get("gpu"),
         "tier": c.get("tier"), "vram_gb": c.get("vram_gb"), "from_hourly_usd": c.get("from_hourly_usd"),
         "to_hourly_usd": c.get("to_hourly_usd"), "change_pct": c.get("change_pct"),
         "status": c.get("status"), "source_url": c.get("source_url"),
         # P46 (additive): last check at the previous price and days to the check that showed the new one (null if unknown)
         "last_verified_before": c.get("last_verified_before"), "gap_days": c.get("gap_days"),
         # P45 (additive)
         "composition_flag": c.get("composition_flag"),
         **({k: c[k] for k in ("lowest_offer_usd", "offer_count", "previous_lowest_offer_usd", "previous_offer_count") if k in c})}
    r["direction"] = _direction(r["from_hourly_usd"], r["to_hourly_usd"])
    return r


def price_changes(latest: dict | None, history: dict | None, since: str | None = None, gpu: str | None = None,
                  limit: int = 50, cursor: str | None = None, kinds: list[str] | None = None) -> dict:
    """GPU price moves among tracked providers. since=None: the latest daily move (/api/v1/gpu-price-changes.json);
    since='YYYY-MM-DD': every move on or after that date (/api/v1/gpu-prices/history.json), newest first.
    cursor: every history event after the cursor, oldest first, with next_cursor/has_more (lossless watchers).
    kinds: optional subset of down/up/new/removed/same."""
    from .ids import encode_cursor, event_id, rate_id
    if since is not None:
        try:
            since = date.fromisoformat(str(since)[:10]).isoformat()
        except ValueError:
            raise DealError("invalid_argument", "since must be a date like 2026-10-27") from None
    if cursor is not None and since is not None:
        raise DealError("invalid_argument", "pass either cursor or since, not both")
    if isinstance(kinds, str):
        kinds = [k.strip() for k in kinds.split(",") if k.strip()]
    if kinds:
        bad = [k for k in kinds if k not in CHANGE_KINDS]
        if bad:
            raise DealError("invalid_argument", f"kinds must be among {', '.join(CHANGE_KINDS)}; got {', '.join(map(str, bad))}")
    kset = set(kinds) if kinds else None
    limit = max(1, min(int(limit or 50), 200))
    paging = None
    if cursor is not None:
        doc = history or {}
        rows, paging = _cursor_page(doc, cursor, gpu, kset, limit)
        window = {"from": rows[0]["date"] if rows else None, "to": doc.get("last_snapshot")}
        src, covered = GPU_HISTORY_URL, {"first_snapshot": doc.get("first_snapshot"), "last_snapshot": doc.get("last_snapshot"),
                                         "snapshot_count": doc.get("snapshot_count")}
    elif since is None:
        doc = latest or {}
        rows = []
        for c in doc.get("changes") or []:
            r = {"date": doc.get("date"), "key": c.get("key"), "vendor": c.get("vendor"), "gpu": c.get("gpu"), "tier": c.get("tier"),
                 "gpu_count": c.get("gpu_count", 1), "from_hourly_usd": c.get("old_hourly_usd"),
                 "to_hourly_usd": c.get("new_hourly_usd"), "change_pct": c.get("pct"), "source_url": c.get("source_url"),
                 "verified_at": c.get("verified_at"),
                 "last_verified_before": c.get("last_verified_before"), "gap_days": c.get("gap_days"),  # P46 (additive)
                 "composition_flag": c.get("composition_flag"),  # P45 (additive)
                 **({k: c[k] for k in ("lowest_offer_usd", "offer_count", "previous_lowest_offer_usd", "previous_offer_count") if k in c})}
            r["direction"] = _direction(r["from_hourly_usd"], r["to_hourly_usd"], c.get("change"))
            r["rate_id"] = rate_id({**r, "vram_gb": c.get("vram_gb") or _key_vram(c.get("key")),
                                    "billing_unit": c.get("billing_unit") or "hourly"})
            r["event_id"] = event_id(doc.get("date") or "", r["rate_id"], r["direction"])
            rows.append(r)
        window = {"from": doc.get("previous_date"), "to": doc.get("date")}
        src, covered = GPU_CHANGES_URL, None
    else:
        doc = history or {}
        rows = [_history_row(c) for c in doc.get("changes") or [] if (c.get("date") or "") >= since]
        window = {"from": since, "to": doc.get("last_snapshot")}
        src, covered = GPU_HISTORY_URL, {"first_snapshot": doc.get("first_snapshot"), "last_snapshot": doc.get("last_snapshot"),
                                         "snapshot_count": doc.get("snapshot_count")}
    if paging is None:
        if gpu:
            q = gpu.lower()
            rows = [r for r in rows if q in (r.get("gpu") or "").lower()]
        if kset:
            rows = [r for r in rows if r["direction"] in kset]
        rank = {"down": 0, "up": 1, "removed": 2, "new": 3, "same": 4}
        rows.sort(key=lambda r: (r.get("vendor") or "", r.get("gpu") or ""))
        rows.sort(key=lambda r: rank[r["direction"]])
        rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    def _is_price(r):
        # P45: only composition_flag == 'price' (or a non-marketplace row with no flag) is a price move
        if r["direction"] not in ("down", "up"):
            return False
        return r.get("composition_flag") in (None, "price")
    down = sum(_is_price(r) and r["direction"] == "down" for r in rows)
    up = sum(_is_price(r) and r["direction"] == "up" for r in rows)
    added = sum(r["direction"] == "new" for r in rows)
    removed = sum(r["direction"] == "removed" for r in rows)
    comp_n = sum(r["direction"] in ("down", "up") and r.get("composition_flag") in ("composition", "mixed") for r in rows)
    unk_n = sum(r["direction"] in ("down", "up") and r.get("composition_flag") == "unknown" for r in rows)
    bits = [f"{down} price down", f"{up} price up"]
    if comp_n:
        bits.append(f"{comp_n} composition (not a price move)")
    if unk_n:
        bits.append(f"{unk_n} composition unknown (not classified as a price move)")
    bits += [f"{added} newly tracked", f"{removed} no longer tracked"]
    out = {"scope": "tracked providers only (not the whole market); prices per GPU-hour, USD",
           "window": window, "total": len(rows), "count": min(len(rows), limit), "price_drops": down, "price_rises": up,
           "newly_tracked": added, "no_longer_tracked": removed,
           "composition_changes": comp_n, "composition_unknown": unk_n,
           "changes": rows[:limit], "data_source": src,
           "summary": (f"{len(rows)} tracked GPU change(s)" + (f" for '{gpu}'" if gpu else "") +
                       f" between {window['from']} and {window['to']}: " + ", ".join(bits) + "."),
           "sorted_by": "date (newest first), then price drops, rises, removals, new rates",
           "note": "'new' = a rate first tracked in this window (no earlier price to compare). Each change cites the vendor source_url it was read from. Confirm on the vendor page before spending. Dedupe on event_id."}
    if paging is not None:
        out.update(paging)
        out["sorted_by"] = "seq ascending (oldest first); save next_cursor only after you have processed these changes"
        out["total"] = out["count"] = len(rows)
        bits = [f"{down} price down", f"{up} price up"]
        if comp_n:
            bits.append(f"{comp_n} composition (not a price move)")
        if unk_n:
            bits.append(f"{unk_n} composition unknown (not classified as a price move)")
        out["summary"] = (f"{len(rows)} tracked GPU change(s) after the cursor" + (f" for '{gpu}'" if gpu else "") +
                          f": " + ", ".join(bits) + "." + (" More available: call again with next_cursor." if paging["has_more"] else ""))
    elif since is not None:
        # Catch-up path for a windowed read: next_cursor sits just before the oldest event in the window, so paging
        # forward with it returns every event (none lost to limit). has_more = rows were cut by limit.
        evs = sorted((e for e in (history or {}).get("changes") or [] if isinstance(e.get("seq"), int)), key=lambda e: e["seq"])
        first = next((e["seq"] for e in evs if (e.get("date") or "") >= since), None)
        if evs:
            start = (first - 1) if first is not None else evs[-1]["seq"]
            prev = next((e for e in evs if e["seq"] == start), None)
            out["next_cursor"] = encode_cursor(start, prev["event_id"] if prev else None)
        else:
            out["next_cursor"] = None
        out["has_more"] = len(rows) > limit
    if covered:
        out["history_coverage"] = covered
        if since and covered.get("first_snapshot") and since < covered["first_snapshot"]:
            out["note"] += f" History starts {covered['first_snapshot']}; nothing earlier is tracked."
    checked = latest_checked_at([r.get("verified_at") for r in rows] +
                                [c.get("verified_at") for c in doc.get("changes") or [] if isinstance(c, dict)])
    basis = "newest verified_at among the changes"
    if not checked:  # history rows carry no check time: fall back to the newest daily snapshot date
        checked = doc.get("last_snapshot") or doc.get("date") or window.get("to")
        basis = "date of the newest daily snapshot (no per-row check time in this source)"
    out.update(freshness(checked))
    out["data_checked_at_basis"] = basis if checked else "unknown: source had no snapshot date"
    out.pop("refresh_hint")
    return out


class StackPricingLoader(FeedLoader):
    """The published /api/v1/stack-pricing.json (Agent Stack Optimizer data). LANTERN_STACK_PRICING_FILE overrides."""
    DEFAULT_URL, URL_ENV, FILE_ENV, LIST_KEY, LABEL = (STACK_PRICING_URL, "LANTERN_STACK_PRICING_URL",
                                                       "LANTERN_STACK_PRICING_FILE", "offers", "stack pricing")


TIER_CLASSES = ("on-demand", "community", "marketplace", "interruptible", "reserved", "dedicated-monthly")
TIER_NOTES = {"on-demand": "on-demand from the vendor's own cloud",
              "community": "community-hosted capacity (e.g. RunPod Community Cloud): third-party hosts, not the vendor's own data centres",
              "marketplace": "variable marketplace price set by individual hosts (median shown)",
              "interruptible": "spot/preemptible: the vendor may stop the job",
              "reserved": "reservation / commitment price ('starting from'); never counted as on-demand",
              "dedicated-monthly": "flat monthly dedicated server"}


def tier_class(r: dict) -> str:
    """One label per rate so 'cheapest' is never misread as cheapest on-demand (audit T9/M6)."""
    tier = (r.get("tier") or "").lower()
    plain = tier.replace("not interruptible", "").replace("non-interruptible", "")
    if r.get("interruptible") or "spot" in plain or "preempt" in plain or "interruptible" in plain:
        return "interruptible"
    if r.get("price_status") == "marketplace" or "marketplace" in tier:
        return "marketplace"
    if "community" in tier:
        return "community"
    # "On-demand (page: ... reserved pricing when you commit)" is an on-demand row that merely mentions reservations
    if ("reserv" in tier or "commit" in tier or "contract" in tier) and not tier.startswith("on-demand"):
        return "reserved"
    if r.get("unit") == "month" or r.get("billing_unit") == "monthly":
        return "dedicated-monthly"
    return "on-demand"


def tie_label(rows, best, price_key: str = "hourly_equiv_usd") -> str:
    """Shared tie rule (MCP summary and site pages): every advertiser with the same GPU, tier class, stock state and price."""
    names = sorted({r["advertiser"] for r in rows if r.get("gpu") == best.get("gpu") and tier_class(r) == tier_class(best)
                    and out_of_stock(r) == out_of_stock(best) and r[price_key] == best[price_key]})
    return best["advertiser"] if len(names) < 2 else " and ".join(names) + " (tie)"


def out_of_stock(r: dict) -> bool:
    """E5: True only when the feed explicitly marks the row out of stock (in_stock is False). Unknown is not out of stock."""
    a = r.get("availability")
    return isinstance(a, dict) and a.get("in_stock") is False


NVLINK_FORM_NOTE = ("Rows named 'NVLink' (e.g. Hyperstack 'H100 NVLink', 'A100 NVLink') count as form 'not stated': NVLink names the "
                    "GPU-to-GPU bridge, and the vendor page does not say SXM or PCIe. A row maps to SXM only where the vendor says SXM or HGX.")


COMPARE_NO_GPU_COUNT = ("No GPU count given; treated as 1 GPU. Rows sold only as multi-GPU allocations (min_gpus > 1) "
                        "are not ranked; they are listed in excluded_min_gpus with the reason.")


def cheapest_by_form_factor(rows: list[dict], gpus: int | None = 1) -> list[dict]:
    """gpu_poor #18, one rule for pages and MCP: per form_factor, the cheapest non-reserved row, preferring rows not marked
    out of stock (in stock or unknown); an out-of-stock row is named only when nothing else exists for that form. Each entry
    says whether the pick is interruptible (spot/community) so it is never read as on-demand. Empty when only one form."""
    from .gpu import form_of, FORM_FACTOR_ORDER
    from .ids import rate_id
    byf: dict = {}
    for r in rows:
        if tier_class(r) == "reserved" or r.get("hourly_equiv_usd") is None:
            continue
        from .gpu import min_gpus_unmet
        from .serverless import rate_reason
        if min_gpus_unmet(r, gpus):
            continue  # Bjorn 1109: an allocation larger than the request is never a form-factor pick
        if rate_reason(r):
            continue  # same serverless/per-second hold as compare (#102/#125), also for callers passing unfiltered rows
        k = (out_of_stock(r), r["hourly_equiv_usd"], r.get("advertiser") or "", r.get("gpu") or "")
        f = form_of(r)
        if f not in byf or k < byf[f][0]:
            byf[f] = (k, r)
    if len(byf) < 2:
        return []
    out = []
    for f in sorted(byf, key=lambda f: FORM_FACTOR_ORDER.index(f) if f in FORM_FACTOR_ORDER else 99):
        r = byf[f][1]
        tc = tier_class(r)
        out.append({"form_factor": f, "rate_id": rate_id(r), "advertiser": r["advertiser"], "gpu": r["gpu"],
                    "hourly_usd": r["hourly_equiv_usd"], "tier": r.get("tier"), "tier_class": tc,
                    "interruptible": tc == "interruptible", "in_stock": (r.get("availability") or {}).get("in_stock")
                    if isinstance(r.get("availability"), dict) else None, "source_url": r.get("source_url")})
    return out


def stock_phrase(a) -> str:
    """Stock state for a summary lead, with the availability check time (never the price date)."""
    a = a if isinstance(a, dict) else {}
    t = (a.get("checked_at") or "").replace("T", " ")[:16]
    if a.get("availability_stale"):
        x = (a.get("availability_expires_at") or "").replace("T", " ")[11:16]
        life = a.get("max_age_hours")
        valid = (f"{life * 60:g} min" if isinstance(life, (int, float)) and life < 1 else f"{life:g} h") if isinstance(life, (int, float)) else None
        return (f"availability unknown: last stock check {t[11:]}Z expired" + (f" at {x}Z" if x else "")
                + (f" (this stock claim was valid {valid})" if valid else ""))
    if a.get("in_stock") is True:
        return f"available when checked {t}Z" if t else "available when checked"
    if a.get("in_stock") is False:
        return f"out of stock when checked {t}Z" if t else "out of stock when checked"
    return "availability unknown (no stock signal)"


def oos_note(r: dict) -> str:
    a = r.get("availability") or {}
    return "out of stock when checked" + (f" at {a['checked_at']}" if a.get("checked_at") else "")


RATE_FIELDS = ("advertiser", "gpu", "vram_gb", "hourly_equiv_usd", "price_usd", "unit", "tier", "billing",
               "basis", "source_url", "verified_at", "offer_type", "affiliate", "redeem_url", "deal_id",
               "gpu_count", "server_price_usd", "server_hourly_usd", "evidence", "min_gpus", "price_status",
               "price_basis", "lowest_offer_usd", "offer_count", "interruptible", "availability", "region",
               # T112/T113 (additive pass-through of existing feed fields; T118 found them dropped here)
               "availability_rate_7d", "expected_cost_usd", "expected_cost_label", "availability_status",
               "availability_reason", "availability_reason_detail",
               # P45 (additive): literal marketplace query + composition flag from successive med/min/n
               "marketplace_query", "composition_flag", "composition_previous")


def _tokens(s: str) -> list[str]:
    from .gpu_names import tokens
    return tokens(s)


def gpu_models(data: dict) -> list[str]:
    return sorted({r.get("gpu") for r in data.get("rates") or [] if r.get("gpu")})


HISTORY_DAYS = 30


def _hist_key(r: dict) -> str:
    return f"{r.get('advertiser')}|{r.get('gpu')}|{r.get('tier')}|{r.get('vram_gb')}|{r.get('gpu_count') or 1}"


def gpu_history_view(history: dict, gpu: str, results: list[dict], days: int = HISTORY_DAYS) -> dict:
    """Per-result price history (change points) + recent changes for this model among tracked providers."""
    q = set(_tokens(gpu))
    series = {s.get("key"): s for s in history.get("series") or [] if isinstance(s, dict)}
    for r in results:
        s = series.get(_hist_key(r))
        r["price_history"] = [{k: p[k] for k in ("date", "hourly_usd", "status", "lowest_offer_usd", "offer_count") if k in p}
                              for p in (s or {}).get("points") or []]
    last = history.get("last_snapshot")
    start = None
    if last:
        try:
            start = (datetime.fromisoformat(last) - timedelta(days=days)).date().isoformat()
        except ValueError:
            start = None
    changes = [{k: c.get(k) for k in ("date", "vendor", "gpu", "tier", "vram_gb", "from_hourly_usd", "to_hourly_usd",
                                      "change_pct", "status", "source_url", "last_verified_before", "gap_days",
                                      "composition_flag", "lowest_offer_usd", "offer_count",
                                      "previous_lowest_offer_usd", "previous_offer_count") if k in c or k in (
                                          "date", "vendor", "gpu", "tier", "vram_gb", "from_hourly_usd",
                                          "to_hourly_usd", "change_pct", "status", "source_url",
                                          "last_verified_before", "gap_days", "composition_flag")}
               for c in history.get("changes") or [] if isinstance(c, dict) and q <= set(_tokens(c.get("gpu", "")))
               and (start is None or (c.get("date") or "") > start)]
    return {"recent_changes": changes, "window_days": days, "first_snapshot": history.get("first_snapshot"),
            "last_snapshot": last, "source": GPU_HISTORY_URL,
            "note": "Changes among tracked providers only (daily snapshots; points are change points). "
                    "composition_flag on a marketplace median is from successive median/min/n, not a host intersection; "
                    "composition, mixed and unknown are not price moves."}


def compare_gpu_prices(data: dict, gpu: str, limit: int = 10, history: dict | None = None,
                       on_demand_only: bool = False, include_reserved: bool = False,
                       max_data_age_hours: float | None = None, now: datetime | None = None, region: str | None = None,
                       usable_filter=None, gpus: int | None = None) -> dict:
    """Filter gpu-prices.json rates by model (all query tokens must be tokens of the model name, so
    'H100' matches 'H100 SXM' but 'L40' does not match 'L40S') and sort by hourly price ascending."""
    from .ids import rate_id
    vram_m = re.search(r"\b(\d{2,3})\s*gb\b", gpu or "", re.I)
    want_vram = int(vram_m.group(1)) if vram_m else None
    q = _tokens(re.sub(r"\b\d{2,3}\s*gb\b", " ", gpu or "", flags=re.I))
    if not q:
        raise DealError("invalid_argument", "gpu is required, e.g. 'H100', 'A100 SXM', 'A100 80GB', 'RTX 4090'")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise DealError("invalid_argument", f"limit must be an integer 1-{MAX_LIMIT}")
    if gpus is not None and (not isinstance(gpus, int) or isinstance(gpus, bool) or not 1 <= gpus <= 1024):
        raise DealError("invalid_argument", "gpus must be an integer 1-1024")
    from .gpu import min_gpus_unmet
    from .rate_dates import min_bill as _min_bill
    assumptions = [] if gpus is not None else [COMPARE_NO_GPU_COUNT]
    n_gpus = gpus or 1
    rows = [r for r in data.get("rates") or []
            if isinstance(r, dict) and isinstance(r.get("hourly_equiv_usd"), (int, float))
            and set(q) <= set(_tokens(r.get("gpu", "")))
            and (want_vram is None or r.get("vram_gb") == want_vram)]
    from .owner_hold import is_held
    held_owner = [{"vendor": r.get("advertiser"), "gpu": r.get("gpu"), "tier": r.get("tier"),
                   "source_url": r.get("source_url"), "checked_at": r.get("verified_at") or r.get("checked_at"),
                   "reason": "owner_hold"} for r in rows if is_held(r.get("advertiser"))]
    rows = [r for r in rows if not is_held(r.get("advertiser"))]
    if not rows:
        if held_owner:
            return {"gpu": gpu, "ok_current": False, "count": 0, "results": [], "total": 0,
                    "summary": (f"No current price for '{gpu}': {len(held_owner)} tracked rate(s) are temporarily held "
                                "(owner_hold) and are not ranked."),
                    "held_owner": held_owner, "data_source": GPU_PRICES_URL,
                    "feed_updated_at": data.get("feed_updated_at"), "scope": "cheapest among tracked providers"}
        raise DealError("not_found", f"No tracked price for GPU '{gpu}'. Tracked models: {', '.join(gpu_models(data))}")
    from . import data_age
    try:
        max_h = data_age.validate_max_age(max_data_age_hours)
    except ValueError as e:
        raise DealError("invalid_argument", str(e))
    # 0.3.30: availability older than AVAIL_MAX_AGE_H is re-checked at call time and shown unknown (never ranks or leads)
    from .gpu_availability import stale_guard
    _now_av = now.astimezone(timezone.utc) if isinstance(now, datetime) and now.tzinfo else None
    rows = [dict(r, availability=stale_guard(r["availability"], _now_av)) if isinstance(r.get("availability"), dict) else r
            for r in rows]
    excluded_too_old = 0
    stale_rows = []
    if max_h is not None:
        keep = [r for r in rows if not data_age.too_old(r, max_h, now)]
        excluded_too_old = len(rows) - len(keep)
        if not keep:
            raise DealError("not_found", f"No tracked price for GPU '{gpu}' verified within {max_h:g} hours "
                                         f"({excluded_too_old} older rates exist; raise or omit max_data_age_hours)")
        rows = keep
    else:
        # Gauge re28: by default a price older than 168 h never ranks or heads the summary; listed separately
        rows, stale_rows = data_age.split_current(rows, None, now)
        if not rows:
            sv = sorted((data_age.stale_view(r, now) for r in stale_rows), key=lambda x: (x["price"], x["vendor"] or ""))
            return {"gpu": gpu, "ok_current": False, "count": 0, "results": [], "total": 0,
                    "summary": (f"No current price for '{gpu}': all {len(sv)} tracked rates are older than "
                                f"{data_age.CURRENT_MAX_HOURS} h (stale), so no current cheapest is named. Stale rows are in "
                                "stale_prices; pass max_data_age_hours to rank them anyway, and confirm on the vendor page."),
                    "stale_prices": sv, "excluded_stale": len(sv), "max_data_age_hours": None,
                    "current_max_age_hours": data_age.CURRENT_MAX_HOURS,
                    "data_source": GPU_PRICES_URL, "feed_updated_at": data.get("feed_updated_at"),
                    "scope": "cheapest among tracked providers"}
    # T63 (Gauge/Bjorn 1108): serverless / per-second prices are held in EVERY pricing mode (never ranked as an hourly
    # rate); they stay visible in held_serverless with the reason.
    from . import serverless as _sl
    held_serverless = [{"vendor": r.get("advertiser"), "gpu": r.get("gpu"), "tier": r.get("tier"), "billing_unit": r.get("billing_unit"),
                        "price_per_second_usd": r.get("price_per_second_usd"), "source_url": r.get("source_url"),
                        "checked_at": r.get("verified_at") or r.get("checked_at"), "reason": _sl.rate_reason(r), "_row": r}
                       for r in rows if _sl.rate_reason(r)]
    if held_serverless:
        rows = [r for r in rows if not _sl.rate_reason(r)]
        if not rows:
            raise DealError("not_found", f"Only serverless/per-second prices are tracked for GPU '{gpu}' ({len(held_serverless)}); "
                                         "they are held, never ranked as a dedicated hourly rate")
    excluded = 0
    if on_demand_only:
        keep = [r for r in rows if tier_class(r) == "on-demand"]
        # held serverless rows that are not on-demand still count here (same count as before the T63 hold)
        excluded = len(rows) - len(keep) + sum(1 for h in held_serverless if tier_class(h["_row"]) != "on-demand")
        if not keep:
            raise DealError("not_found", f"No on-demand tracked price for GPU '{gpu}' ({excluded} spot/community/marketplace/monthly rates exist; retry without on_demand_only)")
        rows = keep
    excluded_reserved = 0
    if not include_reserved:
        keep = [r for r in rows if tier_class(r) != "reserved"]
        excluded_reserved = len(rows) - len(keep)
        if not keep:
            raise DealError("not_found", f"Only reservation/commitment prices are tracked for GPU '{gpu}' ({excluded_reserved}); retry with include_reserved=true")
        rows = keep
    # T47: shared eligibility contract (core.eligibility). region: rows whose unexpired regions exclude it are dropped;
    # rows with no region evidence stay, labelled unresolved, ranked after eligible rows (never "cheapest").
    from . import eligibility as EL
    try:
        cons = EL.normalize(gpu=gpu, region=region, max_price_age_hours=max_h,
                            tiers=["on-demand"] if on_demand_only else (None if include_reserved else [t for t in EL.TIER_CLASSES if t != "reserved"]))
    except EL.EligibilityError as e:
        raise DealError("invalid_argument", str(e))
    elig = {id(r): EL.evaluate(r, cons, now) for r in rows}
    excluded_region = 0
    if cons.get("region"):
        keep = [r for r in rows if not any(u["constraint"] == "region" for u in elig[id(r)]["unmet"])]
        excluded_region = len(rows) - len(keep)
        if not keep:
            raise DealError("not_found", f"No tracked '{gpu}' rate publishes region {cons['region']} ({excluded_region} rates publish other regions)")
        rows = keep
    # Bjorn 1109: a row ranks only when min_gpus <= the requested GPU count (1 when none given). Rows sold only as
    # larger allocations are NOT ranked; they are listed in excluded_min_gpus with the reason (never dropped silently).
    excluded_min = [{"vendor": r.get("advertiser"), "gpu": r.get("gpu"), "tier": r.get("tier"), "min_gpus": r.get("min_gpus"),
                     "gpu_count": r.get("gpu_count"), "hourly_usd": r.get("hourly_equiv_usd"), "rate_id": rate_id(r),
                     "source_url": r.get("source_url"), "checked_at": r.get("verified_at") or r.get("checked_at"),
                     "reason": f"sold only as {r.get('min_gpus')}-GPU allocations; {n_gpus} GPU(s) requested",
                     **dict(zip(("min_bill_usd_per_hour", "min_bill_basis"), _min_bill(r)))}
                    for r in rows if min_gpus_unmet(r, n_gpus)]
    excluded_min.sort(key=lambda x: (x["min_gpus"] or 1, x["hourly_usd"], x["vendor"] or ""))
    if excluded_min:
        rows = [r for r in rows if not min_gpus_unmet(r, n_gpus)]
        if not rows:
            raise DealError("not_found", f"No tracked '{gpu}' rate sells a {n_gpus}-GPU allocation: all {len(excluded_min)} "
                                         "matching rates need more GPUs (" + "; ".join(
                                             f"{x['vendor']} {x['gpu']} min {x['min_gpus']}" for x in excluded_min[:8])
                                         + (" ..." if len(excluded_min) > 8 else "") + "). Pass gpus >= "
                                         f"{min(x['min_gpus'] for x in excluded_min)} to rank them.", reason="min_gpus")
    # T61: optional usable-memory filter (callable(rows) -> core.gpu_identity.filter_usable result). It runs on every
    # remaining row BEFORE sort/limit, so count, total, the summary and cheapest_by_form_factor describe filtered rows.
    ufilter = None
    if usable_filter is not None:
        f = usable_filter(rows)
        ufilter = {"matched": len(f["matched"]), "below": len(f["below"]), "unknown": len(f["unknown"]), "note": f.get("note")}
        if f.get("identity_unavailable"):
            ufilter["identity_unavailable"] = True
        rows = f["matched"]
        if not rows:
            return {"gpu": gpu, "summary": (f"No tracked '{gpu}' rate has a sourced usable memory meeting the filter "
                                            f"({ufilter['unknown']} unknown, {ufilter['below']} below). Nominal memory is not used as usable memory."),
                    "on_demand_only": bool(on_demand_only), "excluded_non_on_demand": excluded,
                    "include_reserved": bool(include_reserved), "excluded_reserved": excluded_reserved,
                    "max_data_age_hours": max_h, "excluded_too_old": excluded_too_old, "excluded_stale": len(stale_rows),
                    "region": cons.get("region"), "excluded_other_region": excluded_region,
                    "scope": "cheapest among tracked providers", "total": 0, "count": 0, "results": [],
                    "usable_memory_filter": ufilter, "excluded_serverless": len(held_serverless),
                    "held_serverless": [{k: v for k, v in h.items() if k != "_row"} for h in held_serverless],
                    "data_source": GPU_PRICES_URL, "feed_updated_at": data.get("feed_updated_at")}
    unresolved = lambda r: any(u["constraint"] == "region" for u in elig[id(r)]["unknown"])
    # Reserved rows (only with include_reserved) sort after pay-as-you-go rows: never reported as "cheapest".
    # E5: rows the feed marks out of stock sort after in-stock/unknown rows (kept, flagged), so never "cheapest".
    oos_cheaper = min((r for r in rows if out_of_stock(r) and tier_class(r) != "reserved"),
                      key=lambda r: r["hourly_equiv_usd"], default=None)
    # Shared lead rule (core.data_age.lead_key): a degraded (> 48 h) row is shown and flagged but never ranked first
    # while a fresh row exists; if none is fresh, stale_fallback says the top row is not a current price.
    rows.sort(key=lambda r: (tier_class(r) == "reserved", data_age.lead_key(r, now, max_h=max_h), unresolved(r), out_of_stock(r), r["hourly_equiv_usd"], r.get("advertiser") or "", r.get("gpu") or ""))
    stale_fallback, deg_note = data_age.degraded_note([r for r in rows if tier_class(r) != "reserved"], now, max_h=max_h)
    od = next((r for r in rows if tier_class(r) == "on-demand"), None)
    # Different memory sizes are different products (an A100 40GB is not an A100 80GB): name the cheapest per size.
    by_vram = {}
    for r in rows:
        by_vram.setdefault(r.get("vram_gb"), r)
    vram_note = ""
    if len(by_vram) > 1:
        big = max(v for v in by_vram if v)
        b = next((r for r in rows if r.get("vram_gb") == big and tier_class(r) == "on-demand" and not out_of_stock(r)), by_vram.get(big))
        vram_note = (f" Memory sizes differ (cheapest {'on-demand ' if tier_class(b) == 'on-demand' else ''}{big}GB: {b['advertiser']} {b['gpu']} {big}GB at {usd(b['hourly_equiv_usd'])}/hr, {b['tier']})"
                     ", compare like with like: " + "; ".join(
            f"{v} GB from {usd(r['hourly_equiv_usd'])}/hr ({r['advertiser']})" for v, r in sorted(by_vram.items(), key=lambda x: (x[0] is None, x[0] or 0)))
            + f". Add the size (e.g. '{q[0].upper()} {max(v for v in by_vram if v)}GB') to filter.")
    results = []
    for i, r in enumerate(rows[:limit], 1):
        out = {k: r.get(k) for k in RATE_FIELDS}
        out["hourly_usd"] = out.pop("hourly_equiv_usd")
        out["checked_at"] = out.pop("verified_at")
        out["tier_class"] = tier_class(r)
        out["tier_note"] = TIER_NOTES[out["tier_class"]]
        from .gpu import canonical_model as _cm, form_factor_of as _ff  # T75: same fields as gpu-prices.json rows
        out["canonical_model"] = r.get("canonical_model") or _cm(r["gpu"])
        out["form_factor"] = r.get("form_factor") or _ff(r["gpu"])
        # Brain #247 (additive): quote currency, FX date, last verification; disclosed referral link only where the feed has one
        out["quote_currency"] = r.get("quote_currency") or "USD"
        out["fx_date"] = r.get("fx_date")
        out["last_verified"] = r.get("last_verified") or r.get("verified_at")
        # Brain #584 (additive): when the price took effect at the vendor (feed value; null when not datable), separate
        # from last_verified. eddie_compute (additive): least hourly bill for one allocation = min_gpus x hourly_usd.
        from .rate_dates import EFFECTIVE_KEYS, min_bill
        out.update({k: r.get(k) for k in EFFECTIVE_KEYS})
        out["min_bill_usd_per_hour"], out["min_bill_basis"] = min_bill(r)
        out.update({k: r[k] for k in ("referral_url", "referral_label") if r.get(k)})
        out["rank"] = i
        out["in_stock"] = (out.get("availability") or {}).get("in_stock") if isinstance(out.get("availability"), dict) else None
        if out_of_stock(r):
            out["availability_note"] = oos_note(r) + "; ranked after in-stock/unknown rows"
        out["eligibility"] = elig[id(r)]  # T47: applied / unmet / unknown constraints for this row
        out["rate_id"] = rate_id(r)  # T39: stable across sort order and label renames (core.ids)
        out.update(data_age.age_fields(r, now))
        from .report_issue import report_issue_url
        out["report_issue_url"] = report_issue_url(out)  # T40: give this to the user if the row looks wrong
        results.append(out)
    c = results[0]
    # I5: name every row tied with the cheapest (same price, tier class and stock state)
    c_who = tie_label([x for x in rows if unresolved(x) == unresolved(rows[0]) and data_age.lead_key(x, now, max_h=max_h) == data_age.lead_key(rows[0], now, max_h=max_h)], rows[0])  # re30: a tie never mixes region-confirmed and unresolved rows
    od_who = tie_label([x for x in rows if tier_class(x) == "on-demand" and data_age.lead_key(x, now, max_h=max_h) == data_age.lead_key(od, now, max_h=max_h)], od) if od is not None else None
    oos_msg = ""
    if oos_cheaper is not None and not out_of_stock(c) and oos_cheaper["hourly_equiv_usd"] < c["hourly_usd"]:
        oos_msg = (f" Cheaper but {oos_note(oos_cheaper)}: {oos_cheaper['advertiser']} {oos_cheaper['gpu']} at "
                   f"${oos_cheaper['hourly_equiv_usd']:g}/hr ({oos_cheaper.get('tier')}).")
    elif out_of_stock(c):
        oos_msg = f" Note: this row was {oos_note(c)}; no in-stock or unknown-availability row matched."
    extra = {"history": gpu_history_view(history, gpu, results)} if history is not None else {}
    from .gpu import split_by_form
    if split_by_form(gpu):  # gpu_poor #18 (additive): cheapest per form factor, same rule as the pages
        cbf = cheapest_by_form_factor(rows, n_gpus)
        if cbf:
            extra["cheapest_by_form_factor"] = cbf
            extra["cheapest_by_form_factor_note"] = ("Cheapest non-reserved per form; in-stock/unknown before out-of-stock. "
                                                     "NVLink rows = form 'not stated' (bridge, not SXM/PCIe).")
    region_note = ""
    if cons.get("region"):  # re30 c: say what the region filter found before naming any cheapest
        n_un = sum(1 for r in rows if unresolved(r))
        n_ok = len(rows) - n_un
        region_note = (f"Region {cons['region']}: {n_ok} rate(s) confirmed in {cons['region']}; {n_un} publish no region "
                       f"(unresolved, not eligible); {excluded_region} only other regions."
                       + (" Zero confirmed is not zero supply: most providers do not publish regions; check unresolved rows on the vendor page."
                          if n_ok == 0 and n_un else "") + " ")
    # Gauge #130 nit: a marketplace row may lack lowest_offer_usd (or carry a non-number); never format a missing value.
    lo = c.get("lowest_offer_usd")
    lo_ok = isinstance(lo, (int, float)) and not isinstance(lo, bool)
    mkt_note = ((f"; variable marketplace median, lowest offer ${lo:g}/hr" if lo_ok else "; variable marketplace median")
                if c.get("price_status") == "marketplace" else "")
    return {
        "gpu": gpu,
        "summary": region_note + (f"Cheapest{' regardless of region' if region_note and not elig[id(rows[0])]['eligible'] else ''}{' (not marked out of stock)' if oos_msg and not out_of_stock(c) else ''} among tracked providers: {c_who} {c['gpu']}"
                    + (f" {c['vram_gb']}GB" if c.get("vram_gb") and f"{c['vram_gb']}GB" not in (c.get("gpu") or "") else "")
                    + f" at ${c['hourly_usd']:g}/hr ({c['tier']}" + (", interruptible" if c.get("interruptible") else "")
                    + f", {stock_phrase(c.get('availability'))}; price checked {(c['checked_at'] or '')[:10]})"
                    + mkt_note
                    + (f"; sold only as {c['min_gpus']}-GPU instances" if (c.get("min_gpus") or 1) > 1 else "")
                    + f". Tier: {results[0]['tier_class']}."
                    + ("" if results[0]["tier_class"] == "on-demand" or od is None else
                       f" Cheapest on-demand: {od_who} {od['gpu']} at ${od['hourly_equiv_usd']:g}/hr ({od['tier']}).")
                    + oos_msg + deg_note
                    + (f" {len(stale_rows)} rate(s) with a price older than {data_age.CURRENT_MAX_HOURS} h are not ranked (see stale_prices)." if stale_rows else "")
                    + (f" {len(excluded_min)} rate(s) sold only as allocations larger than {n_gpus} GPU(s) are not ranked (see excluded_min_gpus)." if excluded_min else "")
                    + ". This is the cheapest among tracked providers only, not the whole market. "
                    "Vendors with stale published prices are held out." + vram_note).replace("). .", ").").replace(".. ", ". "),
        "gpus": n_gpus, "assumptions": assumptions, "min_gpus_unmet": len(excluded_min), "excluded_min_gpus": excluded_min,
        "on_demand_only": bool(on_demand_only), "excluded_non_on_demand": excluded,
        "excluded_serverless": len(held_serverless), "held_serverless": [{k: v for k, v in h.items() if k != "_row"} for h in held_serverless],
        "held_owner": held_owner,
        "include_reserved": bool(include_reserved), "excluded_reserved": excluded_reserved,
        "max_data_age_hours": max_h, "excluded_too_old": excluded_too_old,
        "current_max_age_hours": data_age.CURRENT_MAX_HOURS if max_h is None else max_h,
        "excluded_stale": len(stale_rows),
        "stale_prices": sorted((data_age.stale_view(r, now) for r in stale_rows), key=lambda x: (x["price"], x["vendor"] or "")),
        "stale_fallback": stale_fallback,
        "region": cons.get("region"), "excluded_other_region": excluded_region,
        "region_unresolved": sum(1 for r in rows if cons.get("region") and unresolved(r)),
        "constraints": {"applied": cons, "eligible_rate_ids": sorted(rate_id(r) for r in rows if elig[id(r)]["eligible"]),
                        "contract": "core.eligibility (T47): same constraints and result in compare, estimate, watch alerts and the calculator; "
                                    "unknown stock is not confirmed availability; a region without evidence is unresolved"},
        "data_age": {"degraded_after_hours": data_age.DEGRADED_HOURS, "stale_after_hours": data_age.STALE_HOURS,
                     "stale_count": sum(1 for x in results if x["stale"]), "degraded_count": sum(1 for x in results if x["degraded"])},
        "tier_classes": TIER_NOTES,
        "scope": "cheapest among tracked providers",
        "total": len(rows), "count": len(results), "results": results,
        "sorted_by": ("fresh rows first (degraded > 48 h never ranked first), then " if max_h is None else "")
                     + "hourly_usd ascending (monthly plans converted at hours_per_month)",
        "hours_per_month": data.get("hours_per_month"),
        "data_source": GPU_PRICES_URL, "feed_updated_at": data.get("feed_updated_at"),
        "methodology": data.get("methodology"),
        "note": "Each result's source_url is the vendor page the price was checked on (checked_at). "
                "Excludes storage, egress and taxes; confirm on the vendor page before spending.",
        **extra,
        **({"usable_memory_filter": ufilter} if ufilter is not None else {}),
    }


def public_view(deal: dict, fields: tuple[str, ...] = PUBLIC_FIELDS) -> dict:
    out = {k: deal.get(k) for k in fields if k in deal}
    if "redeem_url" in fields and (t := tracked_url(deal, "mcp")):
        out["tracked_url"] = t  # additive: counted /go/ redirect to the same redeem_url
    return out


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


# Retired duplicate deal ids -> the record that carries the vendor's data (audit E3/F5).
DEAL_ALIASES = {"deal-cloreai-001": "deal-clore-ai"}


def get_deal(deals: list[dict], deal_id: str) -> dict:
    if not deal_id or not isinstance(deal_id, str):
        raise DealError("invalid_argument", "id is required")
    deal_id = DEAL_ALIASES.get(deal_id, deal_id)
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
            "billing_period", "promo_code", "expires_at", "verified_at", "redeem_url", "pricing_note", "signup",
            "price_null_reason", "source_url")
    return {"order": "customer_value", "deals": [public_view(d, cols) for d in rows],
            "note": "price_usd null = unknown, not free. Confirm terms on the vendor page before spending."}
