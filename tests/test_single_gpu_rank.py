"""Single-GPU headlines go through core price rank and skip min_gpus above 1.

core.deals.gpu_rate_rank_key is price-only. It does not read min_gpus, so
compare_gpu_prices still ranks a cheaper N-GPU row first. The site skips those
rows when it names a single-GPU price. Affiliate status is not a rank input.
Reserved rates are never the headline.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from core.deals import compare_gpu_prices, gpu_rate_rank_key  # noqa: E402
import gpu_pages  # noqa: E402
import spec_pages  # noqa: E402
from gpu_model_json import build  # noqa: E402

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


def _row(vendor, price, *, min_gpus=1, tier="On-demand", tier_class="on-demand", affiliate=False,
         in_stock=None, gpu="H100 SXM", billing_unit="hourly"):
    r = {
        "advertiser": vendor, "gpu": gpu, "vram_gb": 80, "hourly_equiv_usd": price, "price_usd": price,
        "unit": "hour", "tier": tier, "tier_class": tier_class, "billing_unit": billing_unit,
        "interruptible": tier_class == "interruptible", "min_gpus": min_gpus, "gpu_count": min_gpus,
        "affiliate": affiliate, "verified_at": (NOW - timedelta(hours=2)).isoformat(),
        "source_url": f"https://example.com/{vendor}",
    }
    if in_stock is not None:
        r["availability"] = {"in_stock": in_stock}
    return r


MULTI = _row("Vast", 0.40, min_gpus=8, tier="On-demand (8x GPU)")
SINGLE = _row("RunPod", 1.99, affiliate=True)
DEARER = _row("Lambda", 3.50, affiliate=False)
OOS = _row("CheapOOS", 0.15, in_stock=False)
RESERVED = _row("CommitCo", 0.05, tier="Reserved 1-year", tier_class="reserved")
SPOT_MULTI = _row("Lium", 0.20, min_gpus=2, tier="Spot", tier_class="interruptible")
SPOT_SINGLE = _row("Hyperstack", 0.90, tier="Spot", tier_class="interruptible")


def test_engine_rank_does_not_skip_min_gpus():
    """The engine was not changed to exclude multi-GPU rows. A cheaper 8-GPU row still ranks first."""
    data = {"rates": [SINGLE, MULTI, RESERVED], "feed_updated_at": NOW.isoformat()}
    out = compare_gpu_prices(data, "H100", now=NOW, on_demand_only=False, include_reserved=True)
    assert out["results"][0]["advertiser"] == "Vast"
    assert out["results"][0]["min_gpus"] == 8
    assert gpu_rate_rank_key(MULTI) < gpu_rate_rank_key(SINGLE)


def test_rank_key_ignores_affiliate_and_min_gpus_value():
    a = _row("A", 1.0, affiliate=False)
    b = _row("A", 1.0, affiliate=True)
    assert gpu_rate_rank_key(a) == gpu_rate_rank_key(b)
    hi = _row("A", 1.0, min_gpus=8)
    assert gpu_rate_rank_key(a) == gpu_rate_rank_key(hi)


def test_gpu_pages_headline_skips_cheaper_multi_reserved_and_oos():
    rows = [MULTI, OOS, RESERVED, DEARER, SINGLE]
    picked = gpu_pages._pick_cheapest(rows)
    assert picked["advertiser"] == "RunPod"
    assert gpu_pages.min_gpus_count(picked) == 1
    assert picked["tier_class"] != "reserved"
    hourly = gpu_pages.hourly_single(rows)
    assert hourly[0]["advertiser"] == "RunPod"
    assert all(gpu_pages.min_gpus_count(r) <= 1 and r["tier_class"] != "reserved" for r in hourly)
    flipped = [dict(r, affiliate=not r["affiliate"]) for r in rows]
    assert [r["advertiser"] for r in gpu_pages.rank_rates(rows)] == [r["advertiser"] for r in gpu_pages.rank_rates(flipped)]
    assert gpu_pages.min_gpus_phrase(MULTI) == "8x GPU minimum"
    assert gpu_pages.min_gpus_phrase(SINGLE) == ""
    assert "8x GPU minimum" in gpu_pages._rate_str(MULTI)


def test_spec_heads_skip_multi_gpu_minimums():
    rows = [MULTI, SINGLE, SPOT_MULTI, SPOT_SINGLE, RESERVED]
    od = spec_pages.on_demand_head(rows)
    sp = spec_pages.spot_head(rows)
    assert od["advertiser"] == "RunPod" and spec_pages.gp.min_gpus_count(od) == 1
    assert sp["advertiser"] == "Hyperstack" and sp["hourly_equiv_usd"] == 0.90
    assert "2x GPU minimum" in spec_pages.price_cell(type("G", (), {})(), SPOT_MULTI)


def test_model_json_cheapest_skips_multi_gpu_rows():
    fam = {"name": "H100", "rates": [MULTI, SINGLE, RESERVED, SPOT_MULTI, SPOT_SINGLE]}
    doc = build("h100", fam, "https://example.com")
    named = [r["provider"] for rows in doc["cheapest"].values() for r in rows]
    assert "Vast" not in named and "CommitCo" not in named and "Lium" not in named
    assert "RunPod" in named and "Hyperstack" in named
    assert any(r.get("min_gpus") == 8 for r in doc["rows"])
    assert "commission" not in json.dumps(doc).lower()


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_embed_rank_matches_core_and_skips_multi_gpu():
    node = r"""
const r = require(process.argv[1]);
const rows = JSON.parse(process.argv[2]);
const head = r.singleGpuHeadline(rows);
const order = r.rankGpuRates(rows).map(x => x.advertiser);
process.stdout.write(JSON.stringify({head: head && head.advertiser, order, label: r.minGpusLabel(rows[0])}));
"""
    rows = [MULTI, SINGLE, OOS, RESERVED, DEARER]
    proc = subprocess.run(
        ["node", "-e", node, str(ROOT / "embed" / "rank.js"), json.dumps(rows)],
        capture_output=True, text=True, check=True,
    )
    got = json.loads(proc.stdout)
    assert got["head"] == "RunPod"
    assert got["order"] == [r["advertiser"] for r in gpu_pages.rank_rates(rows)]
    assert got["label"] == "8x GPU minimum"
    js = (ROOT / "embed" / "badge.js").read_text(encoding="utf-8")
    rank = (ROOT / "embed" / "rank.js").read_text(encoding="utf-8").split("if (typeof module", 1)[0].strip()
    assert rank in js
    assert "cheapest" not in js.lower()
    assert "isSingleGpuRate" in js
