#!/bin/sh
# Copy the package's core + server into the worker bundle (same code as PyPI), then deploy with wrangler.
set -e
cd "$(dirname "$0")"
rm -rf src/core src/mcp_server
mkdir -p src/mcp_server
cp -r ../core src/core && rm -rf src/core/__pycache__
cp ../mcp_server/server.py src/mcp_server/server.py && : > src/mcp_server/__init__.py
python3 gen_gha_ranges.py  # T51 src_class: GitHub Actions runner ranges (regenerated on every deploy)
