"""MCP output contract (T36): typed output schemas, a stable error envelope, and brief/full modes.

Every tool result has `ok` (bool). Success: ok=true, mode, plus the tool's fields (mode="full" is unchanged
output; mode="brief" keeps only the essential fields). Failure: ok=false and error={code, message} with code
from ERROR_CODES. Shared by the stdio server and the hosted worker (both import this module).
"""
from __future__ import annotations

import copy

ERROR_CODES = ("invalid_argument", "invalid_cursor", "cursor_expired", "not_found", "feed_unavailable", "feed_invalid",
               "upstream_unavailable", "internal_error")
MODES = ("brief", "full")

ERROR_SCHEMA = {"type": "object", "required": ["code", "message"], "additionalProperties": False,
                "properties": {"code": {"type": "string", "enum": list(ERROR_CODES)}, "message": {"type": "string"}}}

_num = {"type": ["number", "null"]}
_str = {"type": ["string", "null"]}
_bool = {"type": ["boolean", "null"]}

# Per tool: (required top-level success keys, list key with rows, required row keys, brief top-level keys, brief row keys)
SPEC = {
    "compare_gpu_prices": (["gpu", "summary", "count", "results"], "results",
                           ["advertiser", "gpu", "hourly_usd", "source_url", "rank"],
                           ["gpu", "summary", "count", "results"],
                           ["rank", "advertiser", "gpu", "vram_gb", "hourly_usd", "tier_class", "source_url", "checked_at"]),
    "get_price_changes": (["total", "count", "changes"], "changes",
                          ["vendor", "gpu", "direction"],
                          ["summary", "total", "count", "changes", "next_cursor", "has_more"],
                          ["date", "event_id", "rate_id", "seq", "vendor", "gpu", "direction", "from_hourly_usd", "to_hourly_usd",
                           "change_pct", "source_url"]),
    "optimize_stack": (["lines", "total_monthly_usd", "total_is_complete"], "lines",
                       ["status"],
                       ["lines", "total_monthly_usd", "total_is_complete"],
                       ["need", "status", "monthly_cost_usd", "choice"]),
    "optimize_agent_stack": (["lines", "monthly_estimate_usd", "estimate_is_complete"], "lines",
                             ["component", "status"],
                             ["lines", "monthly_estimate_usd", "estimate_is_complete", "missing_components", "budget"],
                             ["component", "status", "monthly_cost_usd", "choice"]),
    "search_deals": (["total", "count", "results"], "results",
                     ["id"],
                     ["total", "count", "results", "next_cursor"],
                     ["id", "advertiser", "title", "offer_type", "price_usd", "redeem_url"]),
    "compare_deals": (["deals"], "deals",
                      ["id"],
                      ["order", "deals"],
                      ["id", "advertiser", "offer_type", "price_usd", "redeem_url"]),
    "get_deal": (["id"], None, [],
                 ["id", "title", "advertiser", "offer_type", "price_usd", "unit", "redeem_url", "verified_at", "affiliate"], []),
}
# Optional typed fields beyond the required ones (T38 paging for get_price_changes).
EXTRA_PROPS = {
    "get_price_changes": {
        "next_cursor": _str, "has_more": _bool, "last_seq": {"type": ["integer", "null"]},
        "changes": {"type": "array", "items": {"type": "object", "required": ["vendor", "gpu", "direction"],
                                                "properties": {"event_id": _str, "rate_id": _str, "key": _str,
                                                               "seq": {"type": ["integer", "null"]}, "snapshot_id": _str}}},
    },
}
BRIEF_CHOICE_KEYS = ("vendor", "plan", "monthly_cost_usd", "source_url", "verified_at", "checked_at")


def output_schema(tool: str) -> dict:
    req, list_key, row_req, _, _ = SPEC[tool]
    props = {"ok": {"type": "boolean"}, "mode": {"type": "string", "enum": list(MODES)}, "error": ERROR_SCHEMA}
    if list_key:
        props[list_key] = {"type": "array", "items": {"type": "object", "required": row_req}}
    props.update(EXTRA_PROPS.get(tool, {}))
    return {
        "type": "object",
        "required": ["ok"],
        "properties": props,
        "additionalProperties": True,
        "if": {"properties": {"ok": {"const": False}}},
        "then": {"required": ["ok", "error"]},
        "else": {"required": ["ok", "mode"] + req, "not": {"required": ["error"]}},
    }


def error(code: str, message: str) -> dict:
    code = code if code in ERROR_CODES else "internal_error"
    return {"ok": False, "error": {"code": code, "message": str(message)}}


def _brief_row(tool: str, row: dict, keys: list) -> dict:
    out = {k: row.get(k) for k in keys if k in row}
    if isinstance(out.get("choice"), dict):
        out["choice"] = {k: out["choice"][k] for k in BRIEF_CHOICE_KEYS if k in out["choice"]}
    return out


def finalize(tool: str, out, mode: str = "full") -> dict:
    """Wrap a raw tool result in the contract envelope."""
    if not isinstance(out, dict):
        return error("internal_error", "tool returned a non-object result")
    if isinstance(out.get("error"), dict) and set(out) <= {"error", "ok"}:
        e = out["error"]
        return error(e.get("code") or "internal_error", e.get("message") or "")
    _, list_key, _, brief_keys, brief_row = SPEC[tool]
    if mode == "full":
        return {"ok": True, "mode": "full", **out}
    b = {k: copy.deepcopy(out[k]) for k in brief_keys if k in out}
    if list_key and isinstance(b.get(list_key), list):
        b[list_key] = [_brief_row(tool, r, brief_row) if isinstance(r, dict) else r for r in b[list_key]]
    return {"ok": True, "mode": "brief", **b}
