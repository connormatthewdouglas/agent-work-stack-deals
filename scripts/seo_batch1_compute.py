#!/usr/bin/env python3
"""Derive every figure used in the SEO batch-1 pages from the live GPU price feed.

Numbers are computed at generate time from api/v1/gpu-prices.json and
api/v1/gpu-prices/history.json. They are never copied from a draft.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICES = ROOT / "api" / "v1" / "gpu-prices.json"
DEFAULT_HISTORY = ROOT / "api" / "v1" / "gpu-prices" / "history.json"

ET = ZoneInfo("America/New_York")
WEEK_START = date(2026, 11, 23)
WEEK_END = date(2026, 11, 28)  # last history snapshot; calendar week runs through Nov 29
WEEK_LABEL = "week of Nov 23, 2026"
FAMILY_PREFIX = {
    "H100": ("H100",),
    "L40S": ("L40S",),
    "A100": ("A100",),
}

# Worked example hour counts for the calculator page (assumptions, not measured jobs).
EXAMPLE_HOURS = (2, 4, 8, 24)


def fmt_usd(value: float) -> str:
    """Format a feed price: keep significant decimals, always at least two for whole cents."""
    if value is None:
        raise ValueError("price is None")
    sign = "-" if value < 0 else ""
    v = abs(value)
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    if "." not in s:
        s = f"{s}.00"
    else:
        whole, frac = s.split(".")
        if len(frac) == 1:
            s = f"{whole}.{frac}0"
    return f"{sign}${s}"


def fmt_usd_mul(rate: float, hours: float) -> str:
    # Round the product to 4 decimal places, then format like other money figures.
    # All worked examples in this batch land on exact cents.
    product = rate * hours
    rounded = round(product + 0.0, 4)
    return fmt_usd(rounded)


def parse_iso(ts: str) -> datetime:
    t = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_et(ts: str, with_utc: bool = True) -> str:
    dt = parse_iso(ts).astimezone(ET)
    # e.g. Nov 28, 2026, 2:02 AM ET
    minute = dt.strftime("%-I:%M")
    ampm = dt.strftime("%p").replace("AM", "AM").replace("PM", "PM")
    et_s = f"{dt.strftime('%b')} {dt.day}, {dt.year}, {minute} {ampm} ET"
    if not with_utc:
        return et_s
    utc = parse_iso(ts).astimezone(timezone.utc)
    utc_s = utc.strftime("%Y-%m-%d %H:%M UTC")
    return f"{et_s} ({utc_s})"


def fmt_et_short(ts: str) -> str:
    dt = parse_iso(ts).astimezone(ET)
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}, {dt.strftime('%-I:%M')} {dt.strftime('%p')} ET"


def family_of(gpu: str | None) -> str | None:
    g = gpu or ""
    if g.startswith("H100"):
        return "H100"
    if "L40S" in g:
        return "L40S"
    if g.startswith("A100"):
        return "A100"
    return None


def bucket(rate: dict) -> str:
    """Classify a live feed row or a history series (tier / tier_class / interruptible)."""
    tc = (rate.get("tier_class") or "").lower()
    tier = rate.get("tier") or ""
    tl = tier.lower()
    if tc == "reserved" or "reserv" in tl or "commit" in tl or (
        "month" in tl and "community" not in tl
    ) or "term contract" in tl:
        return "reserved"
    if "serverless" in tl or tc == "serverless":
        return "serverless"
    if (
        rate.get("interruptible")
        or tc in ("interruptible", "spot", "community")
        or "spot" in tl
        or "community" in tl
        or "preempt" in tl
    ):
        return "spot"
    if tc == "marketplace" or "marketplace" in tl or "aggregator" in tl:
        return "marketplace"
    if tc == "on-demand" or "on-demand" in tl or "on demand" in tl or "public cloud" in tl:
        return "on-demand"
    return "other"


def is_single_gpu(rate: dict) -> bool:
    count = rate.get("gpu_count")
    minimum = rate.get("min_gpus")
    if count is None:
        count = 1
    if minimum is None:
        minimum = 1
    return count == 1 and minimum == 1


def is_referral(rate: dict) -> bool:
    if rate.get("affiliate") is True:
        return True
    redeem = rate.get("redeem_url") or ""
    # Query-string referral markers used in this feed (ref, ref_id).
    if "ref=" in redeem or "ref_id=" in redeem:
        return True
    return False


def row_from_rate(r: dict) -> dict:
    price = r.get("hourly_equiv_usd")
    if price is None:
        price = r.get("price_usd")
    verified = r.get("verified_at") or r.get("checked_at")
    return {
        "vendor": r["advertiser"],
        "gpu": r.get("gpu"),
        "canonical_model": r.get("canonical_model"),
        "form_factor": r.get("form_factor") or "not stated",
        "vram_gb": r.get("vram_gb"),
        "tier": r.get("tier"),
        "tier_class": r.get("tier_class"),
        "interruptible": bool(r.get("interruptible")),
        "gpu_count": r.get("gpu_count") or 1,
        "min_gpus": r.get("min_gpus") or 1,
        "single_gpu": is_single_gpu(r),
        "price_usd": price,
        "price": fmt_usd(price) if price is not None else None,
        "verified_at": verified,
        "verified_et": fmt_et_short(verified) if verified else "unverified",
        "source_url": r.get("source_url"),
        "redeem_url": r.get("redeem_url"),
        "referral": is_referral(r),
        "bucket": bucket(r),
        "deal_id": r.get("deal_id"),
    }


def price_on(points: list[dict], day: date) -> dict | None:
    ds = day.isoformat()
    last = None
    for p in points:
        if p["date"] <= ds:
            last = p
        else:
            break
    return last


def load_snapshots(prices_path: Path | None = None, history_path: Path | None = None) -> tuple[dict, dict]:
    prices = json.loads((Path(prices_path) if prices_path else DEFAULT_PRICES).read_text(encoding="utf-8"))
    history = json.loads((Path(history_path) if history_path else DEFAULT_HISTORY).read_text(encoding="utf-8"))
    return prices, history


def family_rates(prices: dict, family: str) -> list[dict]:
    rows = []
    for r in prices["rates"]:
        if family_of(r.get("gpu") or r.get("canonical_model")) == family:
            rows.append(row_from_rate(r))
    rows.sort(key=lambda x: (x["price_usd"] is None, x["price_usd"] or 0, x["vendor"], x["gpu"] or ""))
    return rows


def cheapest_single(rows: list[dict], buck: str, extra=None) -> dict | None:
    cands = [r for r in rows if r["bucket"] == buck and r["single_gpu"] and r["price_usd"] is not None]
    if extra:
        cands = [r for r in cands if extra(r)]
    return cands[0] if cands else None


def week_days() -> list[date]:
    days = []
    d = WEEK_START
    while d <= WEEK_END:
        days.append(d)
        d += timedelta(days=1)
    return days


def history_changes(history: dict, family: str) -> list[dict]:
    out = []
    for c in history["changes"]:
        if not (WEEK_START.isoformat() <= c["date"] <= WEEK_END.isoformat()):
            continue
        if family_of(c.get("gpu")) != family:
            continue
        out.append(
            {
                "date": c["date"],
                "vendor": c["vendor"],
                "gpu": c["gpu"],
                "tier": c["tier"],
                "bucket": bucket({"tier": c["tier"]}),
                "from_hourly_usd": c.get("from_hourly_usd"),
                "to_hourly_usd": c.get("to_hourly_usd"),
                "from_price": fmt_usd(c["from_hourly_usd"]) if c.get("from_hourly_usd") is not None else None,
                "to_price": fmt_usd(c["to_hourly_usd"]) if c.get("to_hourly_usd") is not None else None,
                "change_pct": c.get("change_pct"),
                "status": c.get("status"),
                "composition_flag": c.get("composition_flag"),
                "source_url": c.get("source_url"),
                "rate_id": c.get("rate_id"),
            }
        )
    out.sort(key=lambda x: (x["date"], x["vendor"], x["gpu"], x["tier"]))
    return out


def daily_cheapest(history: dict, family: str, buck: str = "on-demand", pred=None) -> list[dict]:
    series = [s for s in history["series"] if family_of(s.get("gpu")) == family]
    days_out = []
    for day in week_days():
        cands = []
        for s in series:
            if s.get("gpu_count") != 1:
                continue
            # History series has no min_gpus; treat gpu_count==1 as single-GPU.
            p = price_on(s["points"], day)
            if not p or p.get("status") != "ranked" or p.get("hourly_usd") is None:
                continue
            b = bucket({"tier": s.get("tier")})
            if b != buck:
                continue
            row = {
                "price_usd": p["hourly_usd"],
                "vendor": s["vendor"],
                "gpu": s["gpu"],
                "tier": s["tier"],
                "vram_gb": s.get("vram_gb"),
                "verified_at": p.get("verified_at"),
                "point_date": p.get("date"),
            }
            if pred and not pred(row):
                continue
            cands.append(row)
        cands.sort(key=lambda x: (x["price_usd"], x["vendor"], x["gpu"]))
        top = cands[0] if cands else None
        days_out.append(
            {
                "date": day.isoformat(),
                "n": len(cands),
                "cheapest": (
                    {
                        **top,
                        "price": fmt_usd(top["price_usd"]),
                    }
                    if top
                    else None
                ),
            }
        )
    return days_out


def build_figures() -> dict:
    prices, history = load_snapshots()
    feed_updated_at = prices["feed_updated_at"]
    prices_verified_through = prices["prices_verified_through"]
    license_info = prices["license"]
    price_scope = prices["price_scope"]

    held_vendors = sorted({x["vendor"] for x in prices["held_stale"]})
    # Live `rates` already exclude held records. Vendors may still have other live SKUs.

    families = {}
    for fam in ("H100", "L40S", "A100"):
        rows = family_rates(prices, fam)
        vendors = sorted({r["vendor"] for r in rows})
        by_bucket = {}
        for b in ("on-demand", "spot", "marketplace", "serverless", "reserved", "other"):
            group = [r for r in rows if r["bucket"] == b]
            by_bucket[b] = {
                "all": group,
                "single": [r for r in group if r["single_gpu"]],
                "multi": [r for r in group if not r["single_gpu"]],
            }

        cheapest_od = cheapest_single(rows, "on-demand")
        cheapest_spot = cheapest_single(rows, "spot")
        extras = {}
        if fam == "H100":
            extras["cheapest_on_demand_sxm"] = cheapest_single(
                rows, "on-demand", lambda r: "SXM" in (r["gpu"] or "") or r["form_factor"] == "SXM"
            )
            extras["cheapest_on_demand_pcie"] = cheapest_single(
                rows, "on-demand", lambda r: "PCIe" in (r["gpu"] or "") or r["form_factor"] == "PCIe"
            )
            extras["cheapest_spot_single"] = cheapest_spot
        if fam == "A100":
            extras["cheapest_on_demand_40gb"] = cheapest_single(
                rows, "on-demand", lambda r: r.get("vram_gb") == 40
            )
            extras["cheapest_on_demand_80gb"] = cheapest_single(
                rows, "on-demand", lambda r: r.get("vram_gb") == 80
            )
            extras["cheapest_spot_single"] = cheapest_spot
            extras["cheapest_spot_80gb"] = cheapest_single(
                rows, "spot", lambda r: r.get("vram_gb") == 80
            )

        # Daily cheapest (classic on-demand, not marketplace)
        daily_od = daily_cheapest(history, fam, "on-demand")
        daily_od_80 = (
            daily_cheapest(history, fam, "on-demand", pred=lambda r: r.get("vram_gb") == 80)
            if fam == "A100"
            else None
        )
        daily_od_sxm = (
            daily_cheapest(
                history,
                fam,
                "on-demand",
                pred=lambda r: "SXM" in (r["gpu"] or ""),
            )
            if fam == "H100"
            else None
        )

        changes = history_changes(history, fam)

        families[fam] = {
            "rate_count": len(rows),
            "vendor_count": len(vendors),
            "vendors": vendors,
            "rows": rows,
            "by_bucket": by_bucket,
            "cheapest_on_demand_single": cheapest_od,
            "cheapest_spot_single": cheapest_spot,
            "extras": extras,
            "daily_cheapest_on_demand": daily_od,
            "daily_cheapest_on_demand_80gb": daily_od_80,
            "daily_cheapest_on_demand_sxm": daily_od_sxm,
            "changes": changes,
        }

    # Calculator rates (single-GPU on-demand, labelled).
    h100 = families["H100"]
    l40s = families["L40S"]
    a100 = families["A100"]
    calc_cols = [
        {
            "key": "l40s_cloudrift",
            "label": "L40S · CloudRift on-demand",
            "row": l40s["cheapest_on_demand_single"],
        },
        {
            "key": "a100_40_jarvislabs",
            "label": "A100 40GB · Jarvislabs on-demand",
            "row": a100["extras"]["cheapest_on_demand_40gb"],
        },
        {
            "key": "a100_80_thunder",
            "label": "A100 80GB · Thunder Compute on-demand",
            "row": a100["extras"]["cheapest_on_demand_80gb"],
        },
        {
            "key": "h100_pcie_hyperstack",
            "label": "H100 PCIe · Hyperstack on-demand",
            "row": h100["extras"]["cheapest_on_demand_pcie"],
        },
        {
            "key": "h100_sxm_civo",
            "label": "H100 SXM · Civo on-demand",
            "row": h100["extras"]["cheapest_on_demand_sxm"],
        },
    ]
    calculator = {
        "hours": list(EXAMPLE_HOURS),
        "columns": [],
        "cells": {},  # key -> {hours: {usd, display}}
    }
    for col in calc_cols:
        row = col["row"]
        if row is None:
            raise RuntimeError(f"missing calculator column {col['key']}")
        entry = {
            **col,
            "vendor": row["vendor"],
            "gpu": row["gpu"],
            "vram_gb": row["vram_gb"],
            "rate_usd": row["price_usd"],
            "rate": row["price"],
            "verified_et": row["verified_et"],
            "source_url": row["source_url"],
            "referral": row["referral"],
        }
        calculator["columns"].append(entry)
        calculator["cells"][col["key"]] = {
            str(h): {"usd": round(row["price_usd"] * h, 4), "display": fmt_usd_mul(row["price_usd"], h)}
            for h in EXAMPLE_HOURS
        }

    figures = {
        "week_label": WEEK_LABEL,
        "week_start": WEEK_START.isoformat(),
        "week_end_snapshot": WEEK_END.isoformat(),
        "week_end_calendar": "2026-11-29",
        "feed_updated_at": feed_updated_at,
        "feed_updated_at_et": fmt_et(feed_updated_at),
        "prices_verified_through": prices_verified_through,
        "prices_verified_through_et": fmt_et(prices_verified_through),
        "license": license_info,
        "price_scope": price_scope,
        "held_stale_vendors": held_vendors,
        "snapshot_ids_this_week": [
            s for s in history["snapshot_ids"] if s[:10] >= WEEK_START.isoformat() and s[:10] <= WEEK_END.isoformat()
        ],
        "history_snapshot_count_this_week": None,
        "families": families,
        "calculator": calculator,
        "mcp": {
            "hosted_url": "https://lantern-works-mcp.lantern-works.workers.dev/mcp",
            "hosted_add": "claude mcp add --transport http lantern-works-deals https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=seo-batch1",
            "uvx_add": "claude mcp add lantern-works-deals -- uvx lantern-works-deals-mcp",
            "uvx_command": "uvx lantern-works-deals-mcp",
            "install_docs": "https://thelanternworks.com/install/",
            "api_docs": "https://thelanternworks.com/api/",
            "tools": {
                "compare_gpu_prices": {
                    "name": "compare_gpu_prices",
                    "h100": {"gpu": "H100", "on_demand_only": True},
                    "l40s": {"gpu": "L40S", "on_demand_only": True},
                    "a100": {"gpu": "A100", "on_demand_only": True},
                },
                "estimate_job_cost": {
                    "name": "estimate_job_cost",
                    "example": {
                        "gpu_family": "H100",
                        "gpus_per_job": 1,
                        "job_hours": 8,
                        "allow_interruptible": False,
                    },
                },
            },
        },
        "slugs": {
            "H100": "/reports/cheapest-h100-week-of-2026-11-23/",
            "L40S": "/reports/cheapest-l40s-week-of-2026-11-23/",
            "A100": "/reports/cheapest-a100-week-of-2026-11-23/",
            "cost": "/cost/fine-tune-7b-8b-lora/",
        },
        "live_pages": {
            "H100": "https://thelanternworks.com/gpu/h100-rental-price/",
            "L40S": "https://thelanternworks.com/gpu/l40s-rental-price/",
            "A100": "https://thelanternworks.com/gpu/a100-rental-price/",
            "cost_index": "https://thelanternworks.com/cost/",
            "calculator": "https://thelanternworks.com/tools/gpu-cost-calculator/",
        },
    }
    figures["history_snapshot_count_this_week"] = len(figures["snapshot_ids_this_week"])
    return figures


def json_safe(obj):
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(x) for x in obj]
    return obj


if __name__ == "__main__":
    figs = build_figures()
    # Drop bulky full row lists from the printed summary; still write a compact headline file.
    summary = {
        "feed_updated_at_et": figs["feed_updated_at_et"],
        "week": f"{figs['week_start']} through {figs['week_end_snapshot']} (calendar week ends {figs['week_end_calendar']})",
        "headlines": {},
        "calculator_sample_8h": {k: v["8"] for k, v in figs["calculator"]["cells"].items()},
        "history_snapshots": figs["snapshot_ids_this_week"],
    }
    for fam, data in figs["families"].items():
        od = data["cheapest_on_demand_single"]
        summary["headlines"][fam] = {
            "rates": data["rate_count"],
            "vendors": data["vendor_count"],
            "cheapest_od": f"{od['price']}/hr {od['vendor']} {od['gpu']} vram={od['vram_gb']} verified {od['verified_et']}",
            "od_single": len(data["by_bucket"]["on-demand"]["single"]),
            "spot_single": len(data["by_bucket"]["spot"]["single"]),
            "changes": len(data["changes"]),
            "daily_od_vendors": [d["cheapest"]["vendor"] + " " + d["cheapest"]["price"] for d in data["daily_cheapest_on_demand"]],
        }
    print(json.dumps(summary, indent=2))
