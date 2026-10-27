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
- Until a collector address ships in a release, enabling telemetry only counts locally and sends nothing.

To turn it off, unset `LANTERN_TELEMETRY` or set it to anything other than `1`. You can delete the cache file at any time.

## Website

The site uses Cloudflare Web Analytics for page views; it sets no cookies. Clicks on search, compare, calculator and outbound links are counted as virtual page views under `/e/...`.
