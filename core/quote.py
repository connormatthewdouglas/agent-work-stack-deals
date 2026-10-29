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
            "hours": qty if gpu else None, "gpus": 1 if gpu else None,
            "checked_at": ch.get("checked_at") or ch.get("verified_at")}


def receipt(tool: str, lines: list[dict], data_timestamps: dict, now: datetime | None = None) -> dict:
    key = "need" if tool == "optimize_stack" else "component"
    items = sorted(filter(None, (_item(l, key) for l in lines or [])), key=lambda i: (str(i["line"]), i["rate_id"]))
    basis = {"v": QUOTE_VERSION, "tool": tool, "items": items,
             "data": {k: data_timestamps[k] for k in sorted(data_timestamps) if data_timestamps[k] is not None}}
    h = hashlib.sha256(json.dumps(basis, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"quote_id": "q_" + h[:QUOTE_ID_LEN], "issued_at": issued, "quote_basis": basis}
