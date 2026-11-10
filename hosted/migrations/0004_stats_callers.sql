-- Stats DB (lantern-works-hosted-mcp-stats), additive only: anonymized distinct-caller counting.
-- Apply once: npx wrangler d1 execute lantern-works-hosted-mcp-stats --remote --file=migrations/0004_stats_callers.sql
-- caller_salts holds one random salt per UTC day; the worker deletes past days' salts. callers holds only sha256(salt|ip|ua).
CREATE TABLE IF NOT EXISTS caller_salts (day TEXT PRIMARY KEY, salt TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS callers (day TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, ua_class TEXT NOT NULL, src_class TEXT NOT NULL, h TEXT NOT NULL, PRIMARY KEY (day, kind, ref, ua_class, src_class, h));
