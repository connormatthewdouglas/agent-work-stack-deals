-- Telemetry DB (lantern-works-telemetry), additive only: opt-in anonymous install ids.
-- Apply once (Mart): npx wrangler d1 execute lantern-works-telemetry --remote --file=migrations/0001_installs.sql
-- Then redeploy the collector. If this table is missing, events still save tool counts and the install insert is ignored.
-- Rows are (day, install_id, ref, tool, version, n). No IP, name, or hostname. Public /v1/stats never returns raw ids.
CREATE TABLE IF NOT EXISTS installs (
  day TEXT NOT NULL,
  install_id TEXT NOT NULL,
  ref TEXT NOT NULL,
  tool TEXT NOT NULL,
  version TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, install_id, ref, tool, version)
);
