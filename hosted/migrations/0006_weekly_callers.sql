-- Stats DB (lantern-works-hosted-mcp-stats), additive only: privacy-safe weekly repeat-caller IDs.
-- Apply once (Mart): npx wrangler d1 execute lantern-works-hosted-mcp-stats --remote --file=migrations/0006_weekly_callers.sql
-- Then set the secret once: npx wrangler secret put CALLER_ID_SECRET
-- Redeploy the worker (hosted/deploy.sh). If the secret is unset, tracking is a no-op and requests never fail.
-- Rows are only (iso_week, hash, distinct UTC days seen). No raw IP, prefix, or client name.
CREATE TABLE IF NOT EXISTS weekly_callers (
  iso_week TEXT NOT NULL,
  h TEXT NOT NULL,
  days_seen TEXT NOT NULL,
  PRIMARY KEY (iso_week, h)
);
