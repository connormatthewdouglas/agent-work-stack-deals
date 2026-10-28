"""/api/v1/gpu-price-changes.json and its RSS twin /api/v1/gpu-price-changes.xml (what moved since yesterday's snapshot)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "api" / "v1" / "gpu-price-changes.json"
RSS_PATH = ROOT / "api" / "v1" / "gpu-price-changes.xml"


def write(gen) -> dict:
    sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
    from core.gpu_changes import build_changes, rss
    doc = build_changes()
    doc["source"] = f"{gen.BASE}/api/v1/gpu-prices/history.json"
    doc["rss"] = f"{gen.BASE}/api/v1/gpu-price-changes.xml"
    gen.assert_public_clean(doc)
    JSON_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    RSS_PATH.write_text(rss(doc, gen.BASE), encoding="utf-8")
    return doc
