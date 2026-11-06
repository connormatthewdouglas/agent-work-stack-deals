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
                           ["advertiser", "gpu", "hourly_usd", "source_url", "rank", "rate_id"],
                           # T72 (brief is the default here): keep the counts, scope and refresh time a caller needs to
                           # trust the ranking, plus tier/price_status/in_stock per row; the bulky per-row detail stays full-only.
                           ["gpu", "summary", "scope", "count", "total", "excluded_non_on_demand", "excluded_reserved",
                            "next_refresh_utc", "data_checked_at", "refresh_hint", "results", "cheapest_by_form_factor", "cheapest_by_form_factor_note",
                            # T115 (additive): a relaxed hard constraint must stay visible in brief mode
                            "on_demand_only", "on_demand_fallback"],
                           ["rank", "rate_id", "advertiser", "gpu", "vram_gb", "tier", "hourly_usd", "tier_class", "price_status",
                            "in_stock", "interruptible", "canonical_model", "form_factor", "source_url", "checked_at",
                            # Brain #247 (additive): currency, FX date, last verification, disclosed referral link
                            "quote_currency", "fx_date", "last_verified", "referral_url", "referral_label",
                            # T116: observed stock share; legacy expected_cost_usd is deprecated/null.
                            "availability_rate_7d", "expected_cost_usd",
                            # Scout schema 3.2 (additive): Scout's own status (in_stock|out_of_stock|unknown) and reason
                            "availability_status", "availability_reason", "availability_reason_detail"]),
    "get_price_changes": (["total", "count", "changes"], "changes",
                          ["vendor", "gpu", "direction"],
                          ["summary", "total", "count", "changes", "next_cursor", "has_more"],
                          ["date", "event_id", "rate_id", "seq", "vendor", "gpu", "direction", "from_hourly_usd", "to_hourly_usd",
                           "change_pct", "source_url"]),
    "optimize_stack": (["lines", "total_monthly_usd", "total_is_complete", "quote_id", "issued_at"], "lines",
                       ["status"],
                       ["lines", "total_monthly_usd", "total_is_complete", "quote_id", "issued_at"],
                       ["need", "status", "monthly_cost_usd", "choice"]),
    "optimize_agent_stack": (["lines", "monthly_estimate_usd", "estimate_is_complete", "quote_id", "issued_at"], "lines",
                             ["component", "status"],
                             ["lines", "monthly_estimate_usd", "estimate_is_complete", "missing_components", "budget",
                              "quote_id", "issued_at"],
                             ["component", "status", "monthly_cost_usd", "choice"]),
    "search_deals": (["total", "count", "results"], "results",
                     ["id"],
                     ["total", "count", "results", "next_cursor"],
                     ["id", "advertiser", "title", "offer_type", "price_usd", "list_price_usd", "redeem_url", "source_url", "price_null_reason"]),
    "compare_deals": (["deals"], "deals",
                      ["id"],
                      ["order", "deals"],
                      ["id", "advertiser", "offer_type", "price_usd", "list_price_usd", "redeem_url", "source_url", "price_null_reason"]),
    "estimate_job_cost": (["gpu_family", "requested_gpus", "job_hours", "count", "results", "assumptions", "citations",
                           "missing_costs", "budget_verdict", "quote_id", "issued_at"], "results",
                          ["rank", "rate_id", "vendor", "allocated_gpus", "instances", "compute_subtotal_usd", "source_url"],
                          ["summary", "job_hours", "count", "results", "assumptions", "missing_costs", "budget_verdict",
                           "quote_id", "issued_at"],
                          ["rank", "rate_id", "vendor", "gpu", "allocated_gpus", "instances", "compute_subtotal_usd",
                           "source_url", "verified_at", "stale"]),
    "rebuild_quote": (["quote_id", "receipt_intact", "reproduced", "lines", "revalidation"], "lines",
                      ["line", "matches"],
                      ["quote_id", "receipt_intact", "reproduced", "lines", "revalidation"],
                      ["line", "rate_id", "recorded_subtotal_usd", "recomputed_subtotal_usd", "matches"]),
    "get_deal": (["id"], None, [],
                 ["id", "title", "advertiser", "offer_type", "price_usd", "list_price_usd", "unit", "redeem_url", "verified_at", "affiliate",
                  "source_url", "price_null_reason"], []),
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
# T39: rate_id on every compared rate and optimizer option; quote_id receipt on optimize/estimate responses.
_RATE_ID = {"type": "string", "pattern": "^r_[0-9a-f]{12}$"}
_OPTION = {"type": ["object", "null"], "properties": {"rate_id": _RATE_ID}, "required": ["rate_id"]}
_QUOTE = {"quote_id": {"type": "string", "pattern": "^q_[0-9a-f]{20}$"}, "issued_at": {"type": "string", "format": "date-time"},
          "quote_basis": {"type": "object"}}
# E5: availability passed through from the feed as-is (null when the feed has none; never invented).
_AVAIL = {"type": ["object", "null"], "properties": {"status": _str, "in_stock": {"type": ["boolean", "null"]},
                                                     "checked_at": {"type": ["string", "null"]}, "note": _str,
                                                     "basis": _str, "source": {"type": ["string", "null"]}}}
_AVAIL_PROPS = {"availability": _AVAIL, "in_stock": {"type": ["boolean", "null"]}, "availability_note": _str}
_OPTION = {**_OPTION, "properties": {**_OPTION["properties"], **_AVAIL_PROPS}}
_LINES = {"type": "array", "items": {"type": "object", "properties": {"choice": _OPTION, "availability_note": _str,
                                                                     "gpu_count": {"type": ["integer", "null"], "minimum": 1},
                                                                     "alternatives": {"type": "array", "items": _OPTION}}}}
EXTRA_PROPS["compare_gpu_prices"] = {"results": {"type": "array", "items": {
    "type": "object", "required": SPEC["compare_gpu_prices"][2], "properties": {"canonical_model": _str, "form_factor": _str, "rate_id": _RATE_ID, "report_issue_url": _str,
                                                                          "region": {"type": ["string", "null"]}, "availability": _AVAIL, "in_stock": {"type": ["boolean", "null"]}}}}}
EXTRA_PROPS["optimize_stack"] = {**_QUOTE, "lines": {**_LINES, "items": {**_LINES["items"], "required": ["status"]}}}
EXTRA_PROPS["optimize_agent_stack"] = {**_QUOTE, "lines": {**_LINES, "items": {**_LINES["items"], "required": ["component", "status"]}}}
EXTRA_PROPS["estimate_job_cost"] = {**_QUOTE, "results": {"type": "array", "items": {
    "type": "object", "required": SPEC["estimate_job_cost"][2],
    "properties": {"rate_id": _RATE_ID, "data_age_hours": _num, "degraded": _bool, "stale": _bool, **_AVAIL_PROPS}}},
    "budget_verdict": {"type": "string", "enum": ["unresolved", "within", "over"]}}
# T48 (0.4.0, additive): reopenable receipt on the three quoting tools.
_RECEIPT = {"receipt": {"type": "object", "required": ["receipt_version", "tool", "quote_id", "lines", "feed_revision", "receipt_sha256"]}}
for _t in ("optimize_stack", "optimize_agent_stack", "estimate_job_cost"):
    EXTRA_PROPS[_t] = {**EXTRA_PROPS[_t], **_RECEIPT}
BRIEF_CHOICE_KEYS = ("rate_id", "vendor", "plan", "monthly_cost_usd", "source_url", "verified_at", "checked_at")


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


def is_error(out) -> bool:
    """T44: the one isError rule for stdio and hosted. True iff the result is the error envelope (ok=false).

    No match is NOT an error: a valid query that matches nothing returns ok=true with an empty list (count 0),
    isError=false. not_found (ok=false) is reserved for a named thing that does not exist or is unsupported
    (unknown GPU/vendor/workload)."""
    return isinstance(out, dict) and out.get("ok") is False


def check_args(fn, args) -> dict | None:
    """T44/re26: one argument check for stdio and hosted, run before the tool. Returns the invalid_argument
    envelope for a non-object, a missing required argument, an unknown (extra) argument, or a wrong JSON type;
    None when the arguments are acceptable. Range checks stay in the tools."""
    import inspect
    import typing
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return error("invalid_argument", "arguments must be an object")
    params = inspect.signature(fn).parameters
    extra = sorted(k for k in args if k not in params)
    if extra:
        return error("invalid_argument", f"unknown argument(s): {', '.join(extra)}; valid: {', '.join(params)}")
    missing = [n for n, p in params.items() if p.default is inspect.Parameter.empty and n not in args]
    if missing:
        return error("invalid_argument", f"missing required argument(s): {', '.join(missing)}")
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001
        hints = {}
    for k, v in args.items():
        t = hints.get(k)
        if t is None:
            continue
        opts = typing.get_args(t) if typing.get_origin(t) in (typing.Union, getattr(__import__("types"), "UnionType", None)) else (t,)
        if v is None and type(None) in opts:
            continue
        if not any(_type_ok(v, o) for o in opts if o is not type(None)):
            want = " or ".join(_type_name(o) for o in opts)
            return error("invalid_argument", f"{k} must be {want}")
    return None


def _type_ok(v, t) -> bool:
    import typing
    if t is bool:
        return isinstance(v, bool)
    if t is int:
        return not isinstance(v, bool) and (isinstance(v, int) or (isinstance(v, float) and v.is_integer()))
    if t is float:
        return not isinstance(v, bool) and isinstance(v, (int, float))
    if t is str:
        return isinstance(v, str)
    if typing.get_origin(t) is list or t is list:
        inner = typing.get_args(t)
        return isinstance(v, list) and (not inner or all(_type_ok(x, inner[0]) for x in v))
    if t is dict or typing.get_origin(t) is dict:
        return isinstance(v, dict)
    return True


def _type_name(t) -> str:
    import typing
    names = {bool: "a boolean", int: "an integer", float: "a number", str: "a string", type(None): "null", dict: "an object"}
    if typing.get_origin(t) is list:
        return "an array"
    return names.get(t, getattr(t, "__name__", str(t)))


def error(code: str, message: str) -> dict:
    code = code if code in ERROR_CODES else "internal_error"
    return {"ok": False, "error": {"code": code, "message": str(message)}}


BRIEF_AVAIL_AUDIT_KEYS = ("stock_read_at", "price_read_at", "price_at_claim_usd", "first_read_at", "second_read_at",
                          "second_read_gap_s", "second_read_basis", "two_read_gap_ok", "price_join_failed")


DEAL_TOOLS = ("search_deals", "compare_deals", "get_deal")


def _brief_row(tool: str, row: dict, keys: list) -> dict:
    out = {k: row.get(k) for k in keys if k in row}
    if tool in DEAL_TOOLS and "price_usd" in out:  # Gauge rel054 #4 (additive): list_price_usd is always present, null when unknown
        out.setdefault("list_price_usd", None)
    if tool == "compare_gpu_prices" and (row.get("gpu_count") or 1) > 1:  # Gauge T73 fix7 #3 (additive): mark multi-GPU (8x) server rows; 1 is implied, keeps brief small
        out["gpu_count"] = row["gpu_count"]
    if tool == "compare_gpu_prices" and isinstance(row.get("availability"), dict):
        # Gauge T73 F1-F6 #3 (additive): brief rows carry the stock-claim audit fields that full rows hold in availability
        av = row["availability"]
        for k in BRIEF_AVAIL_AUDIT_KEYS:
            if k in av:
                out[k] = av[k]
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
    if tool == "compare_gpu_prices" and isinstance(out.get("constraints"), dict) and "applied" in out["constraints"]:
        b["constraints"] = {"applied": copy.deepcopy(out["constraints"]["applied"])}  # T115: applied constraints stay in brief
    if tool == "get_deal" and "price_usd" in b:
        b.setdefault("list_price_usd", None)
    if list_key and isinstance(b.get(list_key), list):
        b[list_key] = [_brief_row(tool, r, brief_row) if isinstance(r, dict) else r for r in b[list_key]]
    return {"ok": True, "mode": "brief", **b}
