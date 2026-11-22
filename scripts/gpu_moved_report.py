#!/usr/bin/env python3
"""Build the weekly "GPU prices that moved" report artifacts from a current + history feed.

Used to write data/reports/gpu-prices-that-moved-YYYY-MM-DD/ and the markdown page.
Numbers must come from the feeds passed in, not from a previous draft.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLUG_PREFIX = "gpu-prices-that-moved"


def held_vendors(current: dict) -> set[str]:
    return {x["vendor"] for x in (current.get("held_stale") or [])}


def _point_on_or_before(series: dict, day: str):
    found = None
    for pt in series.get("points") or []:
        if pt.get("date") and pt["date"] <= day:
            found = pt
    return found


def moved_rows(current: dict, history: dict, start: str, end: str) -> list[dict]:
    held = held_vendors(current)
    cur = {}
    for r in current.get("rates") or []:
        cur[(r["advertiser"], r["gpu"], r["tier"], r["vram_gb"], r["gpu_count"])] = r
    rows = []
    for s in history.get("series") or []:
        if s.get("vendor") in held or s.get("billing_unit") != "hourly":
            continue
        r = cur.get((s["vendor"], s["gpu"], s["tier"], s["vram_gb"], s["gpu_count"]))
        if not r or r.get("tier_class") not in ("on-demand", "interruptible"):
            continue
        a, b = _point_on_or_before(s, start), _point_on_or_before(s, end)
        if not a or not b or a.get("status") != "ranked" or b.get("status") != "ranked":
            continue
        if not a.get("hourly_usd") or a["hourly_usd"] == b["hourly_usd"]:
            continue
        kind = "spot/interruptible" if r["tier_class"] == "interruptible" else "on-demand"
        rows.append({
            "vendor": s["vendor"],
            "gpu": s["gpu"],
            "vram_gb": s["vram_gb"],
            "gpu_count": s["gpu_count"],
            "tier": s["tier"],
            "kind": kind,
            "old": a["hourly_usd"],
            "new": b["hourly_usd"],
            "pct": round((b["hourly_usd"] - a["hourly_usd"]) / a["hourly_usd"] * 100, 1),
            "verified": (b.get("verified_at") or "")[:10] or None,
            "source_url": r.get("source_url"),
            "referral": r.get("redeem_url") if r.get("affiliate") else None,
        })
    rows.sort(key=lambda x: (-abs(x["pct"]), x["vendor"], x["gpu"], x["vram_gb"] or 0, x["kind"]))
    return rows


def figures(current: dict, history: dict, start: str, end: str) -> dict:
    rows = moved_rows(current, history, start, end)
    return {
        "feed_updated_at": current.get("feed_updated_at"),
        "start": start,
        "end": end,
        "n_moved": len(rows),
        "held_vendors": sorted(held_vendors(current)),
        "top5": rows[:5],
        "rows": rows,
    }


def gpu_label(r: dict) -> str:
    vram = r.get("vram_gb")
    name = r["gpu"] if not vram else f"{r['gpu']} {vram}GB"
    if (r.get("gpu_count") or 1) != 1:
        name += f" ({r['gpu_count']}x)"
    return name


def _usd(x) -> str:
    return f"${x:.4f}"


def _pct(x) -> str:
    sign = "+" if x > 0 else ""
    return f"{sign}{x:.1f}%"


def chart_svg(fig: dict) -> str:
    top = fig["top5"]
    width, left, right, top_m, row_h, gap = 900, 250, 44, 44, 36, 10
    height = top_m + 16 + len(top) * (row_h + gap) + 48
    xmax = max((abs(r["pct"]) for r in top), default=1) * 1.35 or 1
    bar_max = width - left - right
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Five biggest tracked price moves, week to {fig["end"]}.">\n',
        f'  <title>Five biggest tracked price moves, week to {html.escape(fig["end"])}</title>\n',
        f'  <text x="12" y="22" font-size="15" font-family="system-ui, sans-serif">Five biggest tracked price moves, week to {html.escape(fig["end"])}</text>\n',
    ]
    for i, r in enumerate(top):
        y = top_m + i * (row_h + gap)
        bw = max(2, abs(r["pct"]) / xmax * bar_max)
        kind = "spot" if r["kind"].startswith("spot") else "on-demand"
        label = f'{r["vendor"].split(" (")[0]} {r["gpu"]} ({kind})'
        parts.append(f'  <text x="{left - 10}" y="{y + 18}" text-anchor="end" font-size="12" font-family="system-ui, sans-serif">{html.escape(label)}</text>\n')
        parts.append(f'  <rect x="{left}" y="{y}" width="{bw:.1f}" height="{row_h - 8}" fill="#c4841d"/>\n')
        annot = f'{_pct(r["pct"])}  ({_usd(r["old"])} to {_usd(r["new"])}/GPU-hr)'
        parts.append(f'  <text x="{left + bw + 8}" y="{y + 18}" font-size="11" font-family="system-ui, sans-serif">{html.escape(annot)}</text>\n')
    parts.append(
        f'  <text x="12" y="{height - 10}" font-size="10" font-family="system-ui, sans-serif">'
        f'Source: Lantern Works GPU price history (CC BY 4.0), thelanternworks.com. '
        f'Tracked providers only; spot and on-demand are separate rows. {html.escape(fig["start"])} to {html.escape(fig["end"])}.</text>\n'
        f'</svg>\n'
    )
    return "".join(parts)


def post_markdown(fig: dict) -> str:
    start, end = fig["start"], fig["end"]
    top = fig["top5"]
    rows = fig["rows"]
    vendors = sorted({r["vendor"] for r in rows})
    all_same_vendor = len(vendors) == 1
    all_up = bool(rows) and all(r["new"] > r["old"] for r in rows)
    vendor_phrase = vendors[0] if all_same_vendor else "more than one vendor"
    if all_same_vendor and all_up:
        saw1 = (
            f'Of the eligible hourly rows, **{fig["n_moved"]}** changed price over the week, '
            f"and all of them were {vendor_phrase} rows, every one an increase. "
            f"Other tracked vendors' eligible hourly rows did not change in this window."
        )
    else:
        ups = sum(1 for r in rows if r["new"] > r["old"])
        downs = sum(1 for r in rows if r["new"] < r["old"])
        extra = f", all from {vendor_phrase}" if all_same_vendor else ""
        saw1 = (
            f'Of the eligible hourly rows, **{fig["n_moved"]}** changed price over the week '
            f"({ups} up, {downs} down){extra}."
        )
    by_key = {}
    for r in rows:
        by_key.setdefault((r["vendor"], r["gpu"], r["vram_gb"]), {})[r["kind"]] = r["pct"]
    paired = [v for v in by_key.values() if "on-demand" in v and "spot/interruptible" in v]
    same_pct = bool(paired) and all(v["on-demand"] == v["spot/interruptible"] for v in paired)
    if all_same_vendor and same_pct:
        saw2 = (
            f"{vendors[0]}'s spot rows moved by the same percentage as their matching on-demand rows, "
            "so the increases look like a lineup-wide change. We have no vendor explanation for it, and we are not guessing at one."
        )
    else:
        saw2 = "We have no vendor explanation for the moves, and we are not guessing at one."
    tie_pcts = [p for p in {r["pct"] for r in top} if sum(1 for r in top if r["pct"] == p) > 1]
    if tie_pcts:
        ties = ", ".join(_pct(p).lstrip("+") for p in sorted(tie_pcts, reverse=True))
        saw3 = (
            f"Several rows tie at {ties}; ties are ordered alphabetically by vendor and GPU, then by VRAM and type. "
            "The full list of moves is in [moves.json](moves.json) and in the table below."
        )
    else:
        saw3 = "The full list of moves is in [moves.json](moves.json) and in the table below."

    def table_row(r, with_vram=False):
        gpu = gpu_label(r) if with_vram else r["gpu"]
        return (
            f"| {r['vendor']} | {gpu} | {r['kind']} | {_usd(r['old'])} | {_usd(r['new'])} | "
            f"{_pct(r['pct'])} | {r['verified'] or ''} | [vendor page]({r['source_url']}) |"
        )

    top_rows = "\n".join(table_row(r, with_vram=False) for r in top)
    all_rows = "\n".join(table_row(r, with_vram=True) for r in rows)
    referral_top = any(r.get("referral") for r in top)
    if referral_top:
        disc_extra = (
            "Some of the five rows above have a labelled referral link; "
            "referral status did not affect which moves are listed or how they are ordered."
        )
    else:
        disc_extra = "None of the five rows above carries a referral link."

    feed_at = fig["feed_updated_at"]
    return f"""---
title: "GPU prices that moved: week to {end}"
date: {end}
---

# GPU prices that moved: week to {end}

Every week we compare a snapshot of our GPU price feed with the one from seven days earlier and list the biggest moves. This is the first edition, comparing the **{end}** snapshot with the **{start}** snapshot. Prices are USD per GPU-hour. Figures below were recomputed from the live public feeds; the current feed's `feed_updated_at` was **{feed_at}**. The prices in the tables are the last ranked hourly price on or before each snapshot date, so later re-checks of the same rate do not change the comparison.

**Scope:** tracked providers only, not the whole market. "Cheapest" anywhere on this site means cheapest among the providers we track. Spot/interruptible and on-demand prices are never mixed: each row says which it is. Vendors whose data is currently held as stale in this live feed are excluded, as are reserved, community, marketplace and monthly-billed rows.

![Chart of the five biggest tracked price moves](moved-chart.svg)

## The five biggest moves

| Vendor | GPU (1x) | Type | Prior ({start}) | Now ({end}) | Change | Row verified | Source |
|---|---|---|---|---|---|---|---|
{top_rows}

## What we saw

- {saw1}
- {saw2}
- {saw3}

## All {fig["n_moved"]} moves

VRAM is shown where two rows would otherwise share a GPU name.

| Vendor | GPU (1x) | Type | Prior ({start}) | Now ({end}) | Change | Row verified | Source |
|---|---|---|---|---|---|---|---|
{all_rows}

## Method

Prices come from the daily Lantern Works history feed (change-point series, hourly-equivalent USD per GPU). For each series we take the last price on or before each snapshot date, keep series ranked at both dates, and compute percent change as (new - old) / old. Each row's "verified" date is when that snapshot price was last confirmed on the vendor's page or API; prices can change after that, so check the vendor page before buying.

## Disclosure

Some vendors in our feed have referral links, and Lantern Works may earn a commission if you sign up through them. Referral status never affects ranking or which moves are listed. {disc_extra}

Data: [Lantern Works GPU price history](https://thelanternworks.com/api/v1/gpu-prices/history.json) and [current feed](https://thelanternworks.com/api/v1/gpu-prices.json), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: Lantern Works (https://thelanternworks.com). Spot and on-demand figures are provider-listed rates, not guarantees of availability. Found a wrong price? [Report it](https://thelanternworks.com/report-price/).
"""


def write_artifacts(fig: dict, data_reports: Path | None = None) -> dict[str, Path]:
    data_reports = data_reports or (ROOT / "data" / "reports")
    slug = f"{SLUG_PREFIX}-{fig['end']}"
    asset_dir = data_reports / slug
    asset_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "md": data_reports / f"{slug}.md",
        "figures": asset_dir / "figures.json",
        "moves": asset_dir / "moves.json",
        "chart": asset_dir / "moved-chart.svg",
    }
    slim = {k: fig[k] for k in ("feed_updated_at", "start", "end", "n_moved", "held_vendors", "top5")}
    paths["md"].write_text(post_markdown(fig), encoding="utf-8")
    paths["figures"].write_text(json.dumps(slim, indent=1) + "\n", encoding="utf-8")
    paths["moves"].write_text(json.dumps(fig["rows"], indent=1) + "\n", encoding="utf-8")
    paths["chart"].write_text(chart_svg(fig), encoding="utf-8")
    return paths


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--current", type=Path, required=True)
    p.add_argument("--history", type=Path, required=True)
    p.add_argument("--start", default="2026-11-13")
    p.add_argument("--end", default="2026-11-20")
    p.add_argument("--check", action="store_true", help="Recompute and require committed artifacts to match")
    args = p.parse_args(argv)
    current = json.loads(args.current.read_text(encoding="utf-8"))
    history = json.loads(args.history.read_text(encoding="utf-8"))
    fig = figures(current, history, args.start, args.end)
    if args.check:
        data_reports = ROOT / "data" / "reports"
        slug = f"{SLUG_PREFIX}-{fig['end']}"
        saved = json.loads((data_reports / slug / "figures.json").read_text(encoding="utf-8"))
        slim = {k: fig[k] for k in ("feed_updated_at", "start", "end", "n_moved", "held_vendors", "top5")}
        bad = []
        if saved != slim:
            bad.append("figures.json differs from recomputation")
        moves = json.loads((data_reports / slug / "moves.json").read_text(encoding="utf-8"))
        if moves != fig["rows"]:
            bad.append("moves.json differs from recomputation")
        md = (data_reports / f"{slug}.md").read_text(encoding="utf-8")
        for r in fig["top5"]:
            for tok in (_pct(r["pct"]), _usd(r["old"]), _usd(r["new"]), r["vendor"], r["source_url"]):
                if tok not in md:
                    bad.append("markdown missing " + tok)
        if fig["feed_updated_at"] not in md:
            bad.append("markdown missing live feed_updated_at")
        if bad:
            print("MISMATCH")
            for b in bad:
                print(" ", b)
            return 1
        print(f"OK: artifacts match live recomputation ({fig['n_moved']} moved rows, feed {fig['feed_updated_at']})")
        return 0
    paths = write_artifacts(fig)
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))
    print(f"n_moved={fig['n_moved']} feed_updated_at={fig['feed_updated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
