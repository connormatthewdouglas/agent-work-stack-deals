#!/usr/bin/env python3
"""Overall CI verdict for validate-and-deploy (Gauge rel053: run 41473330377 reported success with tests and
latest-scout-import failed and deploy skipped, because those jobs use continue-on-error).
Reads NEEDS_JSON (toJSON(needs)) and EVENT; exits 1 when the run must be red."""
import json, os, sys

REQUIRED_OK = ("validate", "tests", "latest-scout-import", "release-gate")
OPTIONAL_OK = ("pypi-install", "docker")  # may be skipped on data-only runs, never 'false'


def problems(needs: dict, event: str, ref: str = "refs/heads/main") -> list[str]:
    out = []
    for j in REQUIRED_OK:
        n = needs.get(j) or {}
        if n.get("result") != "success" or (n.get("outputs") or {}).get("ok") != "true":
            out.append(f"{j}: result={n.get('result')} ok={(n.get('outputs') or {}).get('ok')}")
    for j in OPTIONAL_OK:
        n = needs.get(j) or {}
        if n.get("result") == "failure" or (n.get("outputs") or {}).get("ok") == "false":
            out.append(f"{j}: result={n.get('result')} ok={(n.get('outputs') or {}).get('ok')}")
    if event in ("push", "workflow_dispatch") and ref == "refs/heads/main":
        d = needs.get("deploy") or {}
        dep = (d.get("outputs") or {}).get("deployed")
        if dep != "superseded":
            if d.get("result") != "success" or dep != "true":
                out.append(f"deploy: result={d.get('result')} deployed={dep}")
            lc = needs.get("live-checks") or {}
            if lc.get("result") != "success" or (lc.get("outputs") or {}).get("ok") == "false":
                out.append(f"live-checks: result={lc.get('result')}")
    return out


def main() -> int:
    p = problems(json.loads(os.environ["NEEDS_JSON"]), os.environ.get("EVENT", ""), os.environ.get("REF", "refs/heads/main"))
    for x in p:
        print(f"::error title=CI gate::{x}")
    print("ci-status: " + ("FAIL" if p else "ok"))
    return 1 if p else 0


if __name__ == "__main__":
    sys.exit(main())
