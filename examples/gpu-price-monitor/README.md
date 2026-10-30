# GPU price monitor (price-drop alerts)

Zero-dependency Python script. It reads the Lantern Works price history API
(`https://thelanternworks.com/api/v1/gpu-prices/history.json`, built from daily price snapshots) and prints an
`ALERT` line when a tracked rate's latest ranked price is at least `--drop` percent below its previous ranked price.
It also stores a local baseline (`~/.lantern_gpu_baseline.json`), so a drop between two of your own runs is caught even
when the history only has one snapshot. Exit code is `2` when any alert fired, otherwise `0`.

```bash
python monitor.py --gpu H100 --drop 10            # live history API
python monitor.py --history history.json --drop 5 # local file
```

Each line shows `verified_at`, the UTC time the rate was last checked against the vendor page. Prices cover tracked
providers only and exclude storage, egress and taxes. Confirm on the vendor page before spending.

From an MCP client, `compare_gpu_prices` with `include_history: true` (MCP server 0.3.4 and later; 0.3.41 current; `get_price_changes` from 0.3.7) returns the same
change points (`price_history`, `history.recent_changes`). Note: some MCP results include referral links
(`affiliate: true`, `redeem_url`). The history API used here contains no links.

Cron example: `0 9 * * * python monitor.py --gpu H100 --drop 10 || notify-send "GPU price drop"`.
