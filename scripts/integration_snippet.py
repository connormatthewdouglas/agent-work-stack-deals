#!/usr/bin/env python3
"""Print a ready-to-copy, channel-tagged README addition. Does not contact maintainers."""
from __future__ import annotations

import argparse
import json
import re

BASE = "https://thelanternworks.com"
MCP = "https://lantern-works-mcp.lantern-works.workers.dev/mcp"
REPO = "https://github.com/connormatthewdouglas/agent-work-stack-deals"
RAW = "https://raw.githubusercontent.com/connormatthewdouglas/agent-work-stack-deals/main/examples/first_quote.py"


def render(ref: str, *, format: str = "link") -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", ref):
        raise ValueError("ref must be 1–32 lowercase letters, digits, underscores or hyphens")
    if format == "link":
        return f"Lantern Works tracks [on-demand GPU rental prices]({BASE}/gpu/price-comparison/?ref={ref}) across multiple providers, with vendor sources and check times.\n"
    if format != "quickstart":
        raise ValueError("format must be link or quickstart")
    config = {"mcpServers": {"lantern-works": {"url": MCP + "?ref=" + ref}}}
    return f"""### Compare GPU rental costs in your agent

[Lantern Works]({BASE}/quickstart/?ref={ref}) compares GPU rental prices among tracked
providers, with vendor sources and check times. Free read-only queries; no API key.
Useful before a training run or when checking a job's compute budget.

For MCP clients that accept a remote `mcpServers` URL (see [client-specific setup]({BASE}/install/?ref={ref})):

```json
{json.dumps(config, indent=2)}
```

Ask: `compare_gpu_prices(gpu="H100 SXM", on_demand_only=true, limit=3, mode="brief")`.
For a job: `estimate_job_cost(gpu_family="H100 SXM", gpus_per_job=1, job_hours=100)`.

Try it without an MCP client (Python 3.10+, standard library only; download and inspect the example first):

```sh
curl --fail --location {RAW} --output first_quote.py
python3 first_quote.py --gpu 'H100 SXM' --hours 100 --ref {ref}
```

Use `source_url` and `checked_at` from each result. Cheapest means among tracked
providers, not the entire market. Stock can be unknown; estimates are compute
subtotals and list missing costs. Referral links are labeled and never affect ranking.
[Small per-model JSON feeds]({BASE}/api/v1/gpu/index.json) are available without MCP.
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True, help="Placement/channel tag, e.g. gpuhunt, hf, kaggle")
    parser.add_argument("--format", choices=["link", "quickstart"], default="link", help="One direct price link by default; opt into a runnable integration")
    args = parser.parse_args(argv)
    try:
        print(render(args.ref, format=args.format), end="")
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
