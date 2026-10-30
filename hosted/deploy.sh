#!/bin/sh
# Worker-only deploy (no CI run): build, deploy, then the same live checks CI runs after a Pages deploy.
# Usage: sh hosted/deploy.sh   (needs wrangler auth; node_modules linked by the caller)
set -e
cd "$(dirname "$0")"
sh build.sh
npx wrangler deploy
sleep 10   # propagation
python3 ../scripts/check_benchmark_asset.py --hosted
python3 ../scripts/check_error_contract.py --hosted
