-- Hosted price watches (free opt-in key), separate D1 database from the anonymous stats DB.
-- Keys stored only as SHA-256 hashes; webhook signing secrets are derived from a Worker secret, never stored.
CREATE TABLE IF NOT EXISTS watch_keys (key_id TEXT PRIMARY KEY, key_hash TEXT NOT NULL, webhook_url TEXT NOT NULL, email TEXT, created_at TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS watches (watch_id TEXT PRIMARY KEY, key_id TEXT NOT NULL, gpu TEXT NOT NULL, region TEXT, max_hourly_usd REAL NOT NULL, kinds TEXT NOT NULL, baseline_seq INTEGER NOT NULL DEFAULT 0, baseline_day TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS watches_key ON watches(key_id);
CREATE TABLE IF NOT EXISTS watch_deliveries (watch_id TEXT NOT NULL, event_id TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (watch_id, event_id));
CREATE INDEX IF NOT EXISTS watch_deliveries_event ON watch_deliveries(event_id);
CREATE TABLE IF NOT EXISTS watch_key_counters (key_id TEXT NOT NULL, day TEXT NOT NULL, metric TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (key_id, day, metric));
CREATE TABLE IF NOT EXISTS watch_metrics (day TEXT NOT NULL, metric TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, metric));
CREATE TABLE IF NOT EXISTS watch_constraints (watch_id TEXT PRIMARY KEY, vram_gb INTEGER, tiers TEXT, in_stock TEXT);
CREATE TABLE IF NOT EXISTS watch_attempts (watch_id TEXT NOT NULL, event_id TEXT NOT NULL, attempts INTEGER NOT NULL, first_at TEXT NOT NULL, last_at TEXT NOT NULL, last_outcome TEXT NOT NULL, next_at TEXT, done INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (watch_id, event_id));
CREATE TABLE IF NOT EXISTS watch_ops (k TEXT PRIMARY KEY, v TEXT);
