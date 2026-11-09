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
from core.data_license import DATA_LICENSE  # noqa: E402

from core.gpu import PRICE_BASIS_LABELS, price_bucket  # noqa: E402
from core.deals import gpu_rate_rank_key  # noqa: E402
PRICE_BASIS_LABEL = PRICE_BASIS_LABELS["on-demand"]

OUT = ROOT / "api" / "v1" / "gpu"
SCHEMA = "lantern-works-gpu-model-view/1"
BUCKETS = ("on-demand", "spot-community", "serverless", "reserved", "monthly")


def bucket(r: dict) -> str:
    tc = r.get("tier_class") or "on-demand"
    if r.get("tier") == SERVERLESS or "serverless" in (r.get("tier") or "").lower():
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
    request = {k: ev[k] for k in ("request_method", "operation", "record_id") if k in ev}
    if request:
        out["evidence"] = request
    out = {k: v for k, v in out.items() if v is not None}
    # Additive (600me review on gpuhunt#283 / llm-analysis#35 / gpu_poor#18): explicit form factor and price basis.
    out["form_factor"] = _ff(r)
    out["price_basis_label"] = PRICE_BASIS_LABELS[bucket(r)]
    return out


def _ff(r: dict) -> str:
    v = r.get("form_factor")
    return v if v and v != "not stated" else "unknown"


def _group(r: dict) -> tuple:
    """Like-for-like group: never compare SXM vs PCIe or Community vs Secure at headline $/GPU-hour."""
    return (r.get("vram_gb") or 0, _ff(r), r.get("tier") or "unknown")


def build(slug: str, fam: dict, base: str) -> dict:
    from gpu_pages import headline_eligible
    rates = sorted(fam["rates"], key=gpu_rate_rank_key)
    cheapest = {}
    for b in BUCKETS:
        if b in ("reserved", "serverless"):
            continue
        for v in sorted({r.get("vram_gb") for r in rates if bucket(r) == b and headline_eligible(r)}, key=lambda x: x or 0):
            rs = [r for r in rates if bucket(r) == b and r.get("vram_gb") == v and headline_eligible(r)]
            groups = {}
            for r in rs:
                groups.setdefault(_group(r), []).append(r)
            best = sorted((min(g, key=gpu_rate_rank_key) for g in groups.values()), key=gpu_rate_rank_key)
            for r in best:
                row = {"vram_gb": v, **_row(r)}
                row["tier"] = r.get("tier") or "unknown"
                row["verified_at"] = r.get("verified_at") or r.get("checked_at")
                row["source_url"] = r.get("source_url")
                row["group"] = {"form_factor": row["form_factor"], "tier": row["tier"], "vram_gb": v}
                cheapest.setdefault(b, []).append(row)
    ver = [r["verified_at"] for r in rates if r.get("verified_at")]
    return {"schema": SCHEMA, "license": DATA_LICENSE, "model": fam["name"], "slug": slug,
            "url": f"{base}/api/v1/gpu/{slug}.json",
            "scope": "tracked providers only; 'cheapest' means cheapest among tracked providers",
            "price_basis_label": PRICE_BASIS_LABEL,
            "cheapest_grouping": ("cheapest[bucket] has one row per (vram_gb, form_factor, tier) group, sorted by vram_gb then price; "
                                  "SXM vs PCIe and vendor tiers (e.g. RunPod Community vs Secure) are never mixed. "
                                  "form_factor is 'unknown' when the source does not say."),
            "price_basis": "hourly_usd_per_gpu = per-GPU hourly equivalent (monthly rows / 730 h); multi-GPU instances also give server_hourly_usd",
            "reserved_policy": "reserved (commitment) rows and serverless or per-second rows are listed under rows but excluded from cheapest",
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
    try:  # T68: every small view names the full-feed generation it was built from (additive fields)
        _f = json.loads((OUT.parent / "gpu-prices.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _f = {}
    gen_fields = {"generation_id": _f.get("generation_id"), "feed_updated_at": _f.get("feed_updated_at")}
    for slug, fam in families(rates).items():
        if not fam["rates"]:
            continue
        doc = {**build(slug, fam, gen.BASE), **gen_fields}
        gen.assert_public_clean(doc)
        p = OUT / f"{slug}.json"
        p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(p)
        idx.append({"model": doc["model"], "slug": slug, "url": doc["url"], "row_count": doc["row_count"],
                    "providers": len(doc["providers"]), "last_checked": doc["last_checked"]})
    index = {"schema": "lantern-works-gpu-model-index/1", "license": DATA_LICENSE,
             "description": "Per-model GPU price views (small JSON). Same data as gpu-prices.json; reserved rows and serverless or per-second rows excluded from cheapest.",
             **gen_fields, "models": idx}
    gen.assert_public_clean(index)
    (OUT / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths
