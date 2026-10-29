# GPU price watcher: what moved since a date

A small script that calls `get_price_changes` on the Lantern Works MCP server (`uvx lantern-works-deals-mcp`, 0.3.8+)
over stdio with the official `mcp` Python SDK and prints every tracked GPU rental price move since a date, each
with the vendor `source_url`. No API key and no LLM.

```bash
uv venv -p 3.12 .venv && . .venv/bin/activate
uv pip install -r requirements.txt            # uv/uvx must be on PATH
python watch_prices.py 2026-10-21             # every move on or after that date
python watch_prices.py --gpu H100 --limit 3   # latest day's moves, H100 only
python watch_prices.py 2026-10-21 --json      # full tool result
```

Sample cron line (prices refresh daily at about 10:23 UTC; this runs at 11:00 UTC and shows yesterday's moves):

```cron
0 11 * * * cd /path/to/gpu-price-watcher && .venv/bin/python watch_prices.py "$(date -u -d yesterday +\%F)" >> moves.log 2>&1
```

(`date -d` is GNU; on macOS use `date -u -v-1d +\%F`.)

## Real output (lantern-works-deals-mcp 0.3.8 from PyPI, run 2026-10-28 8:07 PM ET)

```text
$ python watch_prices.py 2026-10-21
2 tracked GPU price change(s) between 2026-10-21 and 2026-10-28: 1 down, 1 up, 0 newly tracked, 0 no longer tracked.
data checked: 2026-10-28  next refresh: 2026-10-29T10:23:00Z
  2026-10-28 Vast.ai A100 SXM [Marketplace on-demand (verified; median per GPU)]: $1.3389 -> $1.1378/hr (-15.0%, down)
    source: https://console.vast.ai/api/v0/bundles/?q=%7B%22gpu_name%22%3A%7B%22eq%22%3A%22A100%20SXM4%22%7D%2C%22rentable%22%3A%7B%22eq%22%3Atrue%7D%2C%22rented%22%3A%7B%22eq%22%3Afalse%7D%2C%22verified%22%3A%7B%22eq%22%3Atrue%7D%2C%22type%22%3A%22on-demand%22%2C%22limit%22%3A1000%7D
  2026-10-28 Vast.ai RTX 4090 [Marketplace on-demand (verified; median per GPU)]: $0.5022 -> $0.5175/hr (+3.0%, up)
    source: https://console.vast.ai/api/v0/bundles/?q=%7B%22gpu_name%22%3A%7B%22eq%22%3A%22RTX%204090%22%7D%2C%22rentable%22%3A%7B%22eq%22%3Atrue%7D%2C%22rented%22%3A%7B%22eq%22%3Afalse%7D%2C%22verified%22%3A%7B%22eq%22%3Atrue%7D%2C%22type%22%3A%22on-demand%22%2C%22limit%22%3A1000%7D

$ python watch_prices.py --gpu H100 --limit 3
5 tracked GPU price change(s) for 'H100' between 2026-10-27 and 2026-10-28: 0 down, 0 up, 5 newly tracked, 0 no longer tracked.
data checked: 2026-10-28T16:43:09Z  next refresh: 2026-10-29T10:23:00Z
  2026-10-28 CoreWeave H100 [On-demand, 8-GPU instance]: newly tracked at $6.155/hr
    source: https://www.coreweave.com/pricing
  2026-10-28 DigitalOcean GPU Droplets H100 [On-demand]: newly tracked at $4.41/hr
    source: https://www.digitalocean.com/pricing/gpu-droplets
  2026-10-28 Nebius H100 [On-demand]: newly tracked at $4.5/hr
    source: https://nebius.com/prices
```

Notes: history starts 2026-10-27, so earlier dates return moves from then on. "newly tracked" means a rate first
tracked in the window, with no earlier price to compare. With a date, `data_checked_at` is the newest daily snapshot
date; without one it is the newest `verified_at` time. Results cover tracked providers only (not the whole market).
Prices are per GPU-hour in USD and exclude storage, egress and taxes. Confirm on the vendor page before spending.
Other tools on the same server can return referral links (`affiliate: true`, labeled in results); affiliate status is
not a ranking factor.
