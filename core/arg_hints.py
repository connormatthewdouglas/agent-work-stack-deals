"""Close matches and example calls appended to existing MCP argument errors.

Hints are text-only. Error codes, envelope shape, and validation are unchanged:
a typo or empty value is still rejected.
"""
from __future__ import annotations

import difflib
import re

FIRST_CALL_EXAMPLES = {
    "compare_gpu_prices": 'compare_gpu_prices(gpu="H100")',
    "find_available_gpus": 'find_available_gpus(gpu="RTX 4090", gpus=1)',
    "estimate_job_cost": 'estimate_job_cost(gpu_family="A100", job_hours=8)',
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").casefold())


def close_matches(query: str, options: list[str], n: int = 3, cutoff: float = 0.6) -> list[str]:
    """Return close options for a typo or compacted name (e.g. H1000 → H100, rtx4090 → RTX 4090)."""
    if not (query or "").strip() or not options:
        return []
    qn = _norm(query)
    if not qn:
        return []
    exact = [o for o in options if _norm(o) == qn]
    if exact:
        return exact[:n]
    ranked: list[tuple[float, str]] = []
    for o in options:
        on = _norm(o)
        if not on:
            continue
        if on == qn:
            ranked.append((2.0, o))
        elif on in qn or qn in on:
            ranked.append((1.0 + (min(len(on), len(qn)) / max(len(on), len(qn))), o))
        else:
            ratio = difflib.SequenceMatcher(None, qn, on).ratio()
            if ratio >= cutoff:
                ranked.append((ratio, o))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _, o in ranked:
        if o not in seen:
            seen.add(o)
            out.append(o)
        if len(out) >= n:
            return out
    return out


def format_hint(message: str, *, close: list[str] | None = None, example: str | None = None) -> str:
    """Append close-match and example-call hints; leave the original message as the prefix."""
    parts = [(message or "").rstrip()]
    if close:
        parts.append("Did you mean " + ", ".join(f"'{c}'" for c in close) + "?")
    if example and example not in parts[0]:
        parts.append("Example: " + example)
    return " ".join(p for p in parts if p)


def example_for(tool: str, *, gpu: str | None = None) -> str | None:
    ex = FIRST_CALL_EXAMPLES.get(tool)
    if not ex or not gpu:
        return ex
    if tool == "compare_gpu_prices":
        return f'compare_gpu_prices(gpu="{gpu}")'
    if tool == "find_available_gpus":
        return f'find_available_gpus(gpu="{gpu}", gpus=1)'
    if tool == "estimate_job_cost":
        return f'estimate_job_cost(gpu_family="{gpu}", job_hours=8)'
    return ex


def unknown_gpu(message: str, query: str, models: list[str], tool: str) -> str:
    close = close_matches(query, models)
    return format_hint(message, close=close, example=example_for(tool, gpu=close[0] if close else None) or FIRST_CALL_EXAMPLES.get(tool))


def required_gpu(message: str, tool: str) -> str:
    return format_hint(message, example=FIRST_CALL_EXAMPLES.get(tool))


def bad_enum(message: str, query: str, options: list[str], example: str | None = None) -> str:
    return format_hint(message, close=close_matches(str(query), options, n=1, cutoff=0.5), example=example)
