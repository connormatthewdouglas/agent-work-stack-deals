"""P66/P67 (rosetta, Brain #1006 / #1007): UTC Z timestamps in gpu-prices.json, and held_stale deal_id coverage."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.deals import _parse_dt, apply_utc_z, deal_catalog_updated_at, to_utc_z

ROOT = Path(__file__).resolve().parents[1]
ISO_T = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def _walk_timestamps(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_timestamps(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_timestamps(v, f"{path}[]")
    elif isinstance(obj, str) and ISO_T.match(obj):
        yield path, obj


def test_to_utc_z_accepts_offsets_z_and_naive_and_leaves_non_datetimes():
    assert to_utc_z("2026-10-29T09:30:00-04:00") == "2026-10-29T13:30:00Z"
    assert to_utc_z("2026-11-16T19:40-05:00") == "2026-11-17T00:40:00Z"
    assert to_utc_z("2026-11-09T03:51:49+00:00") == "2026-11-09T03:51:49Z"
    assert to_utc_z("2026-11-22T18:51:23Z") == "2026-11-22T18:51:23Z"
    assert to_utc_z("2026-11-22T18:51:23") == "2026-11-22T18:51:23Z"
    assert to_utc_z("2026-11-22") == "2026-11-22"  # date-only unchanged
    assert to_utc_z("not a time") == "not a time"
    assert to_utc_z(None) is None
    dt = datetime(2026, 11, 22, 13, 30, tzinfo=timezone(timedelta(hours=-4)))
    assert to_utc_z(dt) == "2026-11-22T17:30:00Z"
    # backward-compatible parse
    assert _parse_dt("2026-10-29T09:30:00-04:00") == _parse_dt("2026-10-29T13:30:00Z")
    assert _parse_dt("2026-11-09T03:51:49+00:00") == _parse_dt("2026-11-09T03:51:49Z")


def test_apply_utc_z_rewrites_nested_timestamps_only():
    payload = {
        "deal_feed_updated_at": "2026-10-29T09:30:00-04:00",
        "note": "no available node at 2026-11-22T23:49:39+00:00; withheld",
        "rows": [{"checked_at": "2026-11-09T03:51:49+00:00", "day": "2026-11-09"}],
    }
    out = apply_utc_z(payload)
    assert out["deal_feed_updated_at"] == "2026-10-29T13:30:00Z"
    assert out["rows"][0]["checked_at"] == "2026-11-09T03:51:49Z"
    assert out["rows"][0]["day"] == "2026-11-09"
    assert out["note"].endswith("2026-11-22T23:49:39+00:00; withheld")  # not a standalone timestamp


def test_published_gpu_prices_timestamps_are_utc_z():
    doc = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    bad = [(p, s) for p, s in _walk_timestamps(doc) if not s.endswith("Z") or _parse_dt(s) is None]
    assert bad == [], bad[:8]
    served = deal_catalog_updated_at(ROOT)
    assert served
    assert doc["deal_feed_updated_at"] == to_utc_z(served)
    # lag vs GPU stamp stays visible: we do not copy feed_updated_at onto the deal catalog field
    assert doc["deal_feed_updated_at"] != doc["feed_updated_at"] or to_utc_z(served) == doc["feed_updated_at"]


def test_held_stale_deal_id_is_real_or_null_and_never_invented():
    feed = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    deals = json.loads((ROOT / "deals.json").read_text(encoding="utf-8"))["deals"]
    by_id = {d["id"] for d in deals if d.get("id")}
    by_advertiser = {}
    for d in deals:
        if d.get("id") and d.get("advertiser"):
            by_advertiser.setdefault(d["advertiser"], set()).add(d["id"])

    held = feed.get("held_stale") or []
    missing_real = []
    invented = []
    for h in held:
        did = h.get("deal_id")
        vendor = h.get("vendor")
        if did is not None and did not in by_id:
            invented.append((vendor, did))
        # If the vendor pricing record or a unique deals.json advertiser match has a real id, the hold must carry it.
        doc_id = None
        for p in (ROOT / "data" / "gpu_pricing").glob("*.json"):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict) and doc.get("vendor") == vendor:
                doc_id = doc.get("deal_id")
                break
        catalog_ids = by_advertiser.get(vendor) or set()
        expected = doc_id if isinstance(doc_id, str) and doc_id in by_id else (
            next(iter(catalog_ids)) if len(catalog_ids) == 1 else None
        )
        if expected and did != expected:
            missing_real.append((vendor, did, expected))
    assert invented == []
    assert missing_real == []
    # The 22 nulls are vendors with no deal in the public catalog (GPU-price tracking only).
    nulls = [h["vendor"] for h in held if not h.get("deal_id")]
    for vendor in nulls:
        assert vendor not in by_advertiser, vendor
