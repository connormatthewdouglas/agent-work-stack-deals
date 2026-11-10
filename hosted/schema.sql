CREATE TABLE IF NOT EXISTS tool_calls (day TEXT NOT NULL, tool TEXT NOT NULL, ref TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, tool, ref));
CREATE TABLE IF NOT EXISTS hits (day TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, ref TEXT NOT NULL, ua_class TEXT NOT NULL, src_class TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, kind, name, ref, ua_class, src_class));
CREATE TABLE IF NOT EXISTS caller_salts (day TEXT PRIMARY KEY, salt TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS callers (day TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, ua_class TEXT NOT NULL, src_class TEXT NOT NULL, h TEXT NOT NULL, PRIMARY KEY (day, kind, ref, ua_class, src_class, h));
