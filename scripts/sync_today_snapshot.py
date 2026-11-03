"""Re-write today's (UTC) price snapshot from the current pricing records, exactly as the daily refresh does, so
/api/v1/gpu-price-changes.json never disagrees with gpu-prices.json after an out-of-band price import (T73/T87:
release gate T41-15). Reads records only; never edits a vendor quote."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import gpu_history  # noqa: E402

files = sorted((ROOT / "data" / "gpu_pricing").glob("*.json"))
docs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
day = datetime.now(timezone.utc).date().isoformat()
gpu_history.write_snapshot(docs, day)
print(f"snapshot {day} synced from {len(docs)} pricing files")
