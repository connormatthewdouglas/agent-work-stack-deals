-- F1 poll-only price alerts (Brain #1028). Watches D1 (lantern-works-hosted-watches, binding WATCH_DB). Additive.
-- Apply once, remote (Mart's deploy flow):
--   npx wrangler d1 execute lantern-works-hosted-watches --remote --file=migrations/0008_price_alerts.sql
-- Stored: a hash of the alert token, the alert filter and threshold, and counters. No email, webhook URL, raw IP or raw token.
CREATE TABLE IF NOT EXISTS price_alert_tokens (token_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS price_alerts (alert_id TEXT PRIMARY KEY, token_id TEXT NOT NULL, rate_id TEXT, gpu TEXT, vendor TEXT, vram_gb INTEGER, tiers TEXT, threshold_usd REAL NOT NULL, direction TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_evaluated_at TEXT, last_fired_at TEXT, last_fired_price REAL);
CREATE INDEX IF NOT EXISTS price_alerts_token ON price_alerts(token_id);
CREATE TABLE IF NOT EXISTS price_alert_counters (bucket TEXT NOT NULL, scope TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (bucket, scope));
