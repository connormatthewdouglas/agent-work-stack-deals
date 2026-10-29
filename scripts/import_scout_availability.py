"""Import Lantern Scout's QA-passed availability enrichment (v2) into data/gpu_availability/latest.json.

Source (on the box, not in CI): /workspace/lantern-scout/out/feed_enriched_v2_latest.json. Only public fields are kept.
Rules: unknown stays null (shown as 'unknown', never 'out of stock'); availability has its own timestamp and cadence,
separate from the daily price check; Vast.ai counts are consistency-checked against the same snapshot only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/lantern-scout/out/feed_enriched_v2_latest.json")
OUT = ROOT / "data" / "gpu_availability" / "latest.json"
KEEP = ("vendor", "gpu", "vram_gb", "tier", "region", "available_regions", "in_stock", "offer_count", "stock_level",
        "availability_source", "availability_checked_at", "refresh_rate")


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    if d.get("version") != 2:
        raise SystemExit(f"expected Scout enrichment v2, got {d.get('version')}")
    rows = []
    for r in d["rows"]:
        row = {k: r.get(k) for k in KEEP}
        if row["in_stock"] not in (True, False, None):
            raise SystemExit(f"bad in_stock {row['in_stock']!r} for {row['vendor']} {row['gpu']}")
        if row["in_stock"] is not None and not row["availability_checked_at"]:
            raise SystemExit(f"availability without timestamp: {row['vendor']} {row['gpu']}")
        if any(row[k] is not None for k in ("in_stock", "offer_count", "stock_level", "available_regions")):
            rows.append(row)
    doc = {"schema": "lantern-works-gpu-availability/1", "source": "Lantern Scout availability collector v2 (public vendor APIs, no auth)",
           "imported_rows": len(rows), "rows": sorted(rows, key=lambda r: (r["vendor"], r["gpu"], r["tier"]))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"availability rows={len(rows)} -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
