# Usage measurement (T51)

The hosted worker (`https://lantern-works-mcp.lantern-works.workers.dev`) keeps anonymous daily counters. They are public at `/stats.json` under `hits`.

- **Key:** UTC day × kind (`feed`, `tool`, `initialize`) × path or tool name (or the MCP `clientInfo.name` for `initialize`) × `ref` × `ua_class` × `src_class`.
- **Not stored:** no IP address, user agent, arguments or per-caller identifier. The IP is only tested against GitHub's published Actions ranges (`src_class`), which are baked into the bundle on each deploy from api.github.com/meta.
- **Retention:** at least 90 days; rows older than 120 days are pruned.
- **Distinct callers (`callers_daily`, `callers` in `/stats.json`):** privacy: only a daily-salted SHA-256 hash of IP + user agent is kept (the random salt lives in D1 for its UTC day only, then is deleted, and is never logged or returned); the raw IP and user agent are never stored. Counts are per UTC day × kind (`feed`, `mcp`) × `ref` × `ua_class` × `src_class`; house traffic (`src_class=house` or a house `ref` such as `ci`, `qa`, `test`, `smoke`, `house-*`, `t<N>`) is not counted.
- **Demand counts (`demand_daily` in hosted and site `/stats.json`, P8):** for hosted GPU tool calls (`compare_gpu_prices`, `estimate_job_cost`, `optimize_agent_stack`), totals per UTC day × tool × GPU family × region group × price tier × cheapest provider. The GPU family and region group are bucketed to fixed lists, and anything else is stored as `other`. The price tier and provider describe the first result in our own answer. These rows do not include an IP address, the raw user agent, a caller hash, the tool arguments or any free text. Kept for 120 days. House and CI traffic and known bots are not counted.
- **ua_class:** `house` (lantern-works-gauge, lantern-works-qa, lantern-works-t41), `ci` (lantern-works-ci), `known-bot`, `mcp:<client>` (for example `mcp:lantern-works-pypi`, `mcp:claude`, `mcp:cursor`, `mcp:python-sdk`, `mcp:node`), `browser` or `other`.
- **src_class:** `house` (house or CI user agent), `github-actions` (the IP is in GitHub's Actions ranges) or `other`.

## Feeds through the worker

`GET /api/v1/<file>.json` and `/deals.json` on the worker return the same bytes as the site and are counted. They accept an optional `?ref=<tag>` (`[a-z0-9_-]`, max 32). Only 200 responses are counted, so unknown paths can't grow the table. Tool rows use known tool names only. `initialize` rows use a fixed client vocabulary: `mcp:*`, `other` or `none`.

Fetches straight from thelanternworks.com (GitHub Pages) cannot be counted, because Pages has no request logs.

## Per-key activity

When a pricing tool is called with an opt-in watch key (`Authorization: Bearer` or `api_key`), the key's weekly `pricing_calls` appear in `watches.weekly_per_key`. The key is shown only as an HMAC label. A missing or bad key never fails the pricing call.

## Tag your own traffic (house, never counted as outside use)

| Who | ref | User-Agent |
|---|---|---|
| CI (GitHub Actions) | `ref=ci` | `lantern-works-ci` |
| Mart QA scripts, including MCP python-sdk (`streamablehttp_client(url + "?ref=qa", headers={"User-Agent": "lantern-works-qa"})`) | `ref=qa` | `lantern-works-qa` |
| T41 release gate (live mode reads `/api/v1/*.json` through the worker) | `ref=t41` | `lantern-works-ci/1 (T41 release gate; ref=t41)` |
| Gauge's scripts | `ref=qa` or `ref=t41` | `lantern-works-gauge` (please set this in your own scripts) |

## User agents of our own clients

- **PyPI client:** `lantern-works-deals-mcp/<version> (pypi-client)`.
- **Hosted worker's fetches:** `lantern-works-deals-mcp/<version> (hosted-worker)`.

## Outbound links

Links to vendors on the site get `utm_source=lanternworks` at click time, unless the link already has a `utm_source`. The feeds, and `deals.json` in particular, are unchanged.
