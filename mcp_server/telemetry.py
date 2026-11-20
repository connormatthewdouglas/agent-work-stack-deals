"""Opt-in, anonymous tool-call counter. OFF unless LANTERN_TELEMETRY=1.

What is sent (only when enabled and a collector URL is configured), at most once per UTC day:
    {"install_id": "<uuid>", "ref": "<LANTERN_REF or none>",
     "events": [{"t": "<tool name>", "v": "<package version>", "d": "YYYY-MM-DD", "n": <calls>}]}
Nothing else: no arguments, query text, results, IPs, names or hostnames. The install_id is a random
UUID generated locally the first time telemetry is on; it is not derived from the machine. The collector
stores aggregate counts and (when the id is a valid UUID) install rows; it does not store IPs. Public
/v1/stats returns aggregates only, never the raw install id.

Counts are kept in a small local file (``$XDG_CACHE_HOME/lantern-works-deals-mcp/telemetry.json``,
holding just {day: {tool|version: n}}) so a short-lived stdio process can batch a whole day. The
install id is stored separately at ``$XDG_CONFIG_HOME/lantern-works/install_id`` (mode 0600; deletable).
Completed days are sent in one background request with a short timeout. Any error is swallowed: telemetry
never blocks, slows or breaks a tool call. The install-id file is never created when telemetry is off.

Env:
    LANTERN_TELEMETRY=1            enable (anything else, or unset = disabled; no file, no network)
    LANTERN_TELEMETRY_URL=<url>    override the collector endpoint
    LANTERN_REF=<tag>              optional install source tag ([a-z0-9][a-z0-9_-]{0,31}); else none
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Empty until the collector is deployed: with no URL, enabling telemetry only counts locally.
DEFAULT_URL = "https://lantern-works-telemetry.lantern-works.workers.dev/v1/events"
TIMEOUT_S = 2.0
TOOLS = frozenset({"search_deals", "compare_deals", "get_deal", "compare_gpu_prices", "optimize_stack", "optimize_agent_stack"})
INSTALL_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
REF_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("LANTERN_TELEMETRY", "").strip() == "1"


def collector_url() -> str:
    return os.environ.get("LANTERN_TELEMETRY_URL", "").strip() or DEFAULT_URL


def _state_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "lantern-works-deals-mcp" / "telemetry.json"


def _install_id_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "lantern-works" / "install_id"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ref() -> str:
    raw = os.environ.get("LANTERN_REF", "").strip().lower()
    if REF_RE.fullmatch(raw):
        return raw
    return "other" if raw else "none"


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


def _get_or_create_install_id() -> str | None:
    """Return the local random install id, creating it once. Never raises. None on any error."""
    p = _install_id_path()
    try:
        if p.is_file():
            val = p.read_text(encoding="utf-8").strip().lower()
            if INSTALL_ID_RE.fullmatch(val):
                return val
        uid = str(uuid.UUID(bytes=secrets.token_bytes(16), version=4))
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, (uid + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp, p)
        os.chmod(p, 0o600)
        return uid
    except Exception:
        return None


def build_payload(counts: dict, install_id: str | None = None, ref: str | None = None) -> dict:
    """counts: {day: {"tool|version": n}} -> wire payload (t, v, d, n; optional install_id, ref)."""
    ev = []
    for day, per in sorted(counts.items()):
        for key, n in sorted(per.items()):
            tool, _, ver = key.partition("|")
            if tool in TOOLS and isinstance(n, int) and n > 0:
                ev.append({"t": tool, "v": ver, "d": day, "n": n})
    payload: dict = {"events": ev}
    if install_id:
        payload["install_id"] = install_id
    if ref:
        payload["ref"] = ref
    return payload


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
    payload = build_payload(due, _get_or_create_install_id(), _ref())

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
            _get_or_create_install_id()
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
