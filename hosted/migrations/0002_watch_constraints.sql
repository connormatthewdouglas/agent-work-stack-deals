-- T47 (0.3.52): watch eligibility constraints; additive, applied 2026-10-30
CREATE TABLE IF NOT EXISTS watch_constraints (watch_id TEXT PRIMARY KEY, vram_gb INTEGER, tiers TEXT, in_stock TEXT);
