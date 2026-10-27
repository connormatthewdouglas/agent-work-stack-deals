"""Agent Stack Optimizer: cheapest suitable plan per need among tracked providers (dependency-free).

Prices come only from structured, cited records in data/stack_pricing/<vendor>.json (each offer has the
vendor quote, source_url and checked_at) and from /api/v1/gpu-prices.json for GPU hours. Anything without a
published price or quantity is reported as "unknown", never estimated. Deals pulled from the public feed are
dropped at build time; deals whose signup is manual_only are flagged (and can be excluded).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

PRICING_DIR = Path(__file__).resolve().parents[1] / "data" / "stack_pricing"
TRACKED = "cheapest among tracked providers"

# need -> label, unit, deal tags that identify untracked providers of the same need
NEEDS = {
    "scrape_pages": ("Web pages scraped (no JS rendering)", "pages/month", {"scrape", "scraping", "crawl", "reader"}),
    "scrape_pages_js": ("Web pages scraped with JS rendering", "pages/month", {"scrape", "scraping", "browser"}),
    "proxy_gb": ("Residential proxy traffic", "GB/month", {"proxy", "proxies", "residential", "residential-proxy"}),
    "emails_sent": ("Transactional emails sent", "emails/month", {"transactional-email", "transactional", "smtp"}),
    "search_queries": ("Web search API queries", "queries/month", {"serp", "search-api", "search"}),
    "gpu_hours": ("GPU hours", "GPU-hours/month", {"gpu"}),
}
OFFER_FIELDS = ("need", "plan", "monthly_usd", "included", "overage_usd", "overage_per", "units_per_item", "quote", "assumptions")
EXCLUDE_TAGS = {"antidetect-browser"}
MAX_QTY = 10**9


def load_vendor_files(directory: Path | None = None) -> list[dict]:
    d = directory or PRICING_DIR
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def record_problems(doc: dict) -> list[str]:
    name = doc.get("vendor") or "?"
    out = [f"{name}: missing {k}" for k in ("vendor", "deal_id", "source_url", "checked_at", "offers") if not doc.get(k)]
    for i, o in enumerate(doc.get("offers") or []):
        tag = f"{name} offer {i} ({o.get('plan')})"
        out += [f"{tag}: missing {k}" for k in OFFER_FIELDS if k not in o]
        if o.get("need") not in NEEDS or o.get("need") == "gpu_hours":
            out.append(f"{tag}: unknown need {o.get('need')!r}")
        for k in ("monthly_usd", "included", "units_per_item"):
            if o.get(k) is not None and not _num(o[k]):
                out.append(f"{tag}: {k} must be a non-negative number or null")
        if (o.get("overage_usd") is None) != (o.get("overage_per") is None):
            out.append(f"{tag}: overage_usd and overage_per go together")
        if o.get("overage_per") is not None and not (_num(o["overage_per"]) and o["overage_per"] > 0):
            out.append(f"{tag}: overage_per must be > 0")
        if not str(o.get("quote") or "").strip():
            out.append(f"{tag}: empty quote")
        if not isinstance(o.get("assumptions"), list):
            out.append(f"{tag}: assumptions must be a list")
    return out


def build_payload(deals: list[dict], docs: list[dict] | None = None, base: str = "https://thelanternworks.com") -> dict:
    """Join pricing records with the PUBLIC feed. Records whose deal isn't in the feed (pulled/held) are dropped."""
    docs = load_vendor_files() if docs is None else docs
    by_id = {d["id"]: d for d in deals}
    problems, offers, dropped, priced_ids = [], [], [], set()
    for doc in docs:
        problems += record_problems(doc)
        deal = by_id.get(doc.get("deal_id"))
        if not deal:
            dropped.append(doc.get("vendor"))
            continue
        priced_ids.add(deal["id"])
        for o in doc.get("offers") or []:
            offers.append({"vendor": doc["vendor"], "deal_id": deal["id"], **{k: o.get(k) for k in OFFER_FIELDS},
                           "min_purchase_usd": o.get("min_purchase_usd"), "source_url": o.get("source_url") or doc["source_url"],
                           "checked_at": o.get("checked_at") or doc["checked_at"], "signup": deal.get("signup"),
                           "signup_note": deal.get("signup_note"), "affiliate": bool(deal.get("affiliate")),
                           "redeem_url": deal.get("redeem_url"), "deal_url": f"{base}/deals/{deal['id']}/"})
    priced_names = {(by_id[i].get("advertiser") or "").lower() for i in priced_ids}
    untracked = {}
    for need, (_, _, tags) in NEEDS.items():
        if need == "gpu_hours":
            continue
        rows = [d for d in deals if d["id"] not in priced_ids and not d.get("example")
                and (d.get("advertiser") or "").lower() not in priced_names
                and (set(d.get("tags") or []) & tags) and not (set(d.get("tags") or []) & EXCLUDE_TAGS)]
        untracked[need] = sorted({d.get("advertiser") or d["id"] for d in rows})
    manual = sorted(d["id"] for d in deals if d.get("signup") == "manual_only")
    return {"needs": {k: {"label": v[0], "unit": v[1]} for k, v in NEEDS.items()}, "offers": offers,
            "untracked": untracked, "manual_only_deal_ids": manual, "dropped_vendors": sorted(filter(None, dropped)),
            "problems": problems}


def offer_cost(o: dict, qty: float) -> dict:
    """{'cost': float} or {'unknown': reason} or {'unsuitable': reason}. Never guesses a missing number."""
    if o.get("units_per_item") is None:
        return {"unknown": "usage per item not published"}
    if o.get("monthly_usd") is None:
        return {"unknown": "plan price not published"}
    if o.get("included") is None:
        return {"unknown": "quantity included in the plan not published"}
    units = math.ceil(qty * o["units_per_item"])
    upi = o["units_per_item"]
    conv = f"{qty:,g} x {upi:g} = {units:,} credits; " if upi != 1 else ""
    if units <= o["included"]:
        return {"cost": float(o["monthly_usd"]), "calc": f"{conv}within {o['included']:,} included at ${o['monthly_usd']:g}/mo"}
    if o.get("overage_usd") is None:
        return {"unsuitable": f"needs {units:,} but the plan includes {o['included']:,} and no overage price is published"}
    packs = math.ceil((units - o["included"]) / o["overage_per"])
    extra = packs * o["overage_usd"]
    calc = (f"{conv}${o['monthly_usd']:g}/mo incl. {o['included']:,} + {packs:,} x ${o['overage_usd']:g} per "
            f"{o['overage_per']:,g} extra")
    if o.get("min_purchase_usd") and extra < o["min_purchase_usd"]:
        extra = float(o["min_purchase_usd"])
        calc += f" (raised to the ${o['min_purchase_usd']:g} minimum purchase)"
    return {"cost": round(o["monthly_usd"] + extra, 2), "calc": calc}


def _line_from_offer(o: dict, c: dict) -> dict:
    return {"vendor": o["vendor"], "plan": o["plan"], "deal_id": o["deal_id"], "monthly_cost_usd": c["cost"],
            "calc": c["calc"], "quote": o["quote"], "source_url": o["source_url"], "checked_at": o["checked_at"],
            "assumptions": o["assumptions"], "signup": o.get("signup"), "manual_signup_only": o.get("signup") == "manual_only",
            "signup_note": o.get("signup_note"), "affiliate": o["affiliate"], "redeem_url": o.get("redeem_url"),
            "deal_url": o.get("deal_url")}


def _gpu_options(gpu_data: dict, hours: float, model: str | None, manual: set) -> list[dict]:
    hpm = gpu_data.get("hours_per_month") or 730
    out = []
    for r in gpu_data.get("rates") or []:
        if model and not (r.get("gpu") == model or str(r.get("gpu", "")).startswith(model + " ")
                          or model.lower() in str(r.get("gpu", "")).lower().split()):
            continue
        if r.get("unit") == "hour":
            cost, calc = r["price_usd"] * hours, f"${r['price_usd']:g}/hr x {hours:,g} h"
        else:
            n = max(1, math.ceil(hours / hpm))
            per = r.get("gpu_count") or 1
            cost, calc = r["price_usd"] * n, (f"${r['price_usd']:g}/GPU-mo x {n} (per GPU; sold as {per}-GPU servers at "
                                              f"${r.get('server_price_usd') or 0:,.2f}/mo), flat regardless of hours"
                                              if per > 1 else f"${r['price_usd']:g}/mo x {n} server(s), flat regardless of hours")
        out.append({"vendor": r.get("advertiser"), "plan": f"{r.get('gpu')} ({r.get('tier') or r.get('billing') or ''})".replace(" ()", ""),
                    "deal_id": r.get("deal_id"), "monthly_cost_usd": round(cost, 2), "calc": calc, "quote": r.get("basis"),
                    "source_url": r.get("source_url"), "checked_at": r.get("verified_at"),
                    "assumptions": ["Excludes storage, egress, extra vCPU and taxes.", "1 GPU; hourly rates bill while running."]
                    + (["Interruptible: the vendor may preempt the job."] if r.get("interruptible") else []),
                    "signup": "manual_only" if r.get("deal_id") in manual else None,
                    "manual_signup_only": r.get("deal_id") in manual, "signup_note": None,
                    "affiliate": bool(r.get("affiliate")), "redeem_url": r.get("redeem_url"),
                    "deal_url": f"https://thelanternworks.com/deals/{r.get('deal_id')}/" if r.get("deal_id") else None})
    return sorted(out, key=lambda x: (x["monthly_cost_usd"], x["vendor"] or "", x["plan"]))


class StackError(ValueError):
    pass


def optimize(data: dict, needs: dict, gpu_data: dict | None = None, gpu_model: str | None = None,
             exclude_manual_signup: bool = False, alternatives: int = 3) -> dict:
    """needs: {need: quantity per month}, e.g. {"scrape_pages": 50000, "proxy_gb": 10, "emails_sent": 10000,
    "gpu_hours": 100}. Returns one line per need with the cheapest suitable tracked plan (or status 'unknown')."""
    if not isinstance(needs, dict) or not needs:
        raise StackError(f"needs must be an object of need -> monthly quantity; needs: {', '.join(NEEDS)}")
    bad = [k for k in needs if k not in NEEDS]
    if bad:
        raise StackError(f"unknown need(s) {bad}; valid: {', '.join(NEEDS)}")
    for k, v in needs.items():
        if not _num(v) or v > MAX_QTY:
            raise StackError(f"{k} must be a number 0-{MAX_QTY}")
    manual = set(data.get("manual_only_deal_ids") or [])
    lines = []
    for need, qty in needs.items():
        if not qty:
            continue
        label, unit, _ = NEEDS[need]
        line = {"need": need, "label": label, "quantity": qty, "unit": unit}
        priced, unknown, unsuitable, excluded = [], [], [], []
        if need == "gpu_hours":
            if gpu_data is None:
                raise StackError("gpu_hours needs GPU price data")
            priced = _gpu_options(gpu_data, qty, gpu_model, manual)
            line["gpu_model"] = gpu_model or "any"
            untracked = [u.get("advertiser") for u in gpu_data.get("unpriced") or []]
        else:
            for o in data.get("offers") or []:
                if o["need"] != need:
                    continue
                c = offer_cost(o, qty)
                ref = {"vendor": o["vendor"], "plan": o["plan"], "deal_id": o["deal_id"], "source_url": o["source_url"],
                       "checked_at": o["checked_at"], "quote": o["quote"]}
                if "unknown" in c:
                    unknown.append({**ref, "monthly_cost_usd": "unknown", "reason": c["unknown"], "assumptions": o["assumptions"]})
                elif "unsuitable" in c:
                    unsuitable.append({**ref, "reason": c["unsuitable"]})
                else:
                    priced.append(_line_from_offer(o, c))
            priced.sort(key=lambda x: (x["monthly_cost_usd"], x["vendor"], x["plan"]))
            untracked = (data.get("untracked") or {}).get(need, [])
        if exclude_manual_signup:
            excluded = [{"vendor": p["vendor"], "plan": p["plan"], "reason": "manual signup only"} for p in priced if p["manual_signup_only"]]
            priced = [p for p in priced if not p["manual_signup_only"]]
        # one row per vendor in alternatives (its cheapest suitable plan)
        best_per_vendor, seen = [], set()
        for p in priced:
            if p["vendor"] not in seen:
                seen.add(p["vendor"]); best_per_vendor.append(p)
        if best_per_vendor:
            line.update(status="priced", choice=best_per_vendor[0], monthly_cost_usd=best_per_vendor[0]["monthly_cost_usd"],
                        alternatives=best_per_vendor[1:1 + alternatives])
        else:
            line.update(status="unknown", choice=None, monthly_cost_usd="unknown", alternatives=[])
        uv = {}
        for u in unknown:
            uv.setdefault(u["vendor"], u)
        line.update(unknown_price=list(uv.values()), not_enough=unsuitable, excluded=excluded,
                    untracked_providers=untracked)
        lines.append(line)
    if not lines:
        raise StackError("every quantity is 0; give at least one need > 0")
    known = [l for l in lines if l["status"] == "priced"]
    manual_lines = [l["need"] for l in known if l["choice"]["manual_signup_only"]]
    return {
        "lines": lines,
        "total_monthly_usd": round(sum(l["monthly_cost_usd"] for l in known), 2),
        "total_is_complete": len(known) == len(lines),
        "unknown_needs": [l["need"] for l in lines if l["status"] != "priced"],
        "manual_signup_needs": manual_lines,
        "ranking": f"Per need, the {TRACKED} (vendors we don't track may cost less). Affiliate status is never a ranking factor.",
        "assumptions": ["Each need is priced on its own; plans that share one credit pool across needs aren't combined.",
                        "Monthly list prices before tax; free tiers count when the quantity fits.",
                        "'unknown' means the vendor doesn't publish the number; nothing is estimated.",
                        "Confirm on each source_url and get the user's approval before any paid signup."],
    }
