"""T117: citation URLs are URLs; API operations and record ids are evidence, not URL suffixes."""
from __future__ import annotations

import copy
import re
from urllib.parse import urlsplit


def valid_source_url(value) -> bool:
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and bool(p.hostname) and not p.username and not p.password
                and p.port != 0 and not re.search(r"%(?![0-9A-Fa-f]{2})", value))
    except ValueError:
        return False


def split_source(value: str) -> tuple[str, dict]:
    """Repair only the two exact, observed suffix formats; reject every other invalid URL."""
    if valid_source_url(value):
        return value, {}
    if not isinstance(value, str):
        raise ValueError("source_url must be a string")
    m = re.fullmatch(r"(https://api\.runpod\.io/graphql) (gpuTypes\.(?:securePrice|communityPrice)) id=(\S(?:.*\S)?)", value or "")
    if m:
        return m[1], {"request_method": "POST", "operation": m[2], "record_id": m[3]}
    m = re.fullmatch(r"(https://api\.datacrunch\.io/v1/instance-types) \(([^()\s]+)\)", value or "")
    if m:
        return m[1], {"request_method": "GET", "operation": "instance-types", "record_id": m[2]}
    raise ValueError("invalid source_url (expected a canonical https URL, without operation text)")


def citation_problems(doc: dict) -> list[str]:
    out = []
    def check(value, label):
        if not valid_source_url(value):
            out.append(f"{label}: invalid canonical source_url")
    check(doc.get("source_url"), str(doc.get("vendor", "?")))
    for r in doc.get("records") or []:
        label = f"{doc.get('vendor')} {r.get('gpu')} ({r.get('tier')})"
        check(r.get("source_url"), label)
        ev = r.get("evidence") or {}
        check(ev.get("source_url"), label + " evidence")
        request_keys = ("request_method", "operation", "record_id")
        if any(k in ev for k in request_keys):
            if ev.get("request_method") not in ("GET", "POST") or any(
                not isinstance(ev.get(k), str) or not ev[k].strip() or any(ord(c) < 32 for c in ev[k])
                for k in request_keys):
                out.append(label + ": invalid API request evidence")
        if ev.get("interruption_source_url"):
            check(ev["interruption_source_url"], label + " interruption")
    for key, extra in (doc.get("extras") or {}).items():
        if isinstance(extra, dict) and extra.get("source_url"):
            check(extra["source_url"], f"extras.{key}")
    return out


def normalize_doc(doc: dict) -> tuple[dict, int]:
    """Pure, lossless citation repair: no quote, price, timestamp or identity changes."""
    out, count = copy.deepcopy(doc), 0
    for r in out.get("records") or []:
        endpoint, detail = split_source(r["source_url"])
        ev = r.get("evidence") or {}
        ev_url, ev_detail = split_source(ev["source_url"])
        if endpoint != ev_url or detail != ev_detail:
            raise ValueError("record/evidence citation disagreement")
        if detail:
            for k, v in detail.items():
                if k in ev and ev[k] != v:
                    raise ValueError("conflicting existing citation evidence")
                ev[k] = v
            r["source_url"] = ev["source_url"] = endpoint
            count += 1
    problems = citation_problems(out)
    if problems:
        raise ValueError("; ".join(problems))
    return out, count

