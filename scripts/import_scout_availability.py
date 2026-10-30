"""Import Lantern Scout's QA-passed availability enrichment (v2/v2.1) into data/gpu_availability/latest.json.

Source (on the box, not in CI): /workspace/lantern-scout/out/feed_enriched_v2_latest.json. Only public fields are kept.
Rules: unknown stays null (shown as 'unknown', never 'out of stock'); availability has its own timestamp and cadence,
separate from the daily price check; Vast.ai counts come from a separate check at the time shown, not the price-quote check. Run by hand (manual snapshot)."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/lantern-scout/out/feed_enriched_v2_latest.json")
sys.path.insert(0, str(ROOT))
from core.gpu_availability import AVAIL_MAX_AGE_H, age_hours  # noqa: E402

OUT = ROOT / "data" / "gpu_availability" / "latest.json"
KEEP = ("vendor", "gpu", "vram_gb", "tier", "region", "available_regions", "in_stock", "offer_count", "unrented_servers",
        "stock_level", "availability_source", "availability_source_type", "availability_checked_at", "availability_note",
        "available_regions_detail", "available_regions_label",  # v2.9: per-region checked_at/expiry (1 h), confirmation
        "feed_status", "feed_min_offers", "derived_from_regions", "availability_expires_at")  # v3.2: carried through unchanged


def verify_manifests(raw: bytes) -> int:
    """Refuse a snapshot whose sha256 does not match a shipped manifest. LW_SCOUT_MANIFESTS: os.pathsep-separated paths
    (scout-data latest/manifest.json from push_scout_snapshot.sh; Scout's latest_manifest.json if ever shipped).
    "files" values are a hex string or {"sha256": ...}. Missing or empty manifest, or no entry for the feed: no check."""
    got = hashlib.sha256(raw).hexdigest()
    n = 0
    for mp in filter(None, os.environ.get("LW_SCOUT_MANIFESTS", "").split(os.pathsep)):
        p = Path(mp)
        if not p.is_file() or not p.stat().st_size:
            continue
        want = (json.loads(p.read_text(encoding="utf-8")).get("files") or {}).get("feed_enriched_v2_latest.json")
        want = want.get("sha256") if isinstance(want, dict) else want
        if want and want != got:
            raise SystemExit(f"sha256 mismatch for feed_enriched_v2_latest.json vs {p.name}: manifest {want[:12]}, file {got[:12]}")
        if want:
            n += 1
    return n


def main() -> None:
    raw = SRC.read_bytes()
    checked = verify_manifests(raw)
    d = json.loads(raw.decode("utf-8"))
    try:
        v = tuple(int(x) for x in str(d.get("version")).split("."))
    except ValueError:
        v = (0,)
    if v >= (3, 1) and not checked:  # M2: 3.1+ must match a manifest sha256
        raise SystemExit(f"Scout v{d.get('version')} snapshot refused: no manifest sha256 to verify it (set LW_SCOUT_MANIFESTS)")
    if str(d.get("version")) not in ("2", "2.5", "2.7", "2.9", "3.0", "3.1", "3.2"):  # v2.6 held: failed Gauge QA re18; v2.7, v2.9, v3.0 passed; v3.1 = v3.0 + generation_id; v3.2 = + feed_status/derived_from_regions
        raise SystemExit(f"expected Scout enrichment v2, got {d.get('version')}")
    snap = max((r.get("availability_checked_at") or "" for r in d.get("rows") or []), default="")
    age = age_hours(snap)
    if age is None or age > AVAIL_MAX_AGE_H:  # same refusal as Scout's enrich_feed_v2
        raise SystemExit(f"Scout snapshot {snap or '(no checked_at)'} is {'?' if age is None else f'{age:.1f}'}h old "
                         f"(> {AVAIL_MAX_AGE_H}h); refusing to import")
    rows = []
    for r in d["rows"]:
        if r.get("in_live_feed") is False:  # v2.5: only rows whose price is in the live feed
            continue
        row = {k: r.get(k) for k in KEEP}
        if row.get("feed_status") == "held_below_min_offers":  # v3.2: held rows are never shown as in stock
            row["in_stock"] = None
        if row["in_stock"] not in (True, False, None):
            raise SystemExit(f"bad in_stock {row['in_stock']!r} for {row['vendor']} {row['gpu']}")
        if row["in_stock"] is not None and not row["availability_checked_at"]:
            raise SystemExit(f"availability without timestamp: {row['vendor']} {row['gpu']}")
        if row["vendor"] == "Clore.ai" and row.get("offer_count") is not None:
            raise SystemExit("Clore availability must be unrented_servers, never offer_count")
        if any(row[k] is not None for k in ("in_stock", "offer_count", "unrented_servers", "stock_level", "available_regions", "availability_note")):
            rows.append(row)
    doc = {"schema": "lantern-works-gpu-availability/1", "source": f"Lantern Scout availability collector v{d.get('version')} (public no-auth APIs; Verda and Lambda via authenticated vendor APIs, labelled per row)",
           "collected_at": max((r["availability_checked_at"] or "" for r in rows), default=None),
           "imported_rows": len(rows), "rows": sorted(rows, key=lambda r: (r["vendor"], r["gpu"], r["tier"]))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"availability rows={len(rows)} -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
