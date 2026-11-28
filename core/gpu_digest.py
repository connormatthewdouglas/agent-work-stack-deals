"""F5 (Brain #1032): daily/weekly digest of the biggest tracked GPU price moves.

Reuses existing daily changes (core.gpu_changes.build_changes; ranked rows only) and
existing history windows (core.gpu_history.price_trend). Held/stale days stay out of
the math. Missing snapshot days are not invented. Official generate is deterministic
(snapshot dates only; no wall clock). Live stock is not written into the published
feed; the MCP tool may attach stale_guard availability at request time to surface
staleness without changing the move math.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import gpu_changes, gpu_history as H
from .data_license import DATA_LICENSE, REPORT_ISSUE, REPORT_ISSUE_NOTE
from .ids import rate_id

SCHEMA = "lantern-works-gpu-price-digest/1"
DEFAULT_LIMIT = 10
MAX_LIMIT = 25
PERIODS = ("daily", "weekly")
HISTORY_PATH = Path(__file__).resolve().parents[1] / "api" / "v1" / "gpu-prices" / "history.json"


class DigestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"series": [], "first_snapshot": None, "last_snapshot": None}
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def _is_price_move(pct, flag) -> bool:
    """A real price move: |pct| meets the F2 2% deadband; composition-only flags are not moves."""
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        return False
    if abs(pct) < H.FLAT_BAND:
        return False
    return flag in (None, "price")


def _row_from_change(c: dict) -> dict:
    row = {
        "vendor": c.get("vendor"),
        "gpu": c.get("gpu"),
        "tier": c.get("tier"),
        "gpu_count": c.get("gpu_count") or 1,
        "billing_unit": c.get("billing_unit") or "hourly",
    }
    if c.get("vram_gb") is not None:
        row["vram_gb"] = c["vram_gb"]
    elif c.get("key"):
        parts = str(c["key"]).split("|")
        if len(parts) >= 5 and parts[3].isdigit():
            row["vram_gb"] = int(parts[3])
            if not c.get("gpu_count") and parts[4].isdigit():
                row["gpu_count"] = int(parts[4])
    return row


def _direction_of(pct: float) -> str:
    if pct >= H.FLAT_BAND:
        return "up"
    if pct <= -H.FLAT_BAND:
        return "down"
    return "flat"


def _sort_key(m: dict):
    return (-abs(m["pct"]), m.get("gpu") or "", m.get("vendor") or "", m.get("rate_id") or m.get("key") or "")


def _matches(m: dict, gpu: str | None, vendor: str | None, direction: str | None) -> bool:
    if direction and m.get("direction") != direction:
        return False
    if vendor and (m.get("vendor") or "").lower() != vendor.strip().lower():
        return False
    if gpu and not _tokens(gpu) <= _tokens(m.get("gpu") or ""):
        return False
    return True


def _validate(period: str, limit: int, direction: str | None) -> tuple[str, int, str | None]:
    p = (period or "").strip().lower()
    if p not in PERIODS:
        raise DigestError("invalid_argument", "period must be 'daily' or 'weekly'")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise DigestError("invalid_argument", f"limit must be an integer 1-{MAX_LIMIT}")
    d = (direction or "").strip().lower() or None
    if d in ("any", "all"):
        d = None
    if d is not None and d not in ("up", "down"):
        raise DigestError("invalid_argument", "direction must be 'up', 'down', or omitted")
    return p, limit, d


def daily_moves(changes: dict | None, *, limit: int = DEFAULT_LIMIT,
                gpu: str | None = None, vendor: str | None = None,
                direction: str | None = None) -> dict:
    """Biggest |pct| ranked-to-ranked price moves between the two latest snapshots."""
    doc = changes or {}
    out = []
    for c in doc.get("changes") or []:
        if c.get("change") not in ("up", "down"):
            continue
        if not _is_price_move(c.get("pct"), c.get("composition_flag")):
            continue
        row = _row_from_change(c)
        try:
            rid = rate_id(row)
        except Exception:
            rid = None
        pct = float(c["pct"])
        item = {
            "rate_id": rid,
            "key": c.get("key"),
            "vendor": c.get("vendor"),
            "gpu": c.get("gpu"),
            "tier": c.get("tier"),
            "vram_gb": row.get("vram_gb"),
            "gpu_count": row.get("gpu_count") or 1,
            "change": c["change"],
            "direction": c["change"],
            "start_usd": c.get("old_hourly_usd"),
            "end_usd": c.get("new_hourly_usd"),
            "pct": pct,
            "source_url": c.get("source_url"),
            "verified_at": c.get("verified_at"),
            "last_verified_before": c.get("last_verified_before"),
            "gap_days": c.get("gap_days"),
        }
        if not _matches(item, gpu, vendor, direction):
            continue
        out.append(item)
    out.sort(key=_sort_key)
    considered = len(out)
    moves = []
    for i, m in enumerate(out[:limit], 1):
        moves.append({"rank": i, **m})
    return {
        "period": "daily",
        "date": doc.get("date"),
        "previous_date": doc.get("previous_date"),
        "window_start": doc.get("previous_date"),
        "window_end": doc.get("date"),
        "count": len(moves),
        "considered": considered,
        "moves": moves,
    }


def weekly_moves(history: dict | None, *, limit: int = DEFAULT_LIMIT,
                 gpu: str | None = None, vendor: str | None = None,
                 direction: str | None = None) -> dict:
    """Biggest 7d |pct| moves from price_trend (ranked/verified days only; held/stale days excluded)."""
    hist = history or {}
    last = hist.get("last_snapshot")
    first = hist.get("first_snapshot")
    window_end, window_start = last, None
    if last:
        from datetime import date, timedelta
        window_start = (date.fromisoformat(last) - timedelta(days=6)).isoformat()
    out = []
    for series in hist.get("series") or []:
        if not isinstance(series, dict):
            continue
        tr = H.price_trend(series, history=hist, live=None, held=False, windows=[7])
        wins = {w.get("days"): w for w in (tr.get("windows") or [])}
        w = wins.get(7) or {}
        if w.get("reason") or "pct" not in w:
            continue
        if not _is_price_move(w.get("pct"), None):
            continue
        pct = float(w["pct"])
        item = {
            "rate_id": series.get("rate_id") or rate_id(series),
            "key": series.get("key"),
            "vendor": series.get("vendor"),
            "gpu": series.get("gpu"),
            "tier": series.get("tier"),
            "vram_gb": series.get("vram_gb"),
            "gpu_count": series.get("gpu_count") or 1,
            "change": _direction_of(pct),
            "direction": _direction_of(pct),
            "start_usd": w.get("start_usd"),
            "end_usd": w.get("end_usd"),
            "pct": pct,
            "ranked_days": w.get("ranked_days"),
            "start_at": w.get("start_at"),
            "end_at": w.get("end_at"),
            "source_url": series.get("source_url"),
            "verified_at": w.get("end_at"),
        }
        if not _matches(item, gpu, vendor, direction):
            continue
        out.append(item)
    out.sort(key=_sort_key)
    considered = len(out)
    moves = [{"rank": i, **m} for i, m in enumerate(out[:limit], 1)]
    return {
        "period": "weekly",
        "window_start": window_start,
        "window_end": window_end,
        "first_snapshot": first,
        "last_snapshot": last,
        "count": len(moves),
        "considered": considered,
        "moves": moves,
    }


def attach_live(moves: list[dict], rates: list | None, now=None) -> list[dict]:
    """P64 request-time availability on a copy of each move. Does not change pct/windows."""
    if not rates:
        return moves
    from .gpu_availability import request_availability
    by = {}
    for r in rates:
        if not isinstance(r, dict):
            continue
        try:
            by[rate_id(r)] = r
        except Exception:
            continue
    out = []
    for m in moves:
        item = dict(m)
        r = by.get(item.get("rate_id"))
        if r is not None and isinstance(r.get("availability"), dict):
            g = request_availability(r["availability"], now)
            item["availability"] = g
            item["in_stock"] = g.get("in_stock")
            if g.get("availability_stale"):
                item["availability_stale"] = True
            if g.get("last_known_in_stock") is not None:
                item["last_known_in_stock"] = g.get("last_known_in_stock")
                item["last_known_at"] = g.get("last_known_at")
        out.append(item)
    return out


def price_moves(*, history: dict | None = None, changes: dict | None = None,
                snapshots: list | None = None, period: str = "daily",
                limit: int = DEFAULT_LIMIT, gpu: str | None = None,
                vendor: str | None = None, direction: str | None = None,
                live_rates: list | None = None, now=None) -> dict:
    """One period of the digest, for the MCP tool."""
    period, limit, direction = _validate(period, limit, direction)
    if period == "daily":
        ch = changes if changes is not None else gpu_changes.build_changes(snapshots)
        block = daily_moves(ch, limit=limit, gpu=gpu, vendor=vendor, direction=direction)
    else:
        hist = history if history is not None else _load_history()
        block = weekly_moves(hist, limit=limit, gpu=gpu, vendor=vendor, direction=direction)
    block = dict(block)
    block["moves"] = attach_live(block["moves"], live_rates, now)
    as_of = block.get("window_end") or block.get("date") or block.get("last_snapshot")
    return {
        "ok": True,
        "period": period,
        "as_of": f"{as_of}T12:00:00Z" if as_of and "T" not in str(as_of) else as_of,
        "window_start": block.get("window_start"),
        "window_end": block.get("window_end") or block.get("date"),
        "count": block["count"],
        "considered": block.get("considered"),
        "results": block["moves"],
        "label": "biggest tracked GPU price moves; among tracked providers only",
    }


def build_digest(*, history: dict | None = None, changes: dict | None = None,
                 snapshots: list | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    """Published daily+weekly digest. Snapshot-dated only; no live stock, no wall clock."""
    hist = history if history is not None else _load_history()
    ch = changes if changes is not None else gpu_changes.build_changes(snapshots)
    daily = daily_moves(ch, limit=limit)
    weekly = weekly_moves(hist, limit=limit)
    return {
        "schema": SCHEMA,
        "license": DATA_LICENSE,
        "report_issue": REPORT_ISSUE,
        "methodology": [REPORT_ISSUE_NOTE,
                        "Biggest |pct| price moves among tracked providers. Daily moves are ranked-to-ranked "
                        "changes between the two latest snapshots; weekly moves use the 7-day history window. "
                        "Held/stale days are excluded. Missing snapshot days are not invented. Composition-only "
                        "marketplace median changes are not price moves. The 2% deadband matches get_price_trend."],
        "description": "Digest of the biggest tracked GPU rental price moves (daily and 7-day), per GPU-hour in USD. "
                       "Each move links the vendor's own pricing page. 'Biggest' and 'cheapest' are among tracked providers only.",
        "daily": daily,
        "weekly": weekly,
    }


def move_title(m: dict, *, period: str) -> str:
    from .money import usd
    pair = f"{usd(m.get('start_usd'))}/GPU-hr → {usd(m.get('end_usd'))}/GPU-hr"
    verb = "dropped" if m.get("direction") == "down" else "rose"
    pct = abs(m["pct"]) if m.get("pct") is not None else None
    pct_s = f" {pct}%" if pct is not None else ""
    prefix = "Weekly: " if period == "weekly" else "Daily: "
    return f"{prefix}{m.get('gpu')} at {m.get('vendor')} {verb}{pct_s}: {pair}"


def rss(doc: dict, base: str) -> str:
    from datetime import datetime, timezone
    from email.utils import format_datetime
    from xml.sax.saxutils import escape as x

    def _pub(day: str | None):
        if day:
            return format_datetime(datetime.fromisoformat(day + "T12:00:00+00:00"))
        return format_datetime(datetime(2026, 1, 1, tzinfo=timezone.utc))

    daily = doc.get("daily") or {}
    weekly = doc.get("weekly") or {}
    days = [d for d in (weekly.get("window_end"), daily.get("date")) if d]
    last = max(days) if days else None
    items = []
    for period, block in (("weekly", weekly), ("daily", daily)):
        day = block.get("window_end") or block.get("date")
        pub = _pub(day)
        start = block.get("window_start") or block.get("previous_date")
        for m in block.get("moves") or []:
            ident = m.get("rate_id") or m.get("key") or str(m.get("rank"))
            guid = f"{base}/api/v1/gpu-price-digest.json#{period}-{day}-{ident}"
            title = move_title(m, period=period)
            desc = title + (f" (window {start} → {day}). Source: vendor pricing page." if start and day else
                            ". Source: vendor pricing page.")
            items.append(
                f"    <item><title>{x(title)}</title><link>{x(m.get('source_url') or base + '/gpu/')}</link>"
                f"<guid isPermaLink=\"false\">{x(guid)}</guid><pubDate>{pub}</pubDate>"
                f"<description>{x(desc)}</description></item>"
            )
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<rss version=\"2.0\"><channel>\n"
            f"    <title>Lantern Works: GPU price-moves digest</title><link>{base}/gpu/</link>\n"
            f"    <description>{x(doc.get('description') or '')}</description>"
            f"<lastBuildDate>{_pub(last)}</lastBuildDate>\n"
            + "\n".join(items) + ("\n" if items else "") + "</channel></rss>\n")
