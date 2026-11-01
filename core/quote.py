"""Quote receipts (T39): a citable, deterministic quote_id for estimate/optimize responses.

rate_id comes from core.ids (T38) and is never re-implemented here. For non-GPU stack plans and deal-feed
entry prices, offer_rate_id() feeds core.ids.rate_id a namespaced identity ('<need>:<plan>' or 'deal:<id>')
so every option carries an id of the same form.

quote_id = 'q_' + sha256 over the canonical JSON of: each priced line's (line, rate_id, quantity, hours, gpus,
checked_at) sorted by line, plus the data timestamps (feed_updated_at values). issued_at is reported next to it
but is NOT hashed, so the same inputs on the same data always give the same quote_id.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .ids import rate_id

QUOTE_VERSION = 1
QUOTE_ID_LEN = 20


def offer_rate_id(vendor: str | None, need: str, plan: str | None = None, deal_id: str | None = None) -> str:
    """rate_id for a non-GPU option: a stack plan (need + plan name) or a deal-feed entry price (deal id)."""
    ident = f"deal:{deal_id}" if deal_id and plan is None else f"{need}:{plan or ''}"
    return rate_id({"vendor": vendor, "gpu": ident, "tier": "plan", "billing_unit": "monthly", "unit": "month"})


def _item(line: dict, key: str) -> dict | None:
    ch = line.get("choice")
    if not isinstance(ch, dict) or not ch.get("rate_id"):
        return None
    qty = line.get("quantity")
    gpu = key in ("gpu_hours", "gpu") or line.get("need") == "gpu_hours" or line.get("component") == "gpu"
    return {"line": line.get(key), "rate_id": ch["rate_id"], "quantity": qty,
            "hours": line.get("hours_per_gpu", qty) if gpu else None, "gpus": (line.get("gpu_count") or 1) if gpu else None,
            "checked_at": ch.get("checked_at") or ch.get("verified_at")}


def receipt(tool: str, lines: list[dict], data_timestamps: dict, now: datetime | None = None) -> dict:
    key = "need" if tool == "optimize_stack" else "component"
    items = sorted(filter(None, (_item(l, key) for l in lines or [])), key=lambda i: (str(i["line"]), i["rate_id"]))
    basis = {"v": QUOTE_VERSION, "tool": tool, "items": items,
             "data": {k: data_timestamps[k] for k in sorted(data_timestamps) if data_timestamps[k] is not None}}
    h = hashlib.sha256(json.dumps(basis, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"quote_id": "q_" + h[:QUOTE_ID_LEN], "issued_at": issued, "quote_basis": basis}


# ---- T48 (0.4.0): reopenable, independently reproducible receipts. Additive: quote_id/quote_basis are unchanged. ----
RECEIPT_VERSION = 1
SNAPSHOT_URL = "https://raw.githubusercontent.com/connormatthewdouglas/agent-work-stack-deals/main/data/gpu_pricing/snapshots/{date}.json"


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def gpu_rate_index(gpu: dict | None) -> dict:
    """rate_id -> feed rate (ranked rows and held rows are both looked up; held rows are marked)."""
    out = {}
    for r in (gpu or {}).get("rates") or []:
        out.setdefault(rate_id(r), r)
    return out


def feed_revision(gpu: dict | None, stack_data: dict | None = None) -> dict:
    """The feed state a quote was computed from: timestamps, Scout generation, a content hash of the GPU rates,
    and the public daily snapshot for that date (a revision anyone can re-download)."""
    g = gpu or {}
    fu = g.get("feed_updated_at")
    return {"gpu_prices_url": "https://thelanternworks.com/api/v1/gpu-prices.json",
            "gpu_prices_feed_updated_at": fu, "generation_id": g.get("generation_id"),
            "gpu_rates_sha256": _sha(g.get("rates") or []) if g else None,
            "daily_snapshot_url": SNAPSHOT_URL.format(date=fu[:10]) if fu else None,
            "stack_pricing_feed_updated_at": (stack_data or {}).get("feed_updated_at")}


def gpu_line(line: str, r: dict, hours: float, gpus_billed: int, instances: int | None, subtotal: float,
             gpu_count: int | None = None) -> dict:
    ev = r.get("evidence") or {}
    return {"line": line, "rate_id": rate_id(r), "kind": "gpu_hour", "vendor": r.get("advertiser") or r.get("vendor"),
            "offer": r.get("gpu"), "vram_gb": r.get("vram_gb"), "tier": r.get("tier"),
            "quoted_price_usd": r.get("hourly_equiv_usd", r.get("hourly_usd")), "price_unit": "per GPU-hour",
            "hours": hours, "gpu_count": gpu_count or gpus_billed, "gpus_billed": gpus_billed, "instances": instances, "subtotal_usd": subtotal,
            "formula": "quoted_price_usd x hours x gpus_billed",
            "source_url": r.get("source_url"), "evidence_quote": ev.get("quote") or r.get("basis"),
            "evidence_checked_at": ev.get("checked_at"), "verified_at": r.get("verified_at") or r.get("checked_at")}


def plan_line(line: str, ch: dict) -> dict:
    """A flat monthly plan line (non-GPU stack need): the quoted price is the plan's monthly cost."""
    return {"line": line, "rate_id": ch.get("rate_id"), "kind": "flat_monthly", "vendor": ch.get("vendor"),
            "offer": ch.get("plan"), "quoted_price_usd": ch.get("monthly_cost_usd"), "price_unit": "per month (plan)",
            "subtotal_usd": ch.get("monthly_cost_usd"), "formula": "subtotal_usd = quoted_price_usd",
            "source_url": ch.get("source_url"), "evidence_quote": ch.get("quote"),
            "verified_at": ch.get("verified_at") or ch.get("checked_at")}


def full_receipt(tool: str, quote_id: str, lines: list[dict], lines_are: str, revision: dict, inputs: dict,
                 total_usd: float | None = None, missing_costs=None) -> dict:
    """lines_are: 'alternatives' (ranked options, not summed) or 'components' (summed into total_usd).
    inputs are the tool's numeric/config arguments only; free-text descriptions are never stored."""
    body = {"receipt_version": RECEIPT_VERSION, "tool": tool, "quote_id": quote_id, "inputs": inputs,
            "lines_are": lines_are, "lines": lines, "total_usd": total_usd, "missing_costs": missing_costs,
            "excludes": "storage, data egress, extra vCPU/RAM and taxes unless listed in missing_costs",
            "feed_revision": revision}
    return {**body, "receipt_sha256": _sha(body)}


def _expected(l: dict) -> float | None:
    if l.get("kind") == "gpu_hour":
        try:
            return round(float(l["quoted_price_usd"]) * float(l["hours"]) * int(l["gpus_billed"]), 2)
        except (TypeError, ValueError, KeyError):
            return None
    return l.get("quoted_price_usd")


def snapshot_prices(snapshot: dict | None) -> dict:
    """rate_id -> every hourly_usd for that rate_id in a published daily snapshot (data/gpu_pricing/snapshots/DATE.json).
    Older snapshots have no gpu_count, so 1x and 8x rows can share a rate_id; a match to any of them counts."""
    out: dict = {}
    for row in (snapshot or {}).get("rows") or []:
        try:
            out.setdefault(rate_id(row), []).append(row.get("hourly_usd"))
        except Exception:  # noqa: BLE001  (a malformed row simply can't vouch for anything)
            pass
    return out


def _same_price(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-6
    except (TypeError, ValueError):
        return False


def provenance(receipt: dict, gpu_today: dict | None, snapshot: dict | None = None) -> dict:
    """Check every line against data the server holds, never against the caller: the pinned feed revision (when the
    receipt's gpu_rates_sha256 equals today's feed, the line's rate_id must exist there at the same price), else the
    published daily snapshot for the receipt's date. No signing key: a line that can't be checked is unverified."""
    fr = receipt.get("feed_revision") or {}
    today_sha = _sha((gpu_today or {}).get("rates") or []) if gpu_today else None
    pinned = bool(today_sha and fr.get("gpu_rates_sha256") == today_sha)
    idx = gpu_rate_index(gpu_today) if pinned else {}
    snap = snapshot_prices(snapshot) if snapshot else {}
    lines, all_ok = [], True
    for l in receipt.get("lines") or []:
        rid, price = l.get("rate_id"), l.get("quoted_price_usd")
        if l.get("kind") != "gpu_hour":
            st, basis = "unverified", "flat plan lines have no pinned revision to check against"
        elif pinned:
            r = idx.get(rid)
            if r is None:
                st, basis = "unknown_rate_id", "rate_id not in the pinned feed revision"
            elif _same_price(r.get("hourly_equiv_usd", r.get("hourly_usd")), price):
                st, basis = "verified", "pinned feed revision (gpu_rates_sha256)"
            else:
                st, basis = "price_mismatch", "quoted_price_usd differs from the pinned feed revision"
        elif snap:
            if rid not in snap:
                st, basis = "unknown_rate_id", "rate_id not in the daily snapshot"
            elif any(_same_price(p, price) for p in snap[rid]):
                st, basis = "verified", "daily snapshot"
            else:
                st, basis = "price_mismatch", "quoted_price_usd differs from the daily snapshot"
        else:
            st, basis = "unverified", "pinned revision is not today's feed and its daily snapshot was unavailable"
        all_ok &= st == "verified"
        lines.append({"line": l.get("line"), "rate_id": rid, "status": st, "basis": basis})
    return {"verified": bool(all_ok and lines), "pinned_revision_is_today": pinned,
            "snapshot_checked": bool(snap) and not pinned, "lines": lines}


def rebuild(receipt: dict, gpu_today: dict | None, snapshot: dict | None = None) -> dict:
    """Re-run a past receipt: (1) reproduce its own arithmetic and integrity from the receipt alone, as of its
    feed revision; (2) separately revalidate each GPU line against today's feed. rate_id ignores cosmetic labels,
    so a renamed tier keeps its identity; a price or evidence change is reported as a new revision."""
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    intact = receipt.get("receipt_sha256") == _sha(body)
    rep, ok = [], True
    for l in receipt.get("lines") or []:
        exp = _expected(l)
        good = exp is not None and l.get("subtotal_usd") is not None and abs(exp - float(l["subtotal_usd"])) <= 0.011
        ok &= good
        rep.append({"line": l.get("line"), "rate_id": l.get("rate_id"), "recorded_subtotal_usd": l.get("subtotal_usd"),
                    "recomputed_subtotal_usd": exp, "matches": good})
    if receipt.get("lines_are") == "components" and receipt.get("total_usd") is not None:
        s = round(sum(float(l.get("subtotal_usd") or 0) for l in receipt.get("lines") or []), 2)
        ok &= abs(s - float(receipt["total_usd"])) <= 0.011 * max(1, len(receipt.get("lines") or []))
    idx = gpu_rate_index(gpu_today)
    held = set()
    for h in (gpu_today or {}).get("held_stale") or []:
        for h_r in h.get("records") or []:
            try:
                held.add(rate_id({"billing_unit": "hourly", **h_r, "advertiser": h.get("vendor")}))
            except Exception:  # noqa: BLE001  (best effort: an unmatched held row reads as not_in_feed_today)
                pass
    reval, changed = [], False
    for l in receipt.get("lines") or []:
        if l.get("kind") != "gpu_hour":
            reval.append({"line": l.get("line"), "rate_id": l.get("rate_id"), "status": "not_revalidated",
                          "note": "flat stack plans are not revalidated here; re-run the optimizer for today's plan prices"})
            continue
        r = idx.get(l.get("rate_id"))
        if r is None:
            st = "held_today" if l.get("rate_id") in held else "not_in_feed_today"
            changed = True
            reval.append({"line": l["line"], "rate_id": l["rate_id"], "status": st})
            continue
        now_l = gpu_line(l["line"], r, l["hours"], l["gpus_billed"], l.get("instances"),
                         gpu_count=l.get("gpu_count"), subtotal=_expected({**l, "quoted_price_usd": r.get("hourly_equiv_usd", r.get("hourly_usd"))}))
        if abs(float(now_l["quoted_price_usd"]) - float(l["quoted_price_usd"])) > 1e-9:
            st = "price_changed"
        elif (now_l["evidence_quote"], now_l["source_url"]) != (l.get("evidence_quote"), l.get("source_url")):
            st = "evidence_changed"
        else:
            st = "unchanged"
        changed |= st != "unchanged"
        reval.append({"line": l["line"], "rate_id": l["rate_id"], "status": st, "quoted_price_usd_then": l["quoted_price_usd"],
                      "quoted_price_usd_today": now_l["quoted_price_usd"], "subtotal_usd_then": l["subtotal_usd"],
                      "subtotal_usd_today": now_l["subtotal_usd"], "source_url_today": now_l["source_url"],
                      "verified_at_today": now_l["verified_at"]})
    prov = provenance(receipt, gpu_today, snapshot)
    # reproduced=True only when the arithmetic holds AND every line's rate_id and price check out against server-held
    # data; the sha256 is unkeyed, so a self-consistent forged receipt is at best 'arithmetic_only'.
    arith = bool(ok and intact)
    reproduced = (True if prov["verified"] else "arithmetic_only") if arith else False
    return {"quote_id": receipt.get("quote_id"), "receipt_intact": intact, "reproduced": reproduced,
            "provenance_verified": prov["verified"], "provenance": prov,
            "as_of": receipt.get("feed_revision"), "lines": rep,
            "revalidation": {"feed_revision_today": feed_revision(gpu_today), "lines": reval,
                             "revision": "new" if changed else "same",
                             "note": "'new' means a price, evidence or listing change since the receipt; the receipt itself still reproduces."}}
