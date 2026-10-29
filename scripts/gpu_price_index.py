"""Lantern Works GPU Price Index (CC BY 4.0).

For each GPU model family, take each tracked provider's cheapest on-demand per-GPU hourly rate,
then publish the median (and min/max/provider count) across providers. Daily values are rebuilt
from api/v1/gpu-prices/history.json change points; today's value comes from api/v1/gpu-prices.json.
Scope: tracked providers only (not the whole market). Usage: python scripts/gpu_price_index.py
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSE = {
    "data": "CC-BY-4.0",
    "data_license_url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": "Lantern Works GPU Price Index (https://thelanternworks.com/gpu-price-index/)",
    "code": "MIT",
    "details": "https://thelanternworks.com/methodology/#license",
}
MIN_PROVIDERS = 2


def family(gpu: str) -> str:
    g = re.sub(r"\s+(SXM\d?|PCIe|NVLink)$", "", gpu.strip())
    return g


def summarize(per_vendor: dict[str, float]) -> dict:
    vals = sorted(per_vendor.values())
    return {
        "median_hourly_usd": round(statistics.median(vals), 4),
        "min_hourly_usd": round(vals[0], 4),
        "max_hourly_usd": round(vals[-1], 4),
        "provider_count": len(vals),
    }


def build() -> dict:
    prices = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    hist = json.loads((ROOT / "api/v1/gpu-prices/history.json").read_text())
    ondemand_keys = set()
    today: dict[str, dict[str, float]] = {}
    for r in prices["rates"]:
        if r.get("tier_class") != "on-demand" or r.get("price_status") != "listed":
            continue
        h = r.get("hourly_equiv_usd")
        if not h:
            continue
        per_gpu = h  # hourly_equiv_usd is already per GPU
        fam = family(r["gpu"])
        v = today.setdefault(fam, {})
        v[r["advertiser"]] = min(v.get(r["advertiser"], 1e9), per_gpu)
        ondemand_keys.add((r["advertiser"], r["gpu"], r.get("tier")))
    # daily series from history change points (on-demand keys present today)
    dates = sorted({s.split(".")[0] for s in hist["snapshot_ids"]})
    daily = []
    for d in dates:
        fams: dict[str, dict[str, float]] = {}
        for s in hist["series"]:
            if (s["vendor"], s["gpu"], s["tier"]) not in ondemand_keys:
                continue
            pts = [p for p in s["points"] if p["date"] <= d]
            if not pts or pts[-1].get("status") != "ranked" or not pts[-1].get("hourly_usd"):
                continue
            v = fams.setdefault(family(s["gpu"]), {})
            v[s["vendor"]] = min(v.get(s["vendor"], 1e9), pts[-1]["hourly_usd"])
        daily.append({"date": d, "index": {f: summarize(v) for f, v in sorted(fams.items()) if len(v) >= MIN_PROVIDERS}})
    current = {f: {**summarize(v), "providers": sorted(v)} for f, v in sorted(today.items()) if len(v) >= MIN_PROVIDERS}
    # the latest day uses the live rates file so the page and JSON agree
    latest = (prices.get("prices_verified_through") or "")[:10]
    today_entry = {"date": latest, "index": {f: {k: x for k, x in v.items() if k != "providers"} for f, v in current.items()}}
    daily = [d for d in daily if d["date"] != latest] + [today_entry]
    return {
        "schema": "lantern-works-gpu-price-index/1",
        "name": "Lantern Works GPU Price Index",
        "license": LICENSE,
        "attribution_text": "Source: Lantern Works GPU Price Index (thelanternworks.com/gpu-price-index), CC BY 4.0",
        "source_feed": "https://thelanternworks.com/api/v1/gpu-prices.json",
        "prices_verified_through": prices.get("prices_verified_through"),
        "method": (
            "Per GPU model family (SXM/PCIe/NVLink variants grouped), take each tracked provider's cheapest "
            "listed on-demand per-GPU hourly rate; publish the median across providers, plus min, max and "
            f"provider count. Families with fewer than {MIN_PROVIDERS} providers are omitted. Interruptible, "
            "community, marketplace, reserved and monthly tiers are excluded. Scope: tracked providers only, "
            "not the whole market. Daily history is rebuilt from the price-history change points."
        ),
        "current": current,
        "daily": daily,
    }


def et(ts: str | None) -> str:
    if not ts:
        return "unknown"
    t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-4)))
    return t.strftime("%Y-%m-%d %H:%M ET")


def page(ix: dict) -> str:
    rows = "".join(
        f"<tr><td>{escape(f)}</td><td>${v['median_hourly_usd']:.2f}</td><td>${v['min_hourly_usd']:.2f}</td>"
        f"<td>${v['max_hourly_usd']:.2f}</td><td>{v['provider_count']}</td></tr>"
        for f, v in ix["current"].items()
    )
    fams = list(ix["current"])
    head = "".join(f"<th>{escape(f)}</th>" for f in fams)
    drows = "".join(
        f"<tr><td>{d['date']}</td>" + "".join(
            f"<td>{'$%.2f' % d['index'][f]['median_hourly_usd'] if f in d['index'] else '—'}</td>" for f in fams
        ) + "</tr>"
        for d in ix["daily"]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GPU Price Index (daily median $/GPU-hour) | Lantern Works</title>
  <meta name="description" content="Daily median on-demand GPU rental price per GPU-hour across tracked cloud providers, by GPU model. Open data, CC BY 4.0." />
  <link rel="canonical" href="https://thelanternworks.com/gpu-price-index/" />
  <link rel="alternate" type="application/json" href="https://thelanternworks.com/gpu-price-index/index.json" />
  <style>
    :root {{ font-family: system-ui, sans-serif; color: #111; background: #fafafa; }}
    body {{ max-width: 52rem; margin: 0 auto; padding: 1.25rem; line-height: 1.45; }}
    table {{ border-collapse: collapse; background: #fff; width: 100%; font-size: .92rem; }}
    th, td {{ border: 1px solid #ddd; padding: .35rem .5rem; text-align: left; }}
    th {{ background: #f3f3f3; }} .tscroll {{ overflow-x: auto; }}
    .note {{ font-size: .88rem; color: #444; }}
  </style>
</head>
<body>
<p><a href="/">Lantern Works</a> · <a href="/gpu/price-comparison/">GPU price comparison</a> · <a href="/gpu/changes/">Daily changes</a></p>
<h1>GPU Price Index</h1>
<p>Median on-demand rental price per GPU-hour (USD) across tracked providers, by GPU model. Prices checked through {et(ix['prices_verified_through'])}.</p>
<div class="tscroll"><table><thead><tr><th>GPU</th><th>Median</th><th>Lowest</th><th>Highest</th><th>Providers</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Daily median history</h2>
<div class="tscroll"><table><thead><tr><th>Date</th>{head}</tr></thead><tbody>{drows}</tbody></table></div>
<h2>Method</h2>
<p class="note">{escape(ix['method'])}</p>
<h2>Data and licence</h2>
<p>JSON: <a href="/gpu-price-index/index.json">/gpu-price-index/index.json</a> (also <a href="/api/v1/gpu-price-index.json">/api/v1/gpu-price-index.json</a>). Underlying rates with vendor sources: <a href="/api/v1/gpu-prices.json">/api/v1/gpu-prices.json</a>.</p>
<p>The index data is licensed <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Please attribute: <em>{escape(ix['attribution_text'])}</em>. Code is MIT.</p>
<p class="note">Some listed providers have referral programs with Lantern Works; affiliate status does not affect the index.</p>
</body>
</html>
"""


def main() -> None:
    ix = build()
    out = json.dumps(ix, indent=2) + "\n"
    (ROOT / "gpu-price-index").mkdir(exist_ok=True)
    (ROOT / "gpu-price-index/index.json").write_text(out)
    (ROOT / "api/v1/gpu-price-index.json").write_text(out)
    (ROOT / "gpu-price-index/index.html").write_text(page(ix))


if __name__ == "__main__":
    main()
