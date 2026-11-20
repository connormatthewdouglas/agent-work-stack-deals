-- Aggregate counts only. No IPs, no request logs. Install ids are stored only in the installs table below.
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

-- T135: same aggregate plus a coarse ua_class (browser|bot|script|prefetch|other) worked out at request time; the
-- User-Agent itself is never stored. New clicks go here; the clicks table above keeps rows recorded before the filter.
CREATE TABLE IF NOT EXISTS go_clicks (
  day TEXT NOT NULL,
  deal_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  src TEXT NOT NULL,
  ref TEXT NOT NULL,
  ua_class TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, deal_id, provider, src, ref, ua_class)
);

-- Opt-in anonymous install telemetry. install_id is a client-generated UUID, not an IP, name or hostname.
-- Public /v1/stats returns aggregates only (no raw ids). Apply on an existing DB via migrations/0001_installs.sql.
CREATE TABLE IF NOT EXISTS installs (
  day TEXT NOT NULL,          -- UTC YYYY-MM-DD reported by the client
  install_id TEXT NOT NULL,   -- random UUID; never derived from the machine
  ref TEXT NOT NULL,          -- LANTERN_REF tag, other, or none
  tool TEXT NOT NULL,
  version TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, install_id, ref, tool, version)
);
