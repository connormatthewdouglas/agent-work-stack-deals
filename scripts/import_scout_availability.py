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
        "feed_status", "feed_min_offers", "derived_from_regions", "availability_expires_at",  # v3.2: carried through unchanged
        "availability_status", "availability_reason", "availability_reason_detail")  # v3.2 (8fb30d76): carried through unchanged


def verify_manifests(raw: bytes, name: str = "feed_enriched_v2_latest.json") -> int:
    """Refuse a snapshot whose sha256 does not match a shipped manifest. LW_SCOUT_MANIFESTS: os.pathsep-separated paths
    (scout-data latest/manifest.json from push_scout_snapshot.sh; Scout's latest_manifest.json if ever shipped).
    "files" values are a hex string or {"sha256": ...}. Missing or empty manifest, or no entry for the feed: no check."""
    got = hashlib.sha256(raw).hexdigest()
    n = 0
    for mp in filter(None, os.environ.get("LW_SCOUT_MANIFESTS", "").split(os.pathsep)):
        p = Path(mp)
        if not p.is_file() or not p.stat().st_size:
            continue
        want = (json.loads(p.read_text(encoding="utf-8")).get("files") or {}).get(name)
        want = want.get("sha256") if isinstance(want, dict) else want
        if want and want != got:
            raise SystemExit(f"sha256 mismatch for {name} vs {p.name}: manifest {want[:12]}, file {got[:12]}")
        if want:
            n += 1
    return n


def _gap_s(first, second) -> float | None:
    from core.gpu_availability import _parse
    a, b = _parse(first), _parse(second)
    return round((b - a).total_seconds(), 1) if a and b else None


def _reads(a: dict) -> dict:
    """first/second stock read times for one raw Scout row (Gauge T73 F1-F6 #2); the gap is computed from the two stamps."""
    out = {"first_read_at": a.get("checked_at"), "second_read_at": a.get("second_read_at")}
    out["second_read_gap_s"] = _gap_s(out["first_read_at"], out["second_read_at"])
    return out


def _same_tier(raw: str, feed: str) -> bool:
    """Scout's raw tier vs the feed's (the feed may add basis words inside the parentheses, e.g. '; median per GPU')."""
    raw, feed = str(raw or ""), str(feed or "")
    return raw == feed or (raw.endswith(")") and feed.startswith(raw[:-1]) and feed[len(raw) - 1] in ";,") or \
        (feed.startswith(raw + " (") and "(" not in raw)


def _raw_for(row: dict, raw_rows: list) -> tuple[dict | None, dict]:
    """(overall raw row, {region: raw row}) for one feed row: vendor (first word), GPU, VRAM and tier."""
    v = str(row["vendor"]).split(" ")[0].lower()
    hits = [a for a in raw_rows if str(a.get("vendor")).split(" ")[0].lower() == v and a.get("gpu_model") == row["gpu"]
            and (a.get("vram_gb") in (None, row.get("vram_gb"))) and _same_tier(a.get("tier"), row["tier"])]
    ov = next((a for a in hits if a.get("region") == "all"), None)
    return ov, {a["region"]: a for a in hits if a.get("region") and a["region"] != "all"}


def _carry_reads(row: dict, ov: dict | None, regions: dict) -> None:
    """Additive: per-region and overall read timestamps from Scout's raw availability file. An overall row with no
    second read of its own, derived from regions, takes the supporting region with the widest gap (labelled)."""
    for d in row.get("available_regions_detail") or []:
        a = regions.get(d.get("region"))
        if a:
            d.update(_reads(a))
            if a.get("second_read_stock_level") is not None and d.get("second_read_stock_level") is None:
                d["second_read_stock_level"] = a["second_read_stock_level"]
    if row.get("in_stock") is None:
        return
    rd = _reads(ov) if ov and ov.get("second_read_at") else None
    if rd:
        rd["second_read_basis"] = "overall"
    else:
        sup = [a for a in regions.values() if a.get("in_stock") is row["in_stock"] and a.get("second_read_at")]
        best = max(sup, key=lambda a: _reads(a)["second_read_gap_s"] or -1, default=None)
        if best:
            rd = {**_reads(best), "second_read_basis": f"region {best.get('region')}"}
    rd = rd or {"first_read_at": row.get("availability_checked_at"), "second_read_at": None, "second_read_gap_s": None}
    row.update(rd)


def main() -> None:
    raw = SRC.read_bytes()
    checked = verify_manifests(raw)
    d = json.loads(raw.decode("utf-8"))
    if not checked:  # N4: every import must match a manifest sha256, whatever version the file claims
        raise SystemExit(f"Scout v{d.get('version')} snapshot refused: no manifest sha256 to verify it (set LW_SCOUT_MANIFESTS)")
    if str(d.get("version")) not in ("2", "2.5", "2.7", "2.9", "3.0", "3.1", "3.2"):  # v2.6 held: failed Gauge QA re18; v2.7, v2.9, v3.0 passed; v3.1 = v3.0 + generation_id; v3.2 = + feed_status/derived_from_regions
        raise SystemExit(f"expected Scout enrichment v2, got {d.get('version')}")
    snap = max((r.get("availability_checked_at") or "" for r in d.get("rows") or []), default="")
    age = age_hours(snap)
    if age is None or age > AVAIL_MAX_AGE_H:  # same refusal as Scout's enrich_feed_v2
        raise SystemExit(f"Scout snapshot {snap or '(no checked_at)'} is {'?' if age is None else f'{age:.1f}'}h old "
                         f"(> {AVAIL_MAX_AGE_H}h); refusing to import")
    overall, raw_rows = {}, []
    ap = Path(os.environ.get("LW_SCOUT_AVAIL") or SRC.with_name("availability_v2_latest.json"))
    if ap.is_file():  # Scout's raw availability file: overall-row derived_from_regions (v3.2); sha256-checked when listed
        araw = ap.read_bytes()
        verify_manifests(araw, "availability_v2_latest.json")
        for a in json.loads(araw.decode("utf-8")).get("rows") or []:
            if a.get("region") == "all":
                overall[(str(a.get("vendor")).lower(), a.get("gpu_model"), a.get("tier"))] = a
            raw_rows.append(a)
    rows = []
    for r in d["rows"]:
        if r.get("in_live_feed") is not True:  # v2.5: only rows confirmed in the live feed (None/missing are skipped)
            continue
        row = {k: r.get(k) for k in KEEP}
        if row.get("feed_status") == "held_below_min_offers":  # v3.2: held rows are never shown as in stock
            row["in_stock"] = None
        ov = overall.get((str(row["vendor"]).split(" ")[0].lower(), row["gpu"], row["tier"]))
        if ov and ov.get("derived_from_regions") is not None:  # N1: carried through from Scout's availability file
            row["derived_from_regions"] = ov["derived_from_regions"]
        rov, rreg = _raw_for(row, raw_rows)
        _carry_reads(row, rov, rreg)
        if row["in_stock"] is True and row["vendor"] == "RunPod":
            if not row.get("available_regions"):  # N2: a GPU-type-wide lowestPrice hint with no confirmed region is not a stock claim
                row["in_stock"] = None
                row["stock_level"] = None
                row["availability_expires_at"] = None
                row["availability_note"] = ("unknown: RunPod's API gave a GPU-type-wide stock hint but no region of this cloud type "
                                            "was confirmed in stock at check time")
            else:  # the overall claim stands only as long as its confirmed regions
                row["derived_from_regions"] = True
        if row.get("available_regions"):  # re30 a: normalised alongside Scout's original labels (Scout files untouched)
            from core.regions import normalize as _rn
            row["available_regions_normalized"] = [_rn(x) for x in row["available_regions"]]
        if row["in_stock"] not in (True, False, None):
            raise SystemExit(f"bad in_stock {row['in_stock']!r} for {row['vendor']} {row['gpu']}")
        if row["in_stock"] is not None and not row["availability_checked_at"]:
            raise SystemExit(f"availability without timestamp: {row['vendor']} {row['gpu']}")
        if row["vendor"] == "Clore.ai" and row.get("offer_count") is not None:
            raise SystemExit("Clore availability must be unrented_servers, never offer_count")
        if any(row[k] is not None for k in ("in_stock", "offer_count", "unrented_servers", "stock_level", "available_regions", "availability_note")):
            rows.append(row)
    doc = {"schema": "lantern-works-gpu-availability/1", "source": f"Lantern Scout availability collector v{d.get('version')} (public no-auth APIs; Verda and Lambda via authenticated vendor APIs, labelled per row)",
           "generation_id": d.get("generation_id") or (json.loads(araw.decode("utf-8")).get("generation_id") if ap.is_file() else None),
           "collected_at": max((r["availability_checked_at"] or "" for r in rows), default=None),
           "imported_rows": len(rows), "rows": sorted(rows, key=lambda r: (r["vendor"], r["gpu"], r["tier"]))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"availability rows={len(rows)} -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
