# Telemetry collector (Cloudflare Worker, free plan)

Receives opt-in, anonymous tool-call counts from `lantern-works-deals-mcp` (see [../PRIVACY.md](../PRIVACY.md)). It stores aggregate counts per (day, tool, version) and, when a valid UUID `install_id` is sent, install rows per (day, install_id, ref, tool, version) in D1. IPs, names and hostnames are never stored. Public `/v1/stats` returns aggregates only (no raw install ids). Request logs are disabled.

- `POST /v1/events`: `{"install_id","ref","events":[{"t","v","d","n"}]}`. `install_id` and `ref` are optional (legacy clients omit them). Events must match exactly: up to 50 events, known tools, an `x.y.z` version, a day from yesterday back to 8 days ago, and counts of 1–10000. An `install_id` must be a 36-character UUID; anything else is ignored and not stored. `ref` is a `[a-z0-9][a-z0-9_-]{0,31}` tag, or `other`/`none`. The body is limited to 4 KB and rate-limited to 30 requests/min per client. The limiter keys on a hash held in memory, never stored. Returns 204.
- `GET /v1/stats?days=30`: read-only aggregate totals, including `installs.distinct`, `installs.returning` (an install id seen on two or more distinct UTC days in the stats window) and `installs.by_ref` / `installs.by_week`. Raw install ids are never published.

## Deploy (free plan; no card)

```bash
cd collector
npx wrangler login                     # or CLOUDFLARE_API_TOKEN with Workers + D1 edit
npx wrangler d1 create lantern-works-telemetry   # paste database_id into wrangler.toml
npx wrangler d1 execute lantern-works-telemetry --remote --file schema.sql
# existing DB (additive): npx wrangler d1 execute lantern-works-telemetry --remote --file=migrations/0001_installs.sql
npx wrangler deploy
```

Test: `node --test test/`.
