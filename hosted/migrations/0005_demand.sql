-- Stats DB (lantern-works-hosted-mcp-stats), additive only: P8 daily aggregate demand counters.
-- Apply once: npx wrangler d1 execute lantern-works-hosted-mcp-stats --remote --file=migrations/0005_demand.sql
-- One counter per UTC day x tool x bucketed GPU family x region group x price tier x cheapest provider. No caller IDs,
-- raw arguments or free text; house traffic and known bots are not counted.
CREATE TABLE IF NOT EXISTS demand (day TEXT NOT NULL, tool TEXT NOT NULL, gpu_family TEXT NOT NULL, region_group TEXT NOT NULL, price_tier TEXT NOT NULL, cheapest_provider TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, tool, gpu_family, region_group, price_tier, cheapest_provider));
