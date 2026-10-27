"""Opt-in, anonymous tool-call counter. OFF unless LANTERN_TELEMETRY=1.

What is sent (only when enabled and a collector URL is configured), at most once per UTC day:
    {"events": [{"t": "<tool name>", "v": "<package version>", "d": "YYYY-MM-DD", "n": <calls>}]}
Nothing else: no arguments, query text, results, install/user/host IDs, or client info. The collector
stores only aggregate counts per (day, tool, version) and does not store IPs.

Counts are kept in a small local file (``$XDG_CACHE_HOME/lantern-works-deals-mcp/telemetry.json``,
holding just {day: {tool|version: n}}) so a short-lived stdio process can batch a whole day. Completed
days are sent in one background request with a short timeout. Any error is swallowed: telemetry never
blocks, slows or breaks a tool call.

Env:
    LANTERN_TELEMETRY=1            enable (anything else, or unset = disabled; no file, no network)
    LANTERN_TELEMETRY_URL=<url>    override the collector endpoint
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Empty until the collector is deployed: with no URL, enabling telemetry only counts locally.
DEFAULT_URL = "https://lantern-works-telemetry.lantern-works.workers.dev/v1/events"
TIMEOUT_S = 2.0
TOOLS = frozenset({"search_deals", "compare_deals", "get_deal", "compare_gpu_prices", "optimize_stack"})
_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("LANTERN_TELEMETRY", "").strip() == "1"


def collector_url() -> str:
    return os.environ.get("LANTERN_TELEMETRY_URL", "").strip() or DEFAULT_URL


def _state_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "lantern-works-deals-mcp" / "telemetry.json"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def build_payload(counts: dict) -> dict:
    """counts: {day: {"tool|version": n}} -> wire payload (only t, v, d, n)."""
    ev = []
    for day, per in sorted(counts.items()):
        for key, n in sorted(per.items()):
            tool, _, ver = key.partition("|")
            if tool in TOOLS and isinstance(n, int) and n > 0:
                ev.append({"t": tool, "v": ver, "d": day, "n": n})
    return {"events": ev}


def send(payload: dict, url: str, timeout: float = TIMEOUT_S) -> bool:
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "lantern-works-deals-mcp-telemetry"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def _flush_due(state: dict, today: str) -> None:
    """Send completed days (< today) once; drop them on success. Caller holds no lock while sending."""
    url = collector_url()
    due = {d: c for d, c in state.get("counts", {}).items() if d < today}
    if not url or not due or state.get("last_sent") == today:
        return
    payload = build_payload(due)

    def worker():
        try:
            ok = send(payload, url) if payload["events"] else True
            with _lock:
                p = _state_path()
                cur = _load(p)
                cur["last_sent"] = today
                if ok:
                    for d in due:
                        cur.get("counts", {}).pop(d, None)
                # keep at most 7 unsent days so the file can't grow without bound
                c = cur.get("counts", {})
                for d in sorted(c)[:-7]:
                    c.pop(d, None)
                _save(p, cur)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def record(tool: str, version: str) -> None:
    """Count one call. No-op unless LANTERN_TELEMETRY=1. Never raises."""
    if not enabled():
        return
    try:
        today = _today()
        with _lock:
            p = _state_path()
            state = _load(p)
            counts = state.setdefault("counts", {})
            day = counts.setdefault(today, {})
            key = f"{tool}|{version}"
            day[key] = int(day.get(key, 0)) + 1
            _save(p, state)
        _flush_due(state, today)
    except Exception:
        pass
