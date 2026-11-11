# Privacy and telemetry

## MCP server (`lantern-works-deals-mcp`)

**Telemetry is off by default.** With nothing set, the server sends no telemetry and writes no telemetry file. Its only network requests fetch the public feeds (`/api/v1/*.json`) with `User-Agent: lantern-works-deals-mcp/<version>`.

### Opt-in tool-call counter

Set `LANTERN_TELEMETRY=1` to help us see which tools are used. It is enabled only when the value is exactly `1`.

**What is sent:** only aggregate counts, at most once per UTC day, in one request:

```json
{"events": [{"t": "compare_gpu_prices", "v": "0.3.3", "d": "2026-10-28", "n": 4}]}
```

- `t` is the tool name, `v` the package version, `d` the UTC day and `n` the number of calls that day.

**What is never sent:**
- tool arguments, queries or results
- user, host, client or install identifiers
- environment details

**Local file:** counts are kept in `~/.cache/lantern-works-deals-mcp/telemetry.json` (or under `$XDG_CACHE_HOME`) until the day is over. The file contains only `{day: {tool|version: count}}` and at most 7 unsent days.

**Failure handling:** the request runs in the background with a 2-second timeout. Failures are ignored, so a tool call is never blocked or broken.

**Collector:** the server code is in [`collector/`](collector/), a Cloudflare Worker with a D1 database.
- It validates the payload: only the fields above, known tool names, version numbers and recent days are accepted.
- Requests are rate-limited. The limiter uses an in-memory hash, and IPs are never written to storage.
- It stores only the total per `(day, tool, version)`, with no request logs.
- Aggregate totals are public at `GET /v1/stats`.

**Configuration:**
- `LANTERN_TELEMETRY_URL` overrides the collector address.
- Endpoint (0.3.3 and later): `https://lantern-works-telemetry.lantern-works.workers.dev/v1/events`. Public aggregate stats: `https://lantern-works-telemetry.lantern-works.workers.dev/v1/stats`. Versions before 0.3.3 send nothing.

To turn it off, unset `LANTERN_TELEMETRY` or set it to anything other than `1`. You can delete the cache file at any time.

## Hosted MCP endpoint

The hosted worker at `https://lantern-works-mcp.lantern-works.workers.dev` keeps anonymous daily counters, public at `/stats.json`.

- **Call counts (`hits`):** totals per UTC day × kind × path or tool × `ref` × `ua_class` × `src_class`. These rows do not include an IP address or the raw user agent.
- **Distinct callers (`callers_daily`, `callers`):** for `/mcp` POSTs and successful feed fetches, the worker stores only a daily-salted SHA-256 hash of the IP address and user agent (`sha256(salt | IP | user-agent)`), plus the same coarse buckets. The raw IP and user agent are never stored, logged or returned. A random salt is created for each UTC day and deleted when that day ends, so hashes from different days cannot be linked. Hashes are kept for 120 days, then deleted. House and CI traffic is not counted. See [`docs/MEASUREMENT.md`](docs/MEASUREMENT.md).
- **Demand counts (`demand_daily`):** for hosted GPU tool calls (`compare_gpu_prices`, `estimate_job_cost`, `optimize_agent_stack`), totals per UTC day × tool × GPU family × region group × price tier × cheapest provider. The GPU family and region group are bucketed to fixed lists, and anything else is stored as `other`. The price tier and provider describe the first result in our own answer. These rows do not include an IP address, the raw user agent, a caller hash, the tool arguments or any free text. Kept for 120 days. House and CI traffic and known bots are not counted.
- **Opt-in price watches:** if you create a watch key, the worker stores a hash of the key, the webhook URL, an optional email, your watches and per-key daily counts. Call arguments are not stored.

## Website

The site uses Cloudflare Web Analytics for page views; it sets no cookies. Clicks on search, compare, calculator and outbound links are counted as virtual page views under `/e/...`. Deal links (and the `tracked_url` field in the feed and MCP results) go through a `/go/<deal-id>` redirect on the telemetry worker, which adds one to an aggregate counter per UTC day, deal, provider, `src` and `?ref=` tag, then redirects to that deal's listed `redeem_url`. No IP address, cookie, user agent or other identifier is stored.
