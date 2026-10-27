-- Aggregate counts only. No IPs, no install IDs, no request logs.
CREATE TABLE IF NOT EXISTS counts (
  day TEXT NOT NULL,      -- UTC YYYY-MM-DD reported by the client
  tool TEXT NOT NULL,     -- one of the five MCP tool names
  version TEXT NOT NULL,  -- package version, e.g. 0.3.3
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, tool, version)
);
