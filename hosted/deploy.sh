#!/bin/sh
# Worker-only deploy: build, deploy, wait until the live /version matches this commit,
# then the same live checks CI runs after a Pages deploy.
# Usage: sh hosted/deploy.sh   (needs wrangler auth; CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID in CI)
set -e
cd "$(dirname "$0")"
sh build.sh
npx --yes wrangler deploy
VER=$(sed -n 's/^version = "\(.*\)"/\1/p' ../pyproject.toml)
SHA=$(git rev-parse HEAD)
python3 ../scripts/check_hosted_version.py --version "$VER" --build "$SHA"
python3 ../scripts/check_benchmark_asset.py --hosted
python3 ../scripts/check_error_contract.py --hosted
