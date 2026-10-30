"""T43 artifact/deployment check: the shipped product (not the source checkout) prices a published-benchmark job.

  python3 scripts/check_benchmark_asset.py --installed   # run with an interpreter where the wheel is installed;
                                                          # executes from a temp dir so the checkout is never imported
  python3 scripts/check_benchmark_asset.py --hosted [URL] # the deployed HTTP MCP endpoint

Cases: H100 SXM 80GB / resnet50, work_units=1,000,000, no throughput -> ok, throughput_basis=published_benchmark;
an unsupported training workload -> ok=false, code not_found, message 'missing: throughput' (abstains usefully).
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=ci"
GOOD = {"gpu_family": "H100 SXM 80GB", "gpus_per_job": 1, "workload": "resnet50", "work_units": 1000000}
TRAIN = {"gpu_family": "H100 SXM 80GB", "gpus_per_job": 1, "workload": "llama 3 70b fine-tuning", "work_units": 1000000}
INSTALLED = r'''
import json, sys
from lantern_works_deals_mcp import server
from lantern_works_deals_mcp.core import throughput
assert "site-packages" in throughput.__file__ or "dist-packages" in throughput.__file__, throughput.__file__
print(json.dumps({"asset": throughput.asset_info(), "good": server.estimate_job_cost(**json.loads(sys.argv[1])),
                  "train": server.estimate_job_cost(**json.loads(sys.argv[2]))}))
'''


def judge(good, train, asset=None):
    errs = []
    if good.get("ok") is not True or good.get("throughput_basis") != "published_benchmark" or not good.get("results"):
        errs.append(f"resnet50 case did not price from the published benchmark: {json.dumps(good)[:300]}")
    e = train.get("error") or {}
    if train.get("ok") is not False or e.get("code") != "not_found" or "missing: throughput" not in e.get("message", ""):
        errs.append(f"training case did not abstain with not_found/missing throughput: {json.dumps(train)[:300]}")
    if asset is not None and not asset.get("figures"):
        errs.append(f"benchmark asset empty: {asset}")
    return errs


def call(url, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "estimate_job_cost", "arguments": args}})
    req = urllib.request.Request(url, body.encode(), {"content-type": "application/json", "accept": "application/json, text/event-stream",
                                                     "user-agent": "lantern-works-ci"})
    res = json.load(urllib.request.urlopen(req, timeout=60))["result"]
    return res["structuredContent"], res.get("isError")


def main():
    if "--hosted" in sys.argv:
        url = next((a for a in sys.argv[1:] if a.startswith("http")), HOSTED)
        (good, gerr), (train, terr) = call(url, GOOD), call(url, TRAIN)
        errs = judge(good, train) + ([] if (gerr, terr) == (False, True) else [f"isError good={gerr} train={terr}"])
        asset = None
    else:
        with tempfile.TemporaryDirectory() as d:  # outside the source checkout
            p = subprocess.run([sys.executable, "-c", INSTALLED, json.dumps(GOOD), json.dumps(TRAIN)], cwd=d,
                               capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""}, timeout=120)
        if p.returncode:
            print(p.stderr[-2000:]); sys.exit("FAIL: installed package check crashed")
        out = json.loads(p.stdout.strip().splitlines()[-1])
        good, train, asset = out["good"], out["train"], out["asset"]
        errs = judge(good, train, asset)
    for e in errs:
        print("FAIL:", e)
    if errs:
        sys.exit(1)
    print(f"BENCHMARK_ASSET_OK ({'hosted' if asset is None else 'installed, ' + str(asset['figures']) + ' figures'}): "
          f"H100 SXM 80GB resnet50 1e6 samples -> {good['job_hours']:.4g} h, cheapest ${good['results'][0]['compute_subtotal_usd']}")


if __name__ == "__main__":
    main()
