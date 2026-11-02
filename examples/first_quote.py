#!/usr/bin/env python3
"""Get a cited GPU comparison without installing a package (Python 3.10+).

Purpose-built example for Lantern Works, not a general MCP SDK. Uses the MCP
2025-06-18 lifecycle and supports JSON and finite SSE POST responses.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://lantern-works-mcp.lantern-works.workers.dev/mcp"
PROTOCOL = "2025-06-18"
MAX_BYTES = 2_000_000
REF_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")


class QuoteError(Exception):
    """An unsuccessful call; never printed as a valid quote."""


def endpoint_with_ref(endpoint: str, ref: str) -> str:
    if not REF_RE.fullmatch(ref):
        raise ValueError("ref must be 1–32 lowercase letters, digits, underscores or hyphens")
    parts = urllib.parse.urlsplit(endpoint)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "ref"]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query + [("ref", ref)])))


def read_response(response, request_id: int) -> dict:
    media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if media_type == "application/json":
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise QuoteError("MCP response exceeded 2 MB")
        message = json.loads(body)
    elif media_type == "text/event-stream":
        data, size = [], 0
        message = None
        for raw in response:
            size += len(raw)
            if size > MAX_BYTES:
                raise QuoteError("MCP event stream exceeded 2 MB")
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
            elif not line and data:
                event = json.loads("\n".join(data))
                data = []
                if isinstance(event, dict) and event.get("id") == request_id:
                    message = event
                    break
        if message is None:
            raise QuoteError("MCP stream ended without the requested response")
    else:
        raise QuoteError(f"Unsupported MCP response type: {media_type or 'missing'}")
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or message.get("id") != request_id:
        raise QuoteError("MCP response has an unexpected request id or shape")
    if "error" in message:
        raise QuoteError("MCP protocol error: " + json.dumps(message["error"]))
    if not isinstance(message.get("result"), dict):
        raise QuoteError("MCP response is missing its result")
    return message["result"]


class Client:
    def __init__(self, endpoint: str, user_agent: str = "lantern-works-first-quote/1.0"):
        self.endpoint = endpoint
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                        "User-Agent": user_agent}
        self.request_id = 0

    def post(self, method: str, params: dict | None = None, *, notification: bool = False):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.request_id += 1
            message["id"] = self.request_id
        request = urllib.request.Request(self.endpoint, data=json.dumps(message).encode(), headers=self.headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            session = response.headers.get("Mcp-Session-Id")
            if method == "initialize" and session:
                self.headers["Mcp-Session-Id"] = session
            if notification:
                if response.status != 202:
                    raise QuoteError(f"MCP notification returned HTTP {response.status}, expected 202")
                return None
            return read_response(response, self.request_id)

    def initialize(self):
        result = self.post("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                           "clientInfo": {"name": "lantern-works-first-quote", "version": "1.0"}})
        if result.get("protocolVersion") != PROTOCOL:
            raise QuoteError("Server negotiated an unsupported MCP protocol version")
        if "tools" not in result.get("capabilities", {}):
            raise QuoteError("Server does not advertise tools")
        self.headers["MCP-Protocol-Version"] = PROTOCOL
        self.post("notifications/initialized", notification=True)
        return result

    def call(self, name: str, arguments: dict) -> dict:
        result = self.post("tools/call", {"name": name, "arguments": arguments})
        payload = result.get("structuredContent")
        if not isinstance(payload, dict):
            payload = next((json.loads(c["text"]) for c in result.get("content", [])
                            if c.get("type") == "text"), None)
        if result.get("isError") or not isinstance(payload, dict) or payload.get("ok") is not True:
            error = payload.get("error") if isinstance(payload, dict) else "Missing structured result"
            raise QuoteError("GPU quote failed: " + json.dumps(error))
        return payload


def positive_hours(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("hours must be a positive finite number")
    return number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", default="H100 SXM", help="Exact variant is best, e.g. H100 SXM or A100 PCIe")
    parser.add_argument("--hours", type=positive_hours, help="Also estimate a job's compute subtotal, with a receipt")
    parser.add_argument("--gpus", type=int, default=1, choices=range(1, 129), metavar="1..128")
    parser.add_argument("--ref", default="first-quote", help="Channel tag; use house-* or qa for internal tests")
    parser.add_argument("--qa", action="store_true", help="Use an internal ref and QA user agent")
    args = parser.parse_args(argv)
    try:
        endpoint = endpoint_with_ref(ENDPOINT, "house-first-quote" if args.qa else args.ref)
        client = Client(endpoint, "lantern-works-qa/1.0" if args.qa else "lantern-works-first-quote/1.0")
        info = client.initialize()
        comparison = client.call("compare_gpu_prices", {"gpu": args.gpu, "limit": 3, "on_demand_only": True,
                                                       "max_data_age_hours": 24, "mode": "brief"})
        output = {"server": info["serverInfo"], "comparison": comparison}
        if args.hours is not None:
            output["job"] = client.call("estimate_job_cost", {"gpu_family": args.gpu, "gpus_per_job": args.gpus,
                                        "job_hours": args.hours, "top_n": 3, "max_data_age_hours": 24, "mode": "full"})
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0
    except (QuoteError, ValueError, KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"No quote: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
