"""GPU price history: dated snapshots (data/gpu_pricing/snapshots/YYYY-MM-DD.json) and the per-series history
published at /api/v1/gpu-prices/history.json.

A snapshot holds one row per pricing record (vendor, GPU, tier, VRAM, GPU count) with the price as published that
day, its status (ranked or held, never both) and the evidence date. History points are change points: a new
point is added only when the price or status differs from the previous snapshot. "Cheapest" and every change
are among tracked providers only, not the whole market.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

SNAPSHOT_SCHEMA = "lantern-works-gpu-snapshot/1"
HISTORY_SCHEMA = "lantern-works-gpu-price-history/1"
SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "gpu_pricing" / "snapshots"


# Tier labels renamed on 2026-10-29 (audit): old snapshots map onto the new label so price series continue.
TIER_ALIASES = {"Secure Cloud": "On-demand (Secure Cloud)", "Community Cloud": "On-demand (Community Cloud)",
                "on-demand": "On-demand", "Serverless (per second)": "Serverless, preemptible (per second)",
                "dedicated server": "Dedicated server (monthly)",
                "Lowest (Batch) priority": "Lowest (Batch) priority, interruptible"}


def series_key(vendor: str, gpu: str, tier: str, vram_gb, gpu_count=1) -> str:
    tier = TIER_ALIASES.get(tier, tier)
    return f"{vendor}|{gpu}|{tier}|{vram_gb}|{gpu_count or 1}"


def snapshot_rows(docs: list[dict]) -> list[dict]:
    """One row per record, from the per-vendor files (raw, before ranking)."""
    rows = []
    for doc in docs:
        for r in doc.get("records") or []:
            held = doc.get("stale") or r.get("stale")
            rows.append({
                "key": series_key(r["vendor"], r["gpu"], r["tier"], r.get("vram_gb"), r.get("gpu_count", 1)),
                "vendor": r["vendor"], "gpu": r["gpu"], "tier": r["tier"], "vram_gb": r.get("vram_gb"),
                "gpu_count": r.get("gpu_count", 1), "billing_unit": r["billing_unit"],
                "price_usd": r["price_usd"], "hourly_usd": r["hourly_usd"],
                "status": "held" if held else "ranked",
                "verified_at": r.get("verified_at") or (r.get("evidence") or {}).get("checked_at") or r["checked_at"],
                "source_url": r["source_url"],
            })
    return sorted(rows, key=lambda x: x["key"])


def snapshot_doc(docs: list[dict], day: str) -> dict:
    return {"schema": SNAPSHOT_SCHEMA, "date": day,
            "note": "Daily snapshot of tracked GPU rental prices (per GPU). status 'held' rows are never ranked.",
            "rows": snapshot_rows(docs)}


def write_snapshot(docs: list[dict], day: str, directory: Path | None = None) -> Path:
    d = Path(directory or SNAPSHOT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{day}.json"
    p.write_text(json.dumps(snapshot_doc(docs, day), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def load_snapshots(directory: Path | None = None) -> list[dict]:
    d = Path(directory or SNAPSHOT_DIR)
    snaps = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("????-??-??.json"))]
    for snap in snaps:  # snapshot files are never rewritten; renamed tier labels are mapped on read
        for row in snap.get("rows", []):
            m = re.search(r"\((\d+)x GPU\)", row.get("tier") or "")
            fix_n = m and int(m.group(1)) > 1 and (row.get("gpu_count") or 1) == 1  # Lambda 8x rows got gpu_count 8 on 2026-10-29
            if fix_n:
                row["gpu_count"] = int(m.group(1))
            if row.get("tier") in TIER_ALIASES or fix_n:
                row["tier"] = TIER_ALIASES.get(row["tier"], row["tier"])
                row["key"] = series_key(row["vendor"], row["gpu"], row["tier"], row.get("vram_gb"), row.get("gpu_count", 1))
    return snaps


def build_history(snapshots: list[dict]) -> dict:
    """Series with change points + a flat, newest-first list of price changes between consecutive snapshots."""
    series: dict[str, dict] = {}
    changes: list[dict] = []
    for snap in sorted(snapshots, key=lambda s: s["date"]):
        day = snap["date"]
        seen = set()
        for row in snap["rows"]:
            k = row["key"]
            seen.add(k)
            s = series.get(k)
            if s is None:
                s = series[k] = {"key": k, **{f: row[f] for f in ("vendor", "gpu", "tier", "vram_gb", "gpu_count", "billing_unit")},
                                 "first_seen": day, "points": []}
            last = s["points"][-1] if s["points"] else None
            if last and last.get("status") != "removed" and last["hourly_usd"] != row["hourly_usd"]:
                old, new = last["hourly_usd"], row["hourly_usd"]
                changes.append({"date": day, "key": k, "vendor": row["vendor"], "gpu": row["gpu"], "tier": row["tier"],
                                "vram_gb": row["vram_gb"], "from_hourly_usd": old, "to_hourly_usd": new,
                                "change_pct": round((new - old) / old * 100, 1) if old else None,
                                "status": row["status"], "source_url": row["source_url"]})
            if (not last or last["hourly_usd"] != row["hourly_usd"] or last["price_usd"] != row["price_usd"]
                    or last["status"] != row["status"]):
                s["points"].append({"date": day, "price_usd": row["price_usd"], "hourly_usd": row["hourly_usd"],
                                    "status": row["status"], "verified_at": row["verified_at"]})
            s["last_seen"] = day
        for k, s in series.items():
            if k not in seen and s["points"] and s["points"][-1]["status"] != "removed":
                p = s["points"][-1]
                s["points"].append({"date": day, "price_usd": p["price_usd"], "hourly_usd": p["hourly_usd"],
                                    "status": "removed", "verified_at": p["verified_at"]})
    changes.sort(key=lambda c: (c["date"], c["key"]), reverse=True)
    dates = sorted(s["date"] for s in snapshots)
    return {"schema": HISTORY_SCHEMA,
            "scope": "tracked providers only (not the whole market); prices per GPU",
            "first_snapshot": dates[0] if dates else None, "last_snapshot": dates[-1] if dates else None,
            "snapshot_count": len(dates),
            "note": ("points are change points: each point is the first snapshot date at that price/status; "
                     "status 'held' = published but not ranked (stale or too thin a marketplace); 'removed' = no longer tracked."),
            "series": sorted(series.values(), key=lambda s: s["key"]), "changes": changes}


def recent_changes(history: dict, days: int = 30, today: str | None = None, gpu: str | None = None) -> list[dict]:
    end = date.fromisoformat(today or history.get("last_snapshot") or date.today().isoformat())
    start = (end - timedelta(days=days)).isoformat()
    out = [c for c in history.get("changes") or [] if c["date"] > start]
    if gpu:
        q = gpu.lower()
        out = [c for c in out if q in c["gpu"].lower()]
    return out


_PRICE_RE = re.compile(r"\$\s?([\d,]*\.?\d+)")


def _key_of(r: dict) -> str:
    return series_key(r["vendor"], r["gpu"], r["tier"], r.get("vram_gb"), r.get("gpu_count", 1))


def change_problems(base: dict[str, dict], docs: list[dict], label: str) -> list[str]:
    """Every rate whose price differs from `base` (key -> {price_usd, evidence_checked_at}) must carry fresh evidence:
    https source_url, an evidence quote containing the new price, and evidence.checked_at newer than the base's."""
    from datetime import datetime
    out = []
    for doc in docs:
        for r in doc.get("records") or []:
            b = base.get(_key_of(r))
            if not b or abs(float(b["price_usd"]) - float(r["price_usd"])) < 1e-9:
                continue
            tag = f"{r['vendor']} {r['gpu']} ({r['tier']}): {b['price_usd']} -> {r['price_usd']} vs {label}"
            ev = r.get("evidence") or {}
            if not str(r.get("source_url", "")).startswith("https://") or ev.get("source_url") != r.get("source_url"):
                out.append(f"{tag}: needs https source_url matching evidence.source_url")
            nums = [float(m.group(1).replace(",", "")) for m in _PRICE_RE.finditer(ev.get("quote") or "")
                    if m.group(1).replace(",", "").replace(".", "").isdigit()]
            if not any(abs(n - float(r["price_usd"])) < 1e-9 for n in nums):
                out.append(f"{tag}: evidence.quote does not contain the new price")
            try:
                fresh = datetime.fromisoformat(ev["checked_at"]) > datetime.fromisoformat(b["checked_at"])
            except (KeyError, TypeError, ValueError):
                fresh = False
            if not fresh:
                out.append(f"{tag}: evidence.checked_at must be newer than {b.get('checked_at')}")
    return out


def base_from_docs(docs: list[dict]) -> dict[str, dict]:
    return {_key_of(r): {"price_usd": r["price_usd"], "checked_at": (r.get("evidence") or {}).get("checked_at") or r["checked_at"]}
            for d in docs for r in d.get("records") or []}


def base_from_snapshot(snap: dict) -> dict[str, dict]:
    return {row["key"]: {"price_usd": row["price_usd"], "checked_at": row["verified_at"]} for row in snap.get("rows") or []}
