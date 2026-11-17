#!/usr/bin/env python3
"""Poll the live hosted Worker /version until it matches the deploy, then exit 0.

Used by hosted/deploy.sh after wrangler deploy. A build must be a hex prefix of at least 7
characters of the commit that was just deployed. Times out instead of passing on an old build.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request

URL = "https://lantern-works-mcp.lantern-works.workers.dev/version"
HEX = re.compile(r"^[0-9a-f]{7,}$")


def versions_match(payload: dict, version: str, sha: str) -> bool:
    if not isinstance(payload, dict) or payload.get("version") != version:
        return False
    got = str(payload.get("build") or "").strip().lower()
    want = sha.strip().lower()
    if not HEX.fullmatch(got) or not HEX.fullmatch(want):
        return False
    return want.startswith(got) or got.startswith(want)


def poll_version(fetch, version: str, sha: str, *, timeout_s: float = 180, interval_s: float = 10,
                 sleep=time.sleep, now=time.monotonic) -> dict:
    """Call fetch() until versions_match or timeout_s elapses. fetch raises or returns a JSON object."""
    deadline = now() + timeout_s
    last = None
    while True:
        try:
            last = fetch()
        except Exception as e:  # noqa: BLE001  (propagation; keep polling until the timeout)
            last = {"error": f"{type(e).__name__}: {e}"}
        if isinstance(last, dict) and versions_match(last, version, sha):
            return last
        if now() >= deadline:
            raise SystemExit(f"hosted /version did not match version {version} build {sha[:12]} "
                             f"within {timeout_s:.0f}s; last={last}")
        sleep(interval_s)


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "LanternWorks-hosted-deploy", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--build", required=True)
    ap.add_argument("--url", default=URL)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--interval", type=float, default=10)
    a = ap.parse_args(argv)
    found = poll_version(lambda: _fetch(a.url), a.version, a.build, timeout_s=a.timeout, interval_s=a.interval)
    print(f"hosted /version matches {found.get('version')} {found.get('build')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
