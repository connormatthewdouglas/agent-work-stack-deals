"""Lantern Works hosted MCP endpoint (streamable HTTP, stateless JSON responses) on a free Cloudflare Python Worker.

Runs the SAME tool functions as the PyPI package: mcp_server/server.py is imported with a tiny FastMCP stand-in
that only records the decorated functions, and the feed loaders are fed the public JSON feeds fetched here.
Stored data: one aggregate counter per (UTC day, tool, ref channel). No IPs, user agents, request bodies or
any other per-caller data are read or stored. Exception, opt-in only: hosted price watches (watch_store.py) keep a
hashed api key, its webhook URL, optional contact email, the watches and per-key daily counts in a separate D1 DB.
"""
import inspect
import json
import re
import sys
import time
import types
import typing
from datetime import datetime, timezone

from workers import Response, WorkerEntrypoint, fetch

# --- FastMCP stand-in: records tools in declaration order -------------------------------------------------------
TOOLS = []


class _FastMCP:
    def __init__(self, name, instructions=None):
        self.name, self.instructions = name, instructions
        self._mcp_server = types.SimpleNamespace(version=None)

    def tool(self, annotations=None):
        def deco(fn):
            TOOLS.append((fn, annotations or {}))
            return fn
        return deco


for name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["mcp.server.fastmcp"].FastMCP = _FastMCP
_tel = types.ModuleType("mcp_server.telemetry")
_tel.record = lambda *a, **k: None  # hosted counts are kept below instead
sys.modules["mcp_server.telemetry"] = _tel

import core  # noqa: E402
from core import deals as core_deals  # noqa: E402
import mcp_server  # noqa: E402,F401
from mcp_server import server  # noqa: E402
import watch_store  # noqa: E402

PROTOCOL = "2025-06-18"
FEEDS = {"loader": core_deals.FEED_URL, "gpu_loader": core_deals.GPU_PRICES_URL,
         "history_loader": core_deals.GPU_HISTORY_URL, "changes_loader": core_deals.GPU_CHANGES_URL,
         "stack_loader": core_deals.STACK_PRICING_URL}
TTL = 600
_cache = {}
REF_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "content-type, authorization, mcp-protocol-version, mcp-session-id",
        "access-control-allow-methods": "GET, POST, OPTIONS"}


async def _feeds():
    now = time.time()
    for attr, url in FEEDS.items():
        hit = _cache.get(url)
        if hit and now - hit[0] < TTL:
            data = hit[1]
        else:
            r = await fetch(url, headers={"user-agent": core_deals.USER_AGENT + " hosted"})
            if r.status != 200:
                raise core_deals.DealError("upstream_unavailable", f"{url} returned HTTP {r.status}")
            data = json.loads(await r.text())
            _cache[url] = (now, data)
        ld = getattr(server, attr)
        ld.load = (lambda d: (lambda *a, **k: d))(data)


def _schema(fn):
    props, req = {}, []
    hints = typing.get_type_hints(fn)
    for p in inspect.signature(fn).parameters.values():
        t = hints.get(p.name, str)
        args = [a for a in typing.get_args(t) if a is not type(None)]
        base = args[0] if args else t
        js = {str: {"type": "string"}, int: {"type": "integer"}, float: {"type": "number"}, bool: {"type": "boolean"}}.get(base)
        if js is None:
            js = {"type": "array", "items": {"type": "string"}} if typing.get_origin(base) is list else {"type": "string"}
        if p.default is inspect.Parameter.empty:
            req.append(p.name)
        else:
            js = {**js, "default": p.default}
        props[p.name] = js
    return {"type": "object", "properties": props, **({"required": req} if req else {})}


def _tool_list():
    return [{"name": fn.__name__, "description": inspect.getdoc(fn) or "", "inputSchema": _schema(fn),
             **({"outputSchema": fn.output_schema} if getattr(fn, "output_schema", None) else {}),
             "annotations": ann} for fn, ann in TOOLS] + watch_store.tool_list()


async def _watch_feeds():
    await _feeds()
    return tuple(_cache[u][1] for u in (core_deals.GPU_PRICES_URL, core_deals.GPU_HISTORY_URL, core_deals.GPU_CHANGES_URL))


async def _count(env, tool, ref):
    day = datetime.now(timezone.utc).date().isoformat()
    try:
        await env.DB.prepare("INSERT INTO tool_calls(day, tool, ref, n) VALUES (?, ?, ?, 1) "
                             "ON CONFLICT(day, tool, ref) DO UPDATE SET n = n + 1").bind(day, tool, ref).run()
    except Exception:
        pass  # counting never breaks a call


def _ok(i, result):
    return {"jsonrpc": "2.0", "id": i, "result": result}


def _err(i, code, msg):
    return {"jsonrpc": "2.0", "id": i, "error": {"code": code, "message": msg}}


async def _handle(msg, env, ref, bearer=None):
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    i, m, p = msg.get("id"), msg["method"], msg.get("params") or {}
    if i is None:  # notification
        return None
    if m == "initialize":
        return _ok(i, {"protocolVersion": p.get("protocolVersion") or PROTOCOL if p.get("protocolVersion") in ("2025-03-26", "2025-06-18", "2025-11-25") else PROTOCOL,
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "lantern-works-deals", "title": "Lantern Works GPU Prices (hosted)", "version": core_deals.VERSION},
                       "instructions": server.INSTRUCTIONS})
    if m == "ping":
        return _ok(i, {})
    if m == "tools/list":
        return _ok(i, {"tools": _tool_list()})
    if m == "tools/call":
        name, args = p.get("name"), p.get("arguments") or {}
        if name in watch_store.NAMES:
            try:
                out = await watch_store.call(name, args, env, bearer, _watch_feeds)
            except core_deals.DealError as e:
                out = {"ok": False, "error": {"code": e.code, "message": e.message}}
            await _count(env, name, ref)
            return _ok(i, {"content": [{"type": "text", "text": json.dumps(out)}], "structuredContent": out, "isError": out.get("ok") is False})
        fn = next((f for f, _ in TOOLS if f.__name__ == name), None)
        if fn is None:
            return _err(i, -32602, f"Unknown tool: {name}")
        try:
            await _feeds()
            out = fn(**args)
        except TypeError as e:
            return _err(i, -32602, f"Invalid arguments: {e}")
        except core_deals.DealError as e:
            out = {"ok": False, "error": {"code": e.code, "message": e.message}}
        await _count(env, name, ref)
        is_err = isinstance(out, dict) and (out.get("ok") is False or ("error" in out and len(out) <= 2))
        return _ok(i, {"content": [{"type": "text", "text": json.dumps(out)}], "structuredContent": out, "isError": bool(is_err)})
    return _err(i, -32601, f"Method not found: {m}")


async def _stats(env):
    rows = (await env.DB.prepare("SELECT day, tool, ref, n FROM tool_calls ORDER BY day DESC, tool, ref LIMIT 2000").all()).results
    rows = [dict(day=r.day, tool=r.tool, ref=r.ref, n=r.n) for r in rows]
    return rows


def _stats_html(rows):
    tot = {}
    for r in rows:
        tot[r["tool"]] = tot.get(r["tool"], 0) + r["n"]
    trs = "".join(f"<tr><td>{r['day']}</td><td>{r['tool']}</td><td>{r['ref']}</td><td>{r['n']}</td></tr>" for r in rows)
    tt = "".join(f"<li><code>{k}</code>: {v}</li>" for k, v in sorted(tot.items(), key=lambda x: -x[1]))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lantern Works hosted MCP: public call counts</title><style>body{{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem}}td,th{{border-bottom:1px solid #ddd;padding:.3rem .6rem;text-align:left}}</style>
<h1>Hosted MCP endpoint: tool calls per day</h1>
<p>Anonymous aggregate counts only: one counter per UTC day, tool and <code>?ref=</code> channel tag. No IP addresses, user agents, arguments or any per-caller data are stored. Machine-readable: <a href="/stats.json">/stats.json</a>. Endpoint: <code>/mcp</code>. Source: <a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/hosted">hosted/</a>.</p>
<h2>Totals</h2><ul>{tt or '<li>No calls yet.</li>'}</ul>
<h2>By day</h2><table><tr><th>Day (UTC)</th><th>Tool</th><th>Ref</th><th>Calls</th></tr>{trs}</table></html>"""


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = request.url
        path = re.sub(r"^https?://[^/]+", "", url).split("?")[0]
        q = url.split("?", 1)[1] if "?" in url else ""
        ref = next((v for k, _, v in (x.partition("=") for x in q.split("&")) if k == "ref"), "") .lower()
        ref = ref if REF_RE.match(ref) else ("none" if not ref else "other")
        if request.method == "OPTIONS":
            return Response("", status=204, headers=CORS)
        if path in ("/stats", "/stats/"):
            return Response(_stats_html(await _stats(self.env)), headers={"content-type": "text/html; charset=utf-8", **CORS})
        if path == "/stats.json":
            return Response(json.dumps({"schema": "lantern-works-hosted-mcp-stats/1", "note": "anonymous aggregate counts per UTC day, tool and ref; nothing per caller is stored",
                                        "rows": await _stats(self.env), "watches": await watch_store.stats(self.env)}), headers={"content-type": "application/json", **CORS})
        if path in ("/mcp", "/mcp/"):
            if request.method == "GET":
                return Response("Lantern Works MCP endpoint (streamable HTTP, POST JSON-RPC). Server-sent event streams are not offered; use POST.",
                                status=405, headers={"allow": "POST", **CORS})
            if request.method == "DELETE":
                return Response("", status=405, headers=CORS)
            try:
                body = json.loads(await request.text())
            except Exception:
                return Response(json.dumps(_err(None, -32700, "Parse error")), status=400, headers={"content-type": "application/json", **CORS})
            auth = request.headers.get("authorization") or ""
            bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else None
            if isinstance(body, list):
                out = [r for r in [await _handle(x, self.env, ref, bearer) for x in body] if r is not None]
                return Response(json.dumps(out) if out else "", status=200 if out else 202, headers={"content-type": "application/json", **CORS})
            r = await _handle(body, self.env, ref, bearer)
            if r is None:
                return Response("", status=202, headers=CORS)
            return Response(json.dumps(r), headers={"content-type": "application/json", **CORS})
        if path == "/":
            return Response("Lantern Works hosted MCP endpoint. POST JSON-RPC to /mcp (streamable HTTP). Public counts: /stats. Docs: https://thelanternworks.com/install/\n",
                            headers={"content-type": "text/plain; charset=utf-8", **CORS})
        return Response("not found\n", status=404, headers=CORS)

    async def scheduled(self, controller, env=None, ctx=None):
        """Cron (wrangler.toml [triggers]): deliver signed price-watch alerts after the daily feed refresh."""
        await watch_store.run_cron(env or self.env, _watch_feeds, fetch)
