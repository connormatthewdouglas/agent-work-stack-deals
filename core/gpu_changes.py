"""What moved since yesterday: diff of the two latest daily GPU price snapshots (data/gpu_pricing/snapshots/).

Only rows with status 'ranked' count as a published price. Output is deterministic (no wall-clock reads), so
regenerating the site never changes it unless a snapshot changes.
"""
from __future__ import annotations

from core import gpu_history


def _ranked(snap: dict) -> dict[str, dict]:
    return {r["key"]: r for r in snap.get("rows", []) if r.get("status") == "ranked" and r.get("hourly_usd") is not None}


def build_changes(snapshots: list[dict] | None = None) -> dict:
    snaps = sorted(snapshots if snapshots is not None else gpu_history.load_snapshots(), key=lambda s: s["date"])
    doc = {"schema": "lantern-works-gpu-price-changes/1",
           "description": "GPU rental rates that moved between the two latest daily snapshots (per GPU-hour, USD). "
                          "Each change links the vendor's own pricing page. 'Cheapest' always means among tracked providers.",
           "date": None, "previous_date": None, "changes": [], "counts": {"down": 0, "up": 0, "new": 0, "removed": 0}}
    if len(snaps) < 2:
        return doc
    prev, cur = snaps[-2], snaps[-1]
    doc["date"], doc["previous_date"] = cur["date"], prev["date"]
    a, b = _ranked(prev), _ranked(cur)
    out = []
    for k in sorted(set(a) | set(b)):
        o, n = a.get(k), b.get(k)
        r = n or o
        base = {"key": k, "vendor": r["vendor"], "gpu": r["gpu"], "tier": r.get("tier"), "gpu_count": r.get("gpu_count", 1),
                "source_url": r.get("source_url")}
        if o and n:
            old, new = round(o["hourly_usd"], 4), round(n["hourly_usd"], 4)
            if old == new:
                continue
            kind = "down" if new < old else "up"
            out.append({**base, "change": kind, "old_hourly_usd": old, "new_hourly_usd": new,
                        "pct": round((new - old) / old * 100, 1) if old else None, "verified_at": n.get("verified_at")})
        elif n:
            out.append({**base, "change": "new", "old_hourly_usd": None, "new_hourly_usd": round(n["hourly_usd"], 4),
                        "pct": None, "verified_at": n.get("verified_at")})
        else:
            out.append({**base, "change": "removed", "old_hourly_usd": round(o["hourly_usd"], 4), "new_hourly_usd": None,
                        "pct": None, "verified_at": None})
    order = {"down": 0, "up": 1, "new": 2, "removed": 3}
    out.sort(key=lambda c: (order[c["change"]], c["pct"] if c["pct"] is not None else 0, c["gpu"], c["vendor"], c["key"]))
    doc["changes"] = out
    for c in out:
        doc["counts"][c["change"]] += 1
    return doc


def _fmt(v):
    return "—" if v is None else f"${v:.2f}/GPU-hr"


def change_title(c: dict) -> str:
    if c["change"] in ("down", "up"):
        return (f"{c['gpu']} at {c['vendor']} {'dropped' if c['change'] == 'down' else 'rose'} {abs(c['pct'])}%: "
                f"{_fmt(c['old_hourly_usd'])} → {_fmt(c['new_hourly_usd'])}")
    if c["change"] == "new":
        return f"Newly tracked: {c['gpu']} at {c['vendor']} {_fmt(c['new_hourly_usd'])}"
    return f"No longer ranked: {c['gpu']} at {c['vendor']} (was {_fmt(c['old_hourly_usd'])})"


def rss(doc: dict, base: str) -> str:
    from email.utils import format_datetime
    from datetime import datetime, timezone
    from xml.sax.saxutils import escape as x
    day = doc.get("date")
    pub = format_datetime(datetime.fromisoformat(day + "T12:00:00+00:00")) if day else format_datetime(datetime(2026, 1, 1, tzinfo=timezone.utc))
    items = []
    for c in doc["changes"]:
        guid = f"{base}/api/v1/gpu-price-changes.json#{day}-{c['key']}"
        items.append(f"    <item><title>{x(change_title(c))}</title><link>{x(c['source_url'] or base + '/gpu/')}</link>"
                     f"<guid isPermaLink=\"false\">{x(guid)}</guid><pubDate>{pub}</pubDate>"
                     f"<description>{x(change_title(c) + ' (snapshot ' + str(doc['previous_date']) + ' → ' + str(day) + '). Source: vendor pricing page.')}</description></item>")
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<rss version=\"2.0\"><channel>\n"
            f"    <title>Lantern Works: GPU price changes</title><link>{base}/gpu/</link>\n"
            f"    <description>{x(doc['description'])}</description><lastBuildDate>{pub}</lastBuildDate>\n"
            + "\n".join(items) + ("\n" if items else "") + "</channel></rss>\n")
