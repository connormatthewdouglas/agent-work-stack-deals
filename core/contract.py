"""MCP output contract (T36): typed output schemas, a stable error envelope, and brief/full modes.

Every tool result has `ok` (bool). Success: ok=true, mode, plus the tool's fields (mode="full" is unchanged
output; mode="brief" keeps only the essential fields). Failure: ok=false and error={code, message} with code
from ERROR_CODES. Shared by the stdio server and the hosted worker (both import this module).
"""
from __future__ import annotations

import copy

from . import golinks

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
                            "on_demand_only", "on_demand_fallback",
                            # T63 (additive): serverless/per-second rows are held in every mode; the count stays visible in brief
                            "excluded_serverless",
                            # T61 (additive): the usable-memory filter outcome when min_usable_memory_gb is given
                            "usable_memory_filter", "model_identity_note",
                            # #122 (additive): GPU count ranked for (no count = 1, stated in assumptions)
                            # Bjorn 1109: min_gpus_unmet = count of rows excluded because min_gpus > gpus (list in full mode: excluded_min_gpus)
                            "gpus", "assumptions", "min_gpus_unmet"],
                           ["rank", "rate_id", "advertiser", "gpu", "vram_gb", "tier", "hourly_usd", "tier_class", "price_status",
                            "in_stock", "interruptible", "canonical_model", "form_factor", "source_url", "checked_at",
                            # Brain #247 (additive): currency, FX date, last verification, disclosed referral link
                            "quote_currency", "fx_date", "last_verified", "referral_url", "referral_label",
                            # T116: observed stock share; legacy expected_cost_usd is deprecated/null.
                            "availability_rate_7d", "expected_cost_usd",
                            # Scout schema 3.2 (additive): Scout's own status (in_stock|out_of_stock|unknown) and reason
                            "availability_status", "availability_reason", "availability_reason_detail",
                            # #122 (additive): the row's allocation minimum (rows above the requested gpus are excluded, #130)
                            "min_gpus"]),
    "get_price_changes": (["total", "count", "changes"], "changes",
                          ["vendor", "gpu", "direction"],
                          ["summary", "total", "count", "changes", "next_cursor", "has_more"],
                          ["date", "event_id", "rate_id", "seq", "vendor", "gpu", "direction", "from_hourly_usd", "to_hourly_usd",
                           "change_pct", "source_url", "last_verified_before", "gap_days"]),
    "optimize_stack": (["lines", "total_monthly_usd", "total_is_complete", "quote_id", "issued_at"], "lines",
                       ["status"],
                       ["lines", "total_monthly_usd", "total_is_complete", "quote_id", "issued_at"],
                       ["need", "status", "monthly_cost_usd", "choice", "excluded_serverless"]),
    "optimize_agent_stack": (["lines", "monthly_estimate_usd", "estimate_is_complete", "quote_id", "issued_at"], "lines",
                             ["component", "status"],
                             ["lines", "monthly_estimate_usd", "estimate_is_complete", "missing_components", "budget",
                              "quote_id", "issued_at"],
                             ["component", "status", "monthly_cost_usd", "choice", "excluded_serverless"]),
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
                           "quote_id", "issued_at",
                           # (additive) serverless/per-second rows are held out of cost ranking; count and reasons stay in brief
                           "excluded_serverless", "held_serverless"],
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
                                                               "seq": {"type": ["integer", "null"]}, "snapshot_id": _str,
                                                               # P46 (additive): bounds on when the change happened; null when unknown
                                                               "last_verified_before": {"type": ["string", "null"], "format": "date-time"},
                                                               "gap_days": {"type": ["number", "null"], "minimum": 0}}}},
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
                                                     "basis": _str, "source": {"type": ["string", "null"]},
                                                     # P36 (additive): last firm stock answer + its check time (display only)
                                                     **(_LAST_KNOWN := {"last_known_in_stock": {"type": ["boolean", "null"]},
                                                                        "last_known_at": {"type": ["string", "null"], "format": "date-time"}}),
                                                     **(_FAILURE_REASON := {  # P41 (additive): core.probe_reason; null when the source does not say
                                                         "failure_reason": {"type": ["string", "null"], "enum": ["sold_out", "region", "quota", "other", None]},
                                                         "failure_reason_detail": {"type": ["string", "null"]}})}}
_AVAIL_PROPS = {"availability": _AVAIL, "in_stock": {"type": ["boolean", "null"]}, "availability_note": _str, **_LAST_KNOWN, **_FAILURE_REASON}
_OPTION = {**_OPTION, "properties": {**_OPTION["properties"], **_AVAIL_PROPS}}
_LINES = {"type": "array", "items": {"type": "object", "properties": {"choice": _OPTION, "availability_note": _str,
                                                                     "gpu_count": {"type": ["integer", "null"], "minimum": 1},
                                                                     "alternatives": {"type": "array", "items": _OPTION}}}}
EXTRA_PROPS["compare_gpu_prices"] = {"results": {"type": "array", "items": {
    "type": "object", "required": SPEC["compare_gpu_prices"][2], "properties": {"canonical_model": _str, "form_factor": _str, "rate_id": _RATE_ID, "report_issue_url": _str,
                                                                          "region": {"type": ["string", "null"]}, "availability": _AVAIL, "in_stock": {"type": ["boolean", "null"]},
                                                                          "min_gpus": {"type": ["integer", "null"]}, **_LAST_KNOWN, **_FAILURE_REASON, **(_RATE_DATES := {
                                                                              # Brain #584 / eddie_compute (additive): core.rate_dates; null when not known
                                                                              "effective_at": {"type": ["string", "null"], "format": "date-time"},
                                                                              "effective_at_basis": {"type": ["string", "null"], "enum": ["vendor_stated", "first_observed", None]},
                                                                              "min_bill_usd_per_hour": {"type": ["number", "null"], "minimum": 0},
                                                                              "min_bill_basis": {"type": ["string", "null"], "enum": ["hourly_rate", "per_second_rate", "monthly_equivalent", None]}})}}},
    # #130: GPU count ranked for; rows whose min_gpus exceeds it are excluded (count + full-mode list with reasons)
    "gpus": {"type": "integer", "minimum": 1}, "assumptions": {"type": "array", "items": {"type": "string"}},
    "min_gpus_unmet": {"type": "integer", "minimum": 0},
    "excluded_min_gpus": {"type": "array", "items": {"type": "object", "required": ["vendor", "gpu", "min_gpus", "reason"],
                          "properties": {"vendor": _str, "gpu": _str, "tier": _str, "min_gpus": {"type": "integer"},
                                         "gpu_count": {"type": ["integer", "null"]}, "hourly_usd": {"type": ["number", "null"]},
                                         "rate_id": _str, "source_url": _str, "checked_at": _str, "reason": _str,
                                         "min_bill_usd_per_hour": _RATE_DATES["min_bill_usd_per_hour"],
                                         "min_bill_basis": _RATE_DATES["min_bill_basis"]}}}}
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
# T136 (additive): the tagged /go/ link stays in brief rows, and the one referral line stays in brief results
for _t, (_req, _lk, _rr, _bk, _br) in list(SPEC.items()):
    SPEC[_t] = (_req, _lk, _rr, list(_bk) + ["referral_disclosure"], list(_br) + (["tracked_url"] if _lk else []))
for _t in ("compare_gpu_prices", "estimate_job_cost"):  # P36 (additive): brief GPU rows keep the last firm stock answer
    SPEC[_t] = SPEC[_t][:4] + (list(SPEC[_t][4]) + ["last_known_in_stock", "last_known_at"],)
for _t in ("compare_gpu_prices", "estimate_job_cost"):  # P41 (additive): brief rows carry a non-null failure reason only
    SPEC[_t] = SPEC[_t][:4] + (list(SPEC[_t][4]) + ["failure_reason", "failure_reason_detail"],)
REFERRAL_DISCLOSURE_SCHEMA = {"type": "string", "description": "One-line referral disclosure, present whenever the result names a "
                              "provider; each provider-naming item then has tracked_url (tagged /go/ redirect)."}
BRIEF_CHOICE_KEYS = ("rate_id", "vendor", "plan", "monthly_cost_usd", "source_url", "verified_at", "checked_at", "tracked_url")


def output_schema(tool: str) -> dict:
    req, list_key, row_req, _, _ = SPEC[tool]
    props = {"ok": {"type": "boolean"}, "mode": {"type": "string", "enum": list(MODES)}, "error": ERROR_SCHEMA}
    if list_key:
        props[list_key] = {"type": "array", "items": {"type": "object", "required": row_req}}
    props.update(EXTRA_PROPS.get(tool, {}))
    props["referral_disclosure"] = REFERRAL_DISCLOSURE_SCHEMA  # T136: one line whenever the result names a provider
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
                          "second_read_gap_s", "second_read_basis", "two_read_gap_ok", "price_join_failed",
                          # P36 (additive): last firm stock answer and its check time, kept beside a lapsed claim
                          "last_known_in_stock", "last_known_at")


LAST_KNOWN_KEYS = ("last_known_in_stock", "last_known_at")  # same as core.gpu_availability.LAST_KNOWN_KEYS
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
            if k in av and k not in LAST_KNOWN_KEYS:
                out[k] = av[k]
    out.update(_brief_last_known(row.get("availability")))
    out.update(_brief_failure_reason(row))
    if not out.get("failure_reason"):
        out.pop("failure_reason", None)
        out.pop("failure_reason_detail", None)
    elif out.get("failure_reason_detail") is None:
        out.pop("failure_reason_detail", None)
    if tool == "compare_gpu_prices":
        out.update(_brief_rate_dates(row))
    if isinstance(out.get("choice"), dict):
        ch = out["choice"]
        out["choice"] = {k: ch[k] for k in BRIEF_CHOICE_KEYS if k in ch}
        if isinstance(ch.get("availability"), dict):
            out["choice"].update(_brief_last_known(ch["availability"]))
            out["choice"].update(_brief_failure_reason({"availability": ch["availability"], **ch}))
    return out


def _brief_last_known(av) -> dict:
    """P36 (additive): a brief GPU row carries last_known_in_stock / last_known_at only when they add something, i.e.
    the claim lapsed (in_stock null) after a firm answer. Absent means null or equal to in_stock / checked_at; full
    mode always has both inside availability. Keeps brief within its size budget."""
    if isinstance(av, dict) and av.get("in_stock") is None and isinstance(av.get("last_known_in_stock"), bool):
        return {k: av.get(k) for k in LAST_KNOWN_KEYS}
    return {}


def _fill_last_known(o) -> None:
    """P36 (additive, display only): give every availability dict in a tool result last_known_in_stock / last_known_at.
    A lapsed claim already carries them (core.gpu_availability.stale_guard); a current firm claim is its own last known
    value; anything else is null. Never invented, and ranking never reads them (it reads in_stock)."""
    from .gpu_availability import last_known
    if isinstance(o, dict):
        av = o.get("availability")
        if isinstance(av, dict):
            v, t = last_known(av)
            av["last_known_in_stock"], av["last_known_at"] = v, t
        for k, x in o.items():
            if k not in ("receipt", "error"):
                _fill_last_known(x)
    elif isinstance(o, list):
        for x in o:
            _fill_last_known(x)


def _brief_failure_reason(row) -> dict:
    """P41 (additive): a brief GPU row carries failure_reason (+ detail) only when the source gave a
    classified no or failure. Absent means null; full mode always has both inside availability."""
    from .probe_reason import classify
    src = row if isinstance(row, dict) else {}
    d = classify(src if src.get("availability") or "in_stock" in src or "availability_reason" in src else {"availability": src})
    out = {}
    if d.get("failure_reason"):
        out["failure_reason"] = d["failure_reason"]
        if d.get("failure_reason_detail"):
            out["failure_reason_detail"] = d["failure_reason_detail"]
    return out


def _fill_failure_reason(o, parent: dict | None = None) -> None:
    """P41 (additive, display only): give every availability dict failure_reason / failure_reason_detail.
    A lapsed out-of-stock claim keeps sold_out (or a source-stated region/quota) beside last_known_in_stock.
    Null when the source does not say. Never invented; ranking never reads these."""
    from .probe_reason import apply
    if isinstance(o, dict):
        av = o.get("availability")
        if isinstance(av, dict):
            apply(av, o if parent is None else {**parent, **o})
            for k in ("failure_reason", "failure_reason_detail"):
                o[k] = av.get(k)
        for k, x in o.items():
            if k not in ("receipt", "error"):
                _fill_failure_reason(x, o if "availability" in o or "advertiser" in o or "vendor" in o else parent)
    elif isinstance(o, list):
        for x in o:
            _fill_failure_reason(x, parent)


def _brief_rate_dates(row: dict) -> dict:
    """Brain #584 / eddie_compute (additive): a brief row carries effective_at (+ basis) only when it is known, and
    min_bill_usd_per_hour (+ basis) only when min_gpus > 1 (otherwise it equals hourly_usd). Absent = null or equal to
    hourly_usd; full mode always has all four. Keeps brief within its size budget."""
    out = {}
    if row.get("effective_at"):
        out.update({k: row.get(k) for k in ("effective_at", "effective_at_basis")})
    if (row.get("min_gpus") or 1) > 1 and row.get("min_bill_usd_per_hour") is not None:
        out.update({k: row.get(k) for k in ("min_bill_usd_per_hour", "min_bill_basis")})
    return out


def finalize(tool: str, out, mode: str = "full") -> dict:
    """Wrap a raw tool result in the contract envelope."""
    if not isinstance(out, dict):
        return error("internal_error", "tool returned a non-object result")
    if isinstance(out.get("error"), dict) and set(out) <= {"error", "ok"}:
        e = out["error"]
        return error(e.get("code") or "internal_error", e.get("message") or "")
    _, list_key, _, brief_keys, brief_row = SPEC[tool]
    out = golinks.annotate(copy.deepcopy(out))
    # T136: tagged /go/ link per provider + one referral line (additive, both modes)
    _fill_last_known(out)  # P36: every availability in a result says its last firm stock answer (null when never firm)
    _fill_failure_reason(out)  # P41: keep a failed/no probe's fixed reason (null when the source does not say)
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
