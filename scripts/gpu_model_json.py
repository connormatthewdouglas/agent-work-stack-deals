"""T17: small per-model JSON views at /api/v1/gpu/<family>.json (+ index.json) for agents that cannot run stdio MCP
and don't want the full gpu-prices.json. Same rates and selection as compare_gpu_prices: reserved rows are listed but
excluded from every "cheapest"; cheapest is split by tier bucket and VRAM. 'Cheapest' = among tracked providers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.gpu import SERVERLESS, families  # noqa: E402

OUT = ROOT / "api" / "v1" / "gpu"
SCHEMA = "lantern-works-gpu-model-view/1"
BUCKETS = ("on-demand", "spot-community", "serverless", "reserved", "monthly")


def bucket(r: dict) -> str:
    tc = r.get("tier_class") or "on-demand"
    if r.get("tier") == SERVERLESS:
        return "serverless"
    if tc == "reserved":
        return "reserved"
    if tc == "dedicated-monthly" or r.get("unit") == "month":
        return "monthly"
    if tc in ("interruptible", "community", "marketplace"):
        return "spot-community"
    return "on-demand"


def _row(r: dict) -> dict:
    ev = r.get("evidence") or {}
    out = {"provider": r["advertiser"], "gpu": r["gpu"], "vram_gb": r.get("vram_gb"), "tier": r["tier"],
           "tier_class": r.get("tier_class"), "bucket": bucket(r), "interruptible": r.get("interruptible"),
           "hourly_usd_per_gpu": r.get("hourly_equiv_usd"), "unit": r["unit"], "price_usd": r["price_usd"],
           "gpu_count": r.get("gpu_count") or 1, "server_hourly_usd": r.get("server_hourly_usd"),
           "min_gpus": r.get("min_gpus") or 1, "price_status": r.get("price_status"),
           "verified_at": r.get("verified_at"), "source_url": r.get("source_url"), "quote": ev.get("quote"), "interruption_quote": ev.get("interruption_quote"),
           "availability": r.get("availability")}
    return {k: v for k, v in out.items() if v is not None}


def _key(r):
    return (r.get("hourly_equiv_usd") or 0, r["advertiser"], r["gpu"], r["tier"])


def build(slug: str, fam: dict, base: str) -> dict:
    rates = sorted(fam["rates"], key=lambda r: (bucket(r) == "reserved",) + _key(r))
    cheapest = {}
    for b in BUCKETS:
        if b == "reserved":
            continue
        for v in sorted({r.get("vram_gb") for r in rates if bucket(r) == b}, key=lambda x: x or 0):
            rs = [r for r in rates if bucket(r) == b and r.get("vram_gb") == v]
            cheapest.setdefault(b, []).append({"vram_gb": v, **_row(min(rs, key=_key))})
    ver = [r["verified_at"] for r in rates if r.get("verified_at")]
    return {"schema": SCHEMA, "model": fam["name"], "slug": slug,
            "url": f"{base}/api/v1/gpu/{slug}.json",
            "scope": "tracked providers only; 'cheapest' means cheapest among tracked providers",
            "price_basis": "hourly_usd_per_gpu = per-GPU hourly equivalent (monthly rows / 730 h); multi-GPU instances also give server_hourly_usd",
            "reserved_policy": "reserved (commitment) rows are listed under rows but excluded from cheapest",
            "last_checked": max(ver) if ver else None, "row_count": len(rates),
            "providers": sorted({r["advertiser"] for r in rates}),
            "cheapest": cheapest, "rows": [_row(r) for r in rates],
            "full_feed": f"{base}/api/v1/gpu-prices.json",
            "history": f"{base}/api/v1/gpu-prices/history.json"}


def write(gen, rates: list[dict]) -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("*.json"):
        p.unlink()
    paths, idx = [], []
    for slug, fam in families(rates).items():
        if not fam["rates"]:
            continue
        doc = build(slug, fam, gen.BASE)
        gen.assert_public_clean(doc)
        p = OUT / f"{slug}.json"
        p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(p)
        idx.append({"model": doc["model"], "slug": slug, "url": doc["url"], "row_count": doc["row_count"],
                    "providers": len(doc["providers"]), "last_checked": doc["last_checked"]})
    index = {"schema": "lantern-works-gpu-model-index/1",
             "description": "Per-model GPU price views (small JSON). Same data as gpu-prices.json; reserved rows excluded from cheapest.",
             "models": idx}
    gen.assert_public_clean(index)
    (OUT / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths
