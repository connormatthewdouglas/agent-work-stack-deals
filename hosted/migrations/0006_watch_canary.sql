-- Watches D1 (lantern-works-hosted-watches). Additive; the Worker also CREATE TABLE IF NOT EXISTS at request time.
CREATE TABLE IF NOT EXISTS watch_canary (event_id TEXT NOT NULL, watch_id_hash TEXT NOT NULL, received_at TEXT NOT NULL, PRIMARY KEY (event_id, watch_id_hash));
