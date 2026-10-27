# Telemetry collector (Cloudflare Worker, free plan)

Receives opt-in, anonymous tool-call counts from `lantern-works-deals-mcp` (see [../PRIVACY.md](../PRIVACY.md)). It stores only aggregate counts per (day, tool, version) in D1, never IPs or IDs, and has request logs disabled.

- `POST /v1/events`: `{"events":[{"t","v","d","n"}]}`. Requests must match exactly: up to 50 events, known tools, an `x.y.z` version, a day from yesterday back to 8 days ago, and counts of 1–10000. The body is limited to 4 KB and rate-limited to 30 requests/min per client. The limiter keys on a hash held in memory, never stored. Returns 204.
- `GET /v1/stats?days=30`: read-only aggregate totals.

## Deploy (free plan; no card)

```bash
cd collector
npx wrangler login                     # or CLOUDFLARE_API_TOKEN with Workers + D1 edit
npx wrangler d1 create lantern-works-telemetry   # paste database_id into wrangler.toml
npx wrangler d1 execute lantern-works-telemetry --remote --file schema.sql
npx wrangler deploy
```

Test: `node --test test/`.
