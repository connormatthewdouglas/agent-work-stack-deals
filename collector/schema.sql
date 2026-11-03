-- Aggregate counts only. No IPs, no install IDs, no request logs.
CREATE TABLE IF NOT EXISTS counts (
  day TEXT NOT NULL,      -- UTC YYYY-MM-DD reported by the client
  tool TEXT NOT NULL,     -- one of the five MCP tool names
  version TEXT NOT NULL,  -- package version, e.g. 0.3.3
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, tool, version)
);

-- /go/<deal-id> redirect clicks: aggregate only (no IP, user agent, cookie or id).
CREATE TABLE IF NOT EXISTS clicks (
  day TEXT NOT NULL,       -- UTC YYYY-MM-DD
  deal_id TEXT NOT NULL,   -- feed deal id
  provider TEXT NOT NULL,  -- deal advertiser from the feed
  src TEXT NOT NULL,       -- site|mcp|feed|readme (+ -test for our own checks), other, none
  ref TEXT NOT NULL,       -- ?ref= channel tag, other, none
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, deal_id, provider, src, ref)
);
