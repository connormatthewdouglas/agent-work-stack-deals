-- T49 (0.3.48): delivery attempts (bounded retries) and operator state
CREATE TABLE IF NOT EXISTS watch_attempts (watch_id TEXT NOT NULL, event_id TEXT NOT NULL, attempts INTEGER NOT NULL, first_at TEXT NOT NULL, last_at TEXT NOT NULL, last_outcome TEXT NOT NULL, next_at TEXT, done INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (watch_id, event_id));
CREATE TABLE IF NOT EXISTS watch_ops (k TEXT PRIMARY KEY, v TEXT);
