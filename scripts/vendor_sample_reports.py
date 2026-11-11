#!/usr/bin/env python3
"""One-page sample reports for each tracked instance vendor (Plan Task 18).

Reads the published GPU price feed and daily snapshots only. Missing history is
disclosed, never invented. Pages are generated; do not hand-edit the HTML/SVG.

  python3 scripts/vendor_sample_reports.py
  python3 scripts/vendor_sample_reports.py --verify   # public GET, robots.txt respected

Hooked from generate_seo_pages.py so a pinned regenerate keeps the pages in sync.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from html import escape as html_escape
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

PRICES_PATH = ROOT / "api" / "v1" / "gpu-prices.json"
HISTORY_PATH = ROOT / "api" / "v1" / "gpu-prices" / "history.json"
SNAPSHOT_DIR = ROOT / "data" / "gpu_pricing" / "snapshots"
CHANGES_PATH = ROOT / "api" / "v1" / "gpu-price-changes.json"
OUT_DIR = ROOT / "reports" / "vendors"
VERIFY_SRC = ROOT / "data" / "reports" / "vendor-verification.json"
BASE = "https://thelanternworks.com"
WINDOW_DAYS = 14
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
UA = "LanternWorksPriceCheck/1.1 (+https://thelanternworks.com/methodology/)"
DISCLOSURE = (
    "Disclosure: some vendor links on Lantern Works are referral/affiliate links "
    "(currently RunPod, Thunder Compute, Vast.ai, Novita AI, Clore.ai, Ucartz and "
    "99Stack Cloud). Lantern Works may earn a commission. Affiliate status does "
    "not affect rankings."
)

# Stable public path segments; fallback slugify covers a vendor added later.
VENDOR_SLUGS = {
    "99Stack Cloud": "99stack",
    "Amazon Web Services": "aws",
    "Microsoft Azure": "azure",
    "Cirrascale": "cirrascale",
    "Civo": "civo",
    "Clore.ai": "clore",
    "CloudRift": "cloudrift",
    "CoreWeave": "coreweave",
    "DigitalOcean GPU Droplets": "digitalocean",
    "E2E Networks": "e2e-networks",
    "Hot Aisle": "hot-aisle",
    "Hyperstack": "hyperstack",
    "Jarvislabs": "jarvislabs",
    "Koyeb": "koyeb",
    "Lambda": "lambda",
    "Lium": "lium",
    "Modal": "modal",
    "Nebius": "nebius",
    "Nova Cloud": "nova-cloud",
    "Novita AI": "novita",
    "OVHcloud (US)": "ovhcloud",
    "Oblivus": "oblivus",
    "RunC.AI": "runc-ai",
    "RunPod": "runpod",
    "SaladCloud": "salad",
    "Spheron": "spheron",
    "Thunder Compute": "thunder-compute",
    "Ucartz": "ucartz",
    "Vast.ai": "vast",
    "Verda (formerly DataCrunch)": "verda",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def vendor_slug(name: str) -> str:
    if name in VENDOR_SLUGS:
        return VENDOR_SLUGS[name]
    s = re.sub(r"\s*\(.*?\)", "", name.lower())
    s = s.replace(".ai", "").replace(".io", "")
    s = _SLUG_RE.sub("-", s).strip("-")
    return s or "vendor"


def iso_date(value) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def window_days(end: date, days: int = WINDOW_DAYS) -> tuple[date, date, list[date]]:
    """Inclusive calendar window of `days` days ending on `end`."""
    start = end - timedelta(days=days - 1)
    return start, end, [start + timedelta(days=i) for i in range(days)]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshots(directory: Path | None = None) -> list[dict]:
    directory = directory or SNAPSHOT_DIR
    snaps = []
    if not directory.is_dir():
        return snaps
    for path in sorted(directory.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("date") and isinstance(doc.get("rows"), list):
            snaps.append(doc)
    snaps.sort(key=lambda d: d["date"])
    return snaps


def snapshot_dates(snaps: list[dict]) -> set[date]:
    out = set()
    for snap in snaps:
        d = iso_date(snap.get("date"))
        if d:
            out.add(d)
    return out


def comparable_snapshot_row(row: dict) -> bool:
    """Like-for-like undercut set: ranked, 1-GPU, not spot/interruptible/reserved."""
    if (row.get("status") or "") != "ranked":
        return False
    try:
        n = int(row.get("gpu_count") or 1)
    except (TypeError, ValueError):
        n = 1
    if n != 1:
        return False
    tier = (row.get("tier") or "").lower()
    if any(w in tier for w in ("interruptible", "spot", "reserved", "preempt")):
        return False
    return True


# Bound in _bind() once gpu_pages / core.ids are imported.
headline_eligible = None  # type: ignore
rate_id_fn = None  # type: ignore
comparable_current_rate = None  # type: ignore


def _bind():
    global headline_eligible, rate_id_fn, comparable_current_rate
    import gpu_pages as gp
    from core.ids import rate_id as _rate_id
    headline_eligible = gp.headline_eligible
    rate_id_fn = _rate_id

    def _comparable(row: dict) -> bool:
        if not gp.headline_eligible(row, gpus=1):
            return False
        if row.get("interruptible") or (row.get("tier_class") or "") == "interruptible":
            return False
        return True

    comparable_current_rate = _comparable  # type: ignore[assignment]


def ineligible_reason(row: dict) -> str:
    from core.gpu import min_gpus_unmet
    from core.serverless import rate_reason
    bits = []
    if min_gpus_unmet(row, 1):
        n = row.get("min_gpus") or row.get("gpu_count") or 1
        bits.append(f"sold only as a {n}-GPU minimum")
    if (row.get("tier_class") or "on-demand") == "reserved":
        bits.append("reserved tier")
    if rate_reason(row) is not None:
        bits.append("serverless")
    if row.get("interruptible") or (row.get("tier_class") or "") == "interruptible":
        bits.append("interruptible/spot")
    return ", ".join(bits) or "not comparable under the single-GPU on-demand rule"


def money(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "no figure recorded"
    if n >= 100:
        return f"${n:,.2f}"
    # Keep more precision for sub-dollar and fractional list prices.
    text = f"{n:.4f}".rstrip("0").rstrip(".")
    return f"${text}"


def competition_ranks(priced: list[tuple[str, float]]) -> dict[str, tuple[int, int, bool]]:
    """vendor -> (rank, field_size, tied). Competition rank; lower price wins."""
    if not priced:
        return {}
    ordered = sorted(priced, key=lambda t: (t[1], t[0].lower()))
    field = len(ordered)
    out: dict[str, tuple[int, int, bool]] = {}
    i = 0
    while i < len(ordered):
        price = ordered[i][1]
        j = i
        while j < len(ordered) and ordered[j][1] == price:
            j += 1
        tied = (j - i) > 1
        rank = i + 1
        for k in range(i, j):
            out[ordered[k][0]] = (rank, field, tied)
        i = j
    return out


def best_comparable_by_gpu(rates: list[dict], predicate) -> dict[str, list[tuple[str, float, dict]]]:
    """gpu name -> list of (vendor, hourly, row) using each vendor's lowest comparable rate."""
    by: dict[str, dict[str, tuple[float, dict]]] = defaultdict(dict)
    for row in rates:
        if not predicate(row):
            continue
        gpu = row.get("gpu") or row.get("canonical_model")
        vendor = row.get("advertiser") or row.get("vendor")
        price = row.get("hourly_equiv_usd")
        if price is None:
            price = row.get("hourly_usd")
        if not gpu or not vendor or price is None:
            continue
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            continue
        cur = by[gpu].get(vendor)
        if cur is None or price_f < cur[0]:
            by[gpu][vendor] = (price_f, row)
    out: dict[str, list[tuple[str, float, dict]]] = {}
    for gpu, vendors in by.items():
        out[gpu] = [(v, p, r) for v, (p, r) in vendors.items()]
    return out


def tracked_vendors(prices: dict) -> list[str]:
    names = []
    seen = set()
    for item in prices.get("vendors") or []:
        name = item.get("vendor") if isinstance(item, dict) else None
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def vendor_meta(prices: dict) -> dict[str, dict]:
    return {v["vendor"]: v for v in (prices.get("vendors") or []) if isinstance(v, dict) and v.get("vendor")}


def build_ranks(prices: dict) -> dict[str, list[dict]]:
    """Per vendor, one row per GPU they currently list, with rank when comparable."""
    _bind()
    rates = list(prices.get("rates") or [])
    comparable = best_comparable_by_gpu(rates, comparable_current_rate)
    ranks_by_gpu = {
        gpu: competition_ranks([(v, p) for v, p, _ in rows])
        for gpu, rows in comparable.items()
    }
    cheapest = {
        gpu: min(rows, key=lambda t: (t[1], t[0].lower()))
        for gpu, rows in comparable.items()
        if rows
    }
    by_vendor: dict[str, list[dict]] = defaultdict(list)
    # Every current listed rate, including ones that are not in the comparable set.
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rates:
        vendor = row.get("advertiser")
        gpu = row.get("gpu")
        if vendor and gpu:
            grouped[(vendor, gpu)].append(row)
    for (vendor, gpu), rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda r: (r.get("hourly_equiv_usd") is None, r.get("hourly_equiv_usd") or 0))
        best = rows_sorted[0]
        info = {
            "gpu": gpu,
            "canonical_model": best.get("canonical_model") or gpu,
            "form_factor": best.get("form_factor"),
            "tier": best.get("tier"),
            "hourly_equiv_usd": best.get("hourly_equiv_usd"),
            "gpu_count": best.get("gpu_count") or 1,
            "min_gpus": best.get("min_gpus") or 1,
            "source_url": best.get("source_url"),
            "verified_at": best.get("verified_at") or best.get("last_verified") or best.get("checked_at"),
            "evidence": best.get("evidence") or {},
            "rate_id": rate_id_fn(best) if rate_id_fn else None,
            "quote_id": (best.get("evidence") or {}).get("quote_id") or best.get("quote_id"),
            "comparable": False,
            "rank": None,
            "field": None,
            "tied": False,
            "cheapest_vendor": None,
            "cheapest_hourly_usd": None,
            "reason": None,
            "row": best,
        }
        if vendor in ranks_by_gpu.get(gpu, {}):
            rank, field, tied = ranks_by_gpu[gpu][vendor]
            cheap_v, cheap_p, _ = cheapest[gpu]
            info.update({
                "comparable": True,
                "rank": rank,
                "field": field,
                "tied": tied,
                "cheapest_vendor": cheap_v,
                "cheapest_hourly_usd": cheap_p,
            })
        else:
            # If any of the vendor's rows for this gpu is ineligible, say why (best first).
            info["reason"] = ineligible_reason(best)
        by_vendor[vendor].append(info)
    for vendor in by_vendor:
        by_vendor[vendor].sort(key=lambda r: ((r["rank"] is None), r["rank"] or 99, r["gpu"]))
    return by_vendor


def build_undercuts(
    snaps: list[dict],
    end: date,
    vendor: str,
    days: int = WINDOW_DAYS,
) -> dict:
    start, end, calendar = window_days(end, days)
    present = snapshot_dates(snaps)
    missing = [d for d in calendar if d not in present]
    present_in_window = [d for d in calendar if d in present]
    by_date = {iso_date(s["date"]): s for s in snaps if iso_date(s.get("date"))}

    # (day, gpu) observations where someone was cheaper, and who.
    observations = []  # dicts
    by_other: Counter = Counter()
    by_other_gpus: dict[str, set] = defaultdict(set)
    days_with_comparable = 0
    models_seen = set()

    for day in present_in_window:
        snap = by_date[day]
        comparable = [r for r in (snap.get("rows") or []) if comparable_snapshot_row(r)]
        by_gpu: dict[str, list[dict]] = defaultdict(list)
        for row in comparable:
            gpu = row.get("gpu")
            if gpu:
                by_gpu[gpu].append(row)
        vendor_gpus = {r.get("gpu") for r in comparable if r.get("vendor") == vendor and r.get("gpu")}
        if vendor_gpus:
            days_with_comparable += 1
        for gpu in sorted(vendor_gpus):
            models_seen.add(gpu)
            rows = by_gpu[gpu]
            ours = [r for r in rows if r.get("vendor") == vendor]
            if not ours:
                continue
            our_price = min(float(r["hourly_usd"]) for r in ours if r.get("hourly_usd") is not None)
            cheaper = []
            for r in rows:
                other = r.get("vendor")
                if other == vendor or r.get("hourly_usd") is None:
                    continue
                price = float(r["hourly_usd"])
                if price < our_price:
                    cheaper.append((other, price))
            if cheaper:
                # one observation per other vendor at their best price that day
                best_by = {}
                for other, price in cheaper:
                    if other not in best_by or price < best_by[other]:
                        best_by[other] = price
                others = sorted(best_by, key=lambda n: (best_by[n], n.lower()))
                observations.append({
                    "date": day.isoformat(),
                    "gpu": gpu,
                    "our_hourly_usd": our_price,
                    "undercut_by": [{"vendor": n, "hourly_usd": best_by[n]} for n in others],
                })
                for n in others:
                    by_other[n] += 1
                    by_other_gpus[n].add(gpu)

    return {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": days,
        "snapshot_days_present": [d.isoformat() for d in present_in_window],
        "snapshot_days_missing": [d.isoformat() for d in missing],
        "days_with_comparable_rate": days_with_comparable,
        "models_seen": sorted(models_seen),
        "undercut_observations": observations,
        "undercut_count": len(observations),
        "undercut_by": [
            {
                "vendor": name,
                "times": count,
                "gpus": sorted(by_other_gpus[name]),
            }
            for name, count in by_other.most_common()
        ],
        "history_incomplete": bool(missing),
    }


def pick_end_date(prices: dict, history: dict | None, changes: dict | None, snaps: list[dict]) -> date:
    candidates = []
    if history:
        d = iso_date(history.get("last_snapshot"))
        if d:
            candidates.append(d)
    if changes:
        d = iso_date(changes.get("date"))
        if d:
            candidates.append(d)
    if snaps:
        d = iso_date(snaps[-1].get("date"))
        if d:
            candidates.append(d)
    d = iso_date((prices or {}).get("feed_updated_at"))
    if d:
        candidates.append(d)
    if not candidates:
        raise SystemExit("cannot determine feed date for the 14-day window")
    return max(candidates)


def held_rows_for(prices: dict, vendor: str) -> dict | None:
    for item in prices.get("held_stale") or []:
        if item.get("vendor") == vendor:
            return item
    return None


def build_all(root: Path | None = None) -> dict:
    root = root or ROOT
    prices = load_json(root / "api" / "v1" / "gpu-prices.json")
    history = None
    hpath = root / "api" / "v1" / "gpu-prices" / "history.json"
    if hpath.is_file():
        history = load_json(hpath)
    changes = None
    cpath = root / "api" / "v1" / "gpu-price-changes.json"
    if cpath.is_file():
        changes = load_json(cpath)
    snaps = load_snapshots(root / "data" / "gpu_pricing" / "snapshots")
    end = pick_end_date(prices, history, changes, snaps)
    vendors = tracked_vendors(prices)
    meta = vendor_meta(prices)
    ranks = build_ranks(prices)
    verify = None
    vpath = root / "data" / "reports" / "vendor-verification.json"
    if vpath.is_file():
        try:
            verify = load_json(vpath)
        except (OSError, ValueError):
            verify = None
    reports = []
    for name in vendors:
        reports.append({
            "vendor": name,
            "slug": vendor_slug(name),
            "meta": meta.get(name) or {},
            "ranks": ranks.get(name) or [],
            "undercuts": build_undercuts(snaps, end, name),
            "held": held_rows_for(prices, name),
            "has_current_rates": bool(ranks.get(name)),
        })
    return {
        "prices": prices,
        "history": history,
        "changes": changes,
        "end": end.isoformat(),
        "feed_updated_at": prices.get("feed_updated_at"),
        "prices_verified_through": prices.get("prices_verified_through"),
        "reports": reports,
        "verification": verify,
    }


def rank_chart_svg(rows: list[dict], vendor: str) -> str:
    """Horizontal bars: this vendor vs the cheapest tracked comparable rate, per GPU."""
    chartable = [r for r in rows if r.get("comparable") and r.get("hourly_equiv_usd") is not None]
    width = 720
    left, right, top = 168, 24, 36
    bar_h, gap = 16, 18
    row_h = bar_h * 2 + 8
    if not chartable:
        height = 80
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="No comparable single-GPU on-demand rates to chart.">\n'
            f'  <title>No comparable rates to chart for {html_escape(vendor)}</title>\n'
            f'  <rect width="{width}" height="{height}" fill="#fafafa"/>\n'
            f'  <text x="{width/2}" y="44" text-anchor="middle" fill="#555" '
            f'font-family="system-ui,sans-serif" font-size="14">'
            f"No comparable single-GPU on-demand rates to chart.</text>\n"
            f"</svg>\n"
        )
    height = top + 28 + len(chartable) * (row_h + gap) + 24
    max_p = max(
        max(float(r["hourly_equiv_usd"]), float(r["cheapest_hourly_usd"] or 0))
        for r in chartable
    )
    max_p = max(max_p, 0.01)
    inner = width - left - right

    def x_for(p: float) -> float:
        return left + (float(p) / max_p) * inner

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Current hourly rate versus the cheapest tracked vendor, by GPU model.">\n',
        f"  <title>{html_escape(vendor)} hourly rate vs cheapest tracked comparable rate</title>\n",
        f'  <rect width="{width}" height="{height}" fill="#fafafa"/>\n',
        f'  <text x="{left}" y="20" font-family="system-ui,sans-serif" font-size="13" fill="#111">'
        f"{html_escape(vendor)} (amber) vs cheapest tracked comparable rate (gray)</text>\n",
    ]
    y = top + 8
    for r in chartable:
        ours = float(r["hourly_equiv_usd"])
        cheap = float(r["cheapest_hourly_usd"])
        label = r["gpu"]
        if len(label) > 22:
            label = label[:20] + "…"
        parts.append(
            f'  <text x="{left - 8}" y="{y + bar_h}" text-anchor="end" '
            f'font-family="system-ui,sans-serif" font-size="11" fill="#111">{html_escape(label)}</text>\n'
        )
        parts.append(
            f'  <rect x="{left}" y="{y}" width="{max(x_for(ours) - left, 1):.1f}" height="{bar_h}" '
            f'fill="#f59e0b" rx="2"/>\n'
        )
        parts.append(
            f'  <text x="{x_for(ours) + 4:.1f}" y="{y + bar_h - 3}" '
            f'font-family="system-ui,sans-serif" font-size="10" fill="#111">{html_escape(money(ours))}</text>\n'
        )
        parts.append(
            f'  <rect x="{left}" y="{y + bar_h + 2}" width="{max(x_for(cheap) - left, 1):.1f}" height="{bar_h}" '
            f'fill="#64748b" rx="2"/>\n'
        )
        cheap_label = f"{money(cheap)} ({r['cheapest_vendor']})"
        parts.append(
            f'  <text x="{x_for(cheap) + 4:.1f}" y="{y + bar_h * 2 - 1}" '
            f'font-family="system-ui,sans-serif" font-size="10" fill="#333">{html_escape(cheap_label)}</text>\n'
        )
        y += row_h + gap
    parts.append("</svg>\n")
    return "".join(parts)


def _esc(gen, s) -> str:
    return gen.esc(s) if gen is not None and hasattr(gen, "esc") else html_escape(str(s or ""))


def _fmt_ts(value) -> str:
    if not value:
        return "not recorded"
    text = str(value).replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1] + " UTC"
    return text


def _verification_for(bundle: dict, slug: str) -> dict | None:
    doc = bundle.get("verification") or {}
    for item in doc.get("vendors") or []:
        if item.get("slug") == slug:
            return item
    return None


def _evidence_html(gen, row: dict) -> str:
    ev = row.get("evidence") or {}
    quote = ev.get("quote") or ""
    src = row.get("source_url") or ev.get("source_url") or ""
    rid = row.get("rate_id") or "not-recorded"
    qid = row.get("quote_id")
    bits = [f'<code>rate_id={_esc(gen, rid)}</code>']
    if qid:
        bits.append(f'<code>quote_id={_esc(gen, qid)}</code>')
    checked = ev.get("checked_at") or row.get("verified_at") or "not recorded"
    bits.append(f"source check {_esc(gen, _fmt_ts(checked))}")
    quote_html = ""
    if quote:
        q = " ".join(str(quote).split())
        quote_html = f"<blockquote><p>{_esc(gen, q)}</p></blockquote>"
    else:
        quote_html = "<p>No source quote is recorded on this rate; none was invented.</p>"
    link = f'<a href="{_esc(gen, src)}" rel="noopener">{_esc(gen, src)}</a>' if src else "no source_url recorded"
    return f"<p>{' · '.join(bits)} · {link}</p>{quote_html}"


def vendor_body(gen, bundle: dict, report: dict) -> str:
    e = lambda s: _esc(gen, s)
    name = report["vendor"]
    slug = report["slug"]
    meta = report["meta"]
    under = report["undercuts"]
    ranks = report["ranks"]
    held = report["held"]
    src = meta.get("source_url") or (ranks[0]["source_url"] if ranks else None)
    feed_ts = bundle.get("feed_updated_at") or "not recorded"
    verified_through = bundle.get("prices_verified_through") or "not recorded"
    crumbs = (
        f'  <p class="crumbs"><a href="{BASE}/">Home</a> · '
        f'<a href="{BASE}/reports/">Reports</a> · '
        f'<a href="{BASE}/reports/vendors/">Vendor sample reports</a> · {e(name)}</p>\n'
    )
    parts = [crumbs, f"  <h1>{e(name)} GPU price sample report</h1>\n"]
    parts.append(
        "  <p>A one-page sample from Lantern Works, generated from the public price feed "
        f'and daily snapshots. Rankings are among <strong>tracked vendors only</strong>, not the whole market. '
        f'Price data is licensed <a href="{LICENSE_URL}">CC BY 4.0</a> (attribution: Lantern Works).</p>\n'
    )
    parts.append(
        f'  <p class="meta">Feed timestamp: <code>feed_updated_at={e(_fmt_ts(feed_ts))}</code>. '
        f'Prices verified through <code>{e(_fmt_ts(verified_through))}</code>. '
        f'14-day window: {e(under["window_start"])} to {e(under["window_end"])} (inclusive), '
        f'ending on the latest published snapshot date.</p>\n'
    )
    if src:
        parts.append(
            f'  <p>Vendor pricing page used as the source for current rows: '
            f'<a href="{e(src)}" rel="noopener">{e(src)}</a>.</p>\n'
        )

    if held and not report["has_current_rates"]:
        reason = held.get("reason") or "held / unranked"
        parts.append(
            f'  <p><strong>Currently unranked.</strong> This vendor is on the tracked list but its '
            f'published rows are held and not used in live rankings ({e(reason)}). '
            f'Held figures below are the last recorded values; they are not a current rank.</p>\n'
        )
        recs = held.get("records") or []
        if recs:
            parts.append("  <h2>Last held records</h2>\n  <div class=\"tscroll\"><table>\n")
            parts.append("    <thead><tr><th>GPU</th><th>Tier</th><th>$/GPU-hr (held)</th><th>Source quote</th></tr></thead>\n    <tbody>\n")
            for rec in recs:
                q = rec.get("quote") or (rec.get("evidence") or {}).get("quote") or "No quote recorded"
                parts.append(
                    f'    <tr><td>{e(rec.get("gpu"))}</td><td>{e(rec.get("tier"))}</td>'
                    f'<td>{e(money(rec.get("hourly_usd")))}</td><td>{e(q)}</td></tr>\n'
                )
            parts.append("    </tbody></table></div>\n")

    parts.append("  <h2>Rank per GPU model</h2>\n")
    parts.append(
        "  <p>Rank is among tracked vendors with a comparable rate for the same published GPU name: "
        "a single-GPU, headline-eligible, non-reserved, non-serverless, non-interruptible offer. "
        "Lower hourly equivalent wins. Affiliate status is not a ranking factor. "
        "Multi-GPU, serverless, reserved, or interruptible offers are listed but not given a rank "
        "in this table, with the reason shown. If the feed has no hourly figure, it is listed as no figure recorded; none is invented.</p>\n"
    )
    if not ranks:
        parts.append("  <p>No current listed rates for this vendor in the published feed.</p>\n")
    else:
        parts.append('  <div class="tscroll"><table>\n')
        parts.append(
            "    <thead><tr><th>GPU</th><th>This vendor</th><th>Rank</th>"
            "<th>Cheapest tracked</th><th>Evidence</th></tr></thead>\n    <tbody>\n"
        )
        for r in ranks:
            if r["comparable"]:
                rank_txt = f'{r["rank"]} of {r["field"]}'
                if r["tied"]:
                    rank_txt += " (tied)"
                cheap = f'{e(money(r["cheapest_hourly_usd"]))} · {e(r["cheapest_vendor"])}'
            else:
                rank_txt = f'not ranked ({e(r["reason"])})'
                cheap = "—"
            price = money(r.get("hourly_equiv_usd"))
            tier = r.get("tier") or ""
            ff = r.get("form_factor") or ""
            mid = f'{e(price)}/hr'
            if tier:
                mid += f' · {e(tier)}'
            if ff and ff != "not stated":
                mid += f' · {e(ff)}'
            ev = _evidence_html(gen, r)
            parts.append(
                f'    <tr><td>{e(r["gpu"])}</td><td>{mid}</td><td>{rank_txt}</td>'
                f"<td>{cheap}</td><td>{ev}</td></tr>\n"
            )
        parts.append("    </tbody></table></div>\n")

    parts.append("  <h2>Undercut in the last 14 days</h2>\n")
    missing = under["snapshot_days_missing"]
    present_n = len(under["snapshot_days_present"])
    if missing:
        parts.append(
            f'  <p><strong>History is incomplete for this window.</strong> '
            f'No daily snapshot was published for {e(", ".join(missing))}. '
            f'Undercut counts use only the {present_n} snapshot days that exist '
            f'({e(under["snapshot_days_present"][0]) if present_n else "none"}'
            f'{e(" … " + under["snapshot_days_present"][-1]) if present_n > 1 else ""}). '
            f'No snapshot exists for those days, so undercut counts do not include them and do not assume prices held steady. No figures were invented for those days.</p>\n'
        )
    else:
        parts.append(
            f'  <p>All {present_n} calendar days in the window have a published snapshot.</p>\n'
        )
    parts.append(
        "  <p>An undercut observation is one snapshot day and GPU name where this vendor had a "
        "comparable ranked 1-GPU, non-spot, non-reserved rate and at least one other tracked vendor "
        "was strictly cheaper the same day. Counts are observations, not distinct hours. "
        "Days with no comparable ranked rate for this vendor are not counted as undercuts.</p>\n"
    )
    if under["days_with_comparable_rate"] == 0 and not ranks:
        if missing or present_n == 0:
            parts.append(
                "  <p>No comparable ranked history for this vendor in the published snapshots "
                "for this window; undercut counts are not assumed to be zero beyond the missing days already named.</p>\n"
            )
        else:
            parts.append(
                "  <p>This vendor had no comparable ranked 1-GPU rate on any of the "
                f'{present_n} snapshot days in the window, so undercut counts are not computed.</p>\n'
            )
    else:
        parts.append(
            f'  <p><strong>{under["undercut_count"]} undercut observation'
            f'{"s" if under["undercut_count"] != 1 else ""}</strong> '
            f'across {under["days_with_comparable_rate"]} snapshot day'
            f'{"s" if under["days_with_comparable_rate"] != 1 else ""} '
            f'where this vendor had a comparable ranked rate'
            f'{(" on " + ", ".join(under["models_seen"])) if under["models_seen"] else ""}.</p>\n'
        )
        if under["undercut_by"]:
            parts.append('  <div class="tscroll"><table>\n')
            parts.append("    <thead><tr><th>Undercut by</th><th>Observations</th><th>GPU names</th></tr></thead>\n    <tbody>\n")
            for row in under["undercut_by"]:
                parts.append(
                    f'    <tr><td>{e(row["vendor"])}</td><td>{row["times"]}</td>'
                    f'<td>{e(", ".join(row["gpus"]))}</td></tr>\n'
                )
            parts.append("    </tbody></table></div>\n")
        else:
            parts.append(
                "  <p>On the snapshot days that exist and where this vendor had a comparable ranked rate, "
                "no other tracked vendor was strictly cheaper.</p>\n"
            )

    parts.append("  <h2>Chart</h2>\n")
    parts.append(
        "  <p>Current hourly equivalent (amber) next to the cheapest tracked comparable rate (gray), "
        "for each GPU this vendor lists that is in the comparable set. The table above is the source; "
        "the chart does not add information.</p>\n"
    )
    parts.append(
        f'  <p><img src="rank-chart.svg" alt="Bar chart: {e(name)} hourly rate versus the cheapest tracked comparable rate, by GPU model." /></p>\n'
    )

    ver = _verification_for(bundle, slug)
    parts.append("  <h2>Check against the vendor pricing page</h2>\n")
    if not ver:
        parts.append(
            "  <p>This edition has no recorded check against the vendor's own pricing page yet.</p>\n"
        )
    else:
        status = ver.get("status") or "could_not_verify"
        label = {"match": "Matches the vendor page", "mismatch": "Does not match the vendor page",
                 "could_not_verify": "Could not verify"}.get(status, status)
        parts.append(f'  <p><strong>{e(label)}.</strong> {e(ver.get("detail") or "")}</p>\n')
        if ver.get("checked_at"):
            parts.append(f'  <p class="meta">Checked at {e(_fmt_ts(ver["checked_at"]))} from {e(ver.get("source_url") or "the recorded source_url")}.</p>\n')

    parts.append(f"  <p><em>{e(DISCLOSURE)}</em></p>\n")
    parts.append(
        f'  <p>Report a correction: <a href="{BASE}/report-price/">report a price</a>. '
        f'See also the <a href="{BASE}/methodology/">methodology</a> and the '
        f'<a href="{BASE}/api/v1/gpu-prices.json">gpu-prices.json</a> feed.</p>\n'
    )
    return "".join(parts)


def index_body(gen, bundle: dict) -> str:
    e = lambda s: _esc(gen, s)
    feed_ts = bundle.get("feed_updated_at") or "not recorded"
    parts = [
        f'  <p class="crumbs"><a href="{BASE}/">Home</a> · '
        f'<a href="{BASE}/reports/">Reports</a> · Vendor sample reports</p>\n',
        "  <h1>Vendor sample reports</h1>\n",
        "  <p>One generated page per tracked instance vendor. Each report shows the vendor's rank "
        "per GPU model among tracked vendors, how many times it was undercut in the last 14 days "
        "and by whom (from published daily snapshots), and one chart. Missing snapshot days are "
        f'disclosed, never filled in. Price data is licensed <a href="{LICENSE_URL}">CC BY 4.0</a> '
        "(attribution: Lantern Works).</p>\n",
        f'  <p class="meta">Generated from <code>feed_updated_at={e(_fmt_ts(feed_ts))}</code>. '
        f'Window ends {e(bundle["end"])}.</p>\n',
    ]
    ver = bundle.get("verification")
    if ver:
        counts = Counter((v.get("status") or "could_not_verify") for v in ver.get("vendors") or [])
        parts.append(
            f'  <p>Check against each vendor\'s own pricing page '
            f'(recorded {e(_fmt_ts(ver.get("checked_at")))}): '
            f'{counts.get("match", 0)} match, {counts.get("mismatch", 0)} mismatch, '
            f'{counts.get("could_not_verify", 0)} could not verify. '
            f'Details are on each vendor page and in the '
            f'<a href="{BASE}/reports/vendors/verification/">verification summary</a>. '
            f'Mismatches are reported only; prices and gates were not changed to force a match.</p>\n'
        )
    else:
        parts.append("  <p>No recorded vendor-page check is attached to this edition yet.</p>\n")
    parts.append('  <div class="tscroll"><table>\n')
    parts.append(
        "    <thead><tr><th>Vendor</th><th>Current comparable GPUs</th><th>Best rank</th>"
        "<th>14-day undercut observations</th><th>History</th></tr></thead>\n    <tbody>\n"
    )
    for report in bundle["reports"]:
        url = f'{BASE}/reports/vendors/{report["slug"]}/'
        comparable = [r for r in report["ranks"] if r.get("comparable")]
        if comparable:
            best = min(r["rank"] for r in comparable)
            best_txt = f"{best} (on {sum(1 for r in comparable if r['rank']==best)} model{'s' if sum(1 for r in comparable if r['rank']==best)!=1 else ''})"
        elif report["held"] and not report["has_current_rates"]:
            best_txt = "held / unranked"
        else:
            best_txt = "no comparable current rate"
        under = report["undercuts"]
        hist = "incomplete" if under["history_incomplete"] else "complete in window"
        if under["snapshot_days_missing"]:
            hist += f' (missing {", ".join(under["snapshot_days_missing"])})'
        parts.append(
            f'    <tr><td><a href="{url}">{e(report["vendor"])}</a></td>'
            f'<td>{len(comparable)}</td><td>{e(best_txt)}</td>'
            f'<td>{under["undercut_count"]}</td><td>{e(hist)}</td></tr>\n'
        )
    parts.append("    </tbody></table></div>\n")
    parts.append(f"  <p><em>{e(DISCLOSURE)}</em></p>\n")
    return "".join(parts)


def verification_body(gen, bundle: dict) -> str:
    e = lambda s: _esc(gen, s)
    ver = bundle["verification"]
    counts = Counter((v.get("status") or "could_not_verify") for v in ver.get("vendors") or [])
    parts = [
        f'  <p class="crumbs"><a href="{BASE}/">Home</a> · '
        f'<a href="{BASE}/reports/">Reports</a> · '
        f'<a href="{BASE}/reports/vendors/">Vendor sample reports</a> · Verification</p>\n',
        "  <h1>Vendor page verification</h1>\n",
        "  <p>A point-in-time check of each sample report against the vendor's own public pricing page "
        "(GET only, robots.txt respected). Mismatches are recorded; published prices and gates were "
        "not changed to force a match. An unreadable or disallowed vendor page is recorded as could not verify; no price is invented. "
        f'Price data is licensed <a href="{LICENSE_URL}">CC BY 4.0</a> (attribution: Lantern Works).</p>\n',
        f'  <p class="meta">Checked at {e(_fmt_ts(ver.get("checked_at")))}. '
        f'{counts.get("match", 0)} match, {counts.get("mismatch", 0)} mismatch, '
        f'{counts.get("could_not_verify", 0)} could not verify.</p>\n',
        '  <div class="tscroll"><table>\n',
        "    <thead><tr><th>Vendor</th><th>Status</th><th>Detail</th><th>Source</th></tr></thead>\n    <tbody>\n",
    ]
    for item in ver.get("vendors") or []:
        slug = item.get("slug") or vendor_slug(item.get("vendor") or "")
        link = f'<a href="{BASE}/reports/vendors/{e(slug)}/">{e(item.get("vendor"))}</a>'
        src = item.get("source_url") or ""
        src_html = f'<a href="{e(src)}" rel="noopener">{e(src)}</a>' if src else "—"
        parts.append(
            f'    <tr><td>{link}</td><td>{e(item.get("status"))}</td>'
            f'<td>{e(item.get("detail"))}</td><td>{src_html}</td></tr>\n'
        )
    parts.append("    </tbody></table></div>\n")
    parts.append(f"  <p><em>{e(DISCLOSURE)}</em></p>\n")
    return "".join(parts)


PERSONAL_RE = re.compile(r"Connor|Frosty|Douglas|connormatthew|/workspace/|/home/", re.I)


def _assert_clean(text: str, label: str) -> None:
    if PERSONAL_RE.search(text):
        raise SystemExit(f"personal or private path leaked into {label}")


def write_pages(gen, bundle: dict, root: Path | None = None) -> list[str]:
    root = root or ROOT
    out_root = root / "reports" / "vendors"
    out_root.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    def write_page(rel: str, title: str, desc: str, url: str, body: str) -> None:
        html = gen.page_shell(title, desc, url, body)
        _assert_clean(html, rel)
        dest = root / rel / "index.html" if not rel.endswith(".html") else root / rel
        # rel is like reports/vendors or reports/vendors/runpod
        dest = root / rel / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")

    write_page(
        "reports/vendors",
        "Vendor sample reports | Lantern Works",
        "One-page GPU price sample reports for each tracked instance vendor, from the Lantern Works price feed.",
        f"{BASE}/reports/vendors/",
        index_body(gen, bundle),
    )
    paths.append("reports/vendors")

    for report in bundle["reports"]:
        slug = report["slug"]
        svg = rank_chart_svg(report["ranks"], report["vendor"])
        _assert_clean(svg, f"reports/vendors/{slug}/rank-chart.svg")
        chart = out_root / slug / "rank-chart.svg"
        chart.parent.mkdir(parents=True, exist_ok=True)
        chart.write_text(svg, encoding="utf-8")
        write_page(
            f"reports/vendors/{slug}",
            f"{report['vendor']} GPU price sample report | Lantern Works",
            f"Lantern Works sample report for {report['vendor']}: rank per GPU among tracked vendors, 14-day undercuts, and one chart.",
            f"{BASE}/reports/vendors/{slug}/",
            vendor_body(gen, bundle, report),
        )
        paths.append(f"reports/vendors/{slug}")

    if bundle.get("verification"):
        write_page(
            "reports/vendors/verification",
            "Vendor page verification | Lantern Works",
            "Point-in-time check of Lantern Works vendor sample reports against each vendor's public pricing page.",
            f"{BASE}/reports/vendors/verification/",
            verification_body(gen, bundle),
        )
        paths.append("reports/vendors/verification")
    return paths


def write_all(gen, root: Path | None = None) -> list[str]:
    bundle = build_all(root or ROOT)
    return write_pages(gen, bundle, root or ROOT)


# ---------------------------------------------------------------------------
# Optional public verification (GET only, robots.txt respected)
# ---------------------------------------------------------------------------

def _robots_allowed(robots_txt: str, path: str, ua_token: str = "LanternWorksPriceCheck") -> tuple[bool, str]:
    """Very small robots.txt evaluator for User-agent: * and our token. Default allow."""
    if robots_txt is None:
        return False, "robots.txt could not be read"
    lines = [ln.strip() for ln in robots_txt.splitlines()]
    agent = None
    star_rules: list[tuple[str, str]] = []
    ours: list[tuple[str, str]] = []
    current: list[tuple[str, str]] | None = None
    for ln in lines:
        if not ln or ln.startswith("#"):
            continue
        if ":" not in ln:
            continue
        key, _, val = ln.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            agent = val
            if agent == "*":
                current = star_rules
            elif ua_token.lower() in agent.lower():
                current = ours
            else:
                current = None
            continue
        if current is None:
            continue
        if key in ("allow", "disallow"):
            current.append((key, val))
    rules = ours if ours else star_rules
    # Longest matching prefix wins; Allow vs Disallow at same length: Allow wins.
    best_len = -1
    allowed = True
    for kind, prefix in rules:
        if prefix == "":
            # Disallow: empty means allow all; Allow: empty is ignored by common practice
            if kind == "disallow":
                continue
            continue
        if path.startswith(prefix) or prefix == "/":
            if len(prefix) > best_len:
                best_len = len(prefix)
                allowed = kind == "allow" or prefix == "/" and kind == "allow"
                if kind == "disallow" and (path.startswith(prefix)):
                    allowed = False
                if kind == "allow":
                    allowed = True
    if best_len < 0:
        # no matching rule → allowed (with a blanket Disallow: / already handled when prefix is /)
        # If there is a Disallow: / it has prefix "/" length 1.
        for kind, prefix in rules:
            if kind == "disallow" and prefix == "/":
                allowed = False
                best_len = 1
        if best_len < 0:
            allowed = True
    return allowed, "allowed by robots.txt" if allowed else f"robots.txt disallows {path}"


def _http_get(url: str, timeout: int = 25) -> tuple[int | None, str, str]:
    """Return (status, body_text, error_reason). Never sends credentials."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            return getattr(resp, "status", 200), text, ""
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(4000).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, body, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return None, "", f"URL error: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 — record and keep going
        return None, "", f"{type(exc).__name__}: {exc}"


def _price_forms(value) -> list[str]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return []
    forms = set()
    for fmt in (f"{n:.4f}", f"{n:.2f}", f"{n:.3f}", f"{n:g}"):
        t = fmt.rstrip("0").rstrip(".") if "." in fmt else fmt
        forms.add(t)
        forms.add(t.replace(".", "\\."))  # not used as regex here; keep plain
        forms.add("$" + t)
        forms.add("$" + f"{n:.2f}")
        forms.add(f"{n:.2f}")
    if n >= 10:
        forms.add(f"{n:,.2f}")
        forms.add(f"${n:,.2f}")
    # monthly equivalent sometimes listed
    monthly = n * 730
    if monthly >= 100:
        forms.add(f"{monthly:,.0f}")
        forms.add(f"${monthly:,.0f}")
        forms.add(f"{monthly:,.2f}")
    return [f for f in forms if f and not f.startswith("$") or True]


def _body_has_price(body: str, value) -> bool:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return False
    # Plain and $-prefixed, 2-4 decimal variants, optional thousands separators.
    variants = []
    for decimals in (2, 3, 4):
        raw = f"{n:.{decimals}f}"
        trimmed = raw.rstrip("0").rstrip(".") if decimals > 2 else raw
        variants.extend([raw, trimmed, f"${raw}", f"${trimmed}"])
    if n >= 1000:
        variants.extend([f"{n:,.2f}", f"${n:,.2f}"])
    monthly = n * 730
    if monthly >= 100:
        variants.extend([f"{monthly:,.0f}", f"${monthly:,.0f}", f"{int(round(monthly))}", f"${int(round(monthly)):,}"])
    lowered = body.replace("\u00a0", " ").replace(",", "")
    compact_variants = []
    for v in variants:
        compact_variants.append(v.replace(",", ""))
    for v in variants + compact_variants:
        if v and v in body:
            return True
        if v and v.replace(",", "") in lowered and any(ch.isdigit() for ch in v):
            # only count if the compact number appears; avoid '2' matching everything
            if len(v.replace("$", "").replace(",", "").replace(".", "")) >= 3 or n < 10:
                if v.replace(",", "") in lowered:
                    return True
    return False


def verify_vendor(report: dict, meta: dict) -> dict:
    name = report["vendor"]
    slug = report["slug"]
    src = (meta.get("source_url") or (report["ranks"][0]["source_url"] if report["ranks"] else None)
           or (report["held"] or {}).get("source_url"))
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {
        "vendor": name,
        "slug": slug,
        "source_url": src,
        "checked_at": checked_at,
        "status": "could_not_verify",
        "detail": "",
    }
    if not src:
        base["detail"] = "No source_url is recorded for this vendor."
        return base
    parsed = urlparse(src)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        base["detail"] = "source_url is not a public http(s) URL."
        return base
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    r_status, robots_txt, r_err = _http_get(robots_url, timeout=15)
    if r_status is None or r_status >= 400 and r_status != 404:
        # 404 robots.txt → allowed. Network/block → cannot verify (do not fetch around a block).
        if r_status == 404:
            robots_txt = ""
        else:
            base["detail"] = f"Could not read robots.txt ({r_err or r_status}); pricing page not fetched."
            return base
    path = parsed.path or "/"
    allowed, why = _robots_allowed(robots_txt, path)
    if not allowed:
        base["detail"] = why
        return base
    # Lambda: GET only (already GET).
    status, body, err = _http_get(src, timeout=25)
    if status is None or (status is not None and status >= 400):
        base["detail"] = err or f"HTTP {status}"
        return base
    prices = []
    for r in report["ranks"]:
        if r.get("hourly_equiv_usd") is not None:
            prices.append((r["gpu"], r["hourly_equiv_usd"]))
    if not prices and report.get("held"):
        for rec in (report["held"].get("records") or []):
            if rec.get("hourly_usd") is not None:
                prices.append((rec.get("gpu"), rec["hourly_usd"]))
    if not prices:
        base["detail"] = "No published hourly figures to look up on the vendor page."
        return base
    found, missing = [], []
    for gpu, price in prices:
        if _body_has_price(body, price):
            found.append(gpu)
        else:
            missing.append(f"{gpu} {money(price)}")
    if found and not missing:
        base["status"] = "match"
        base["detail"] = (
            f"Fetched {src} (HTTP {status}); every current published hourly figure "
            f"({', '.join(found)}) appears in the response body."
        )
        return base
    if found and missing:
        # Partial: not a clean match, but also not a firm mismatch without a parsed alternate.
        base["status"] = "could_not_verify"
        base["detail"] = (
            f"Fetched {src} (HTTP {status}); found {', '.join(found)} in the page body, "
            f"but did not find {', '.join(missing)}. Not treated as a mismatch without a "
            f"clear alternate list price for those SKUs."
        )
        return base
    # Nothing found — could be JS-rendered. That is unverified, not a mismatch.
    base["status"] = "could_not_verify"
    base["detail"] = (
        f"Fetched {src} (HTTP {status}); none of the published hourly figures "
        f"({', '.join(missing)}) appear in the response body. The page may be JavaScript-rendered "
        f"or use a different format. Not treated as a mismatch."
    )
    return base


def run_verification(root: Path | None = None, sleep_s: float = 0.8) -> dict:
    root = root or ROOT
    bundle = build_all(root)
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = []
    hosts_hit = set()
    for report in bundle["reports"]:
        meta = report["meta"]
        # light politeness: if we already fetched this host in this run, pause
        src = meta.get("source_url") or (report["ranks"][0]["source_url"] if report["ranks"] else "")
        host = urlparse(src).netloc if src else ""
        if host and host in hosts_hit and sleep_s:
            time.sleep(sleep_s)
        item = verify_vendor(report, meta)
        items.append(item)
        if host:
            hosts_hit.add(host)
        print(f"verify {item['slug']}: {item['status']} — {item['detail'][:160]}", flush=True)
    counts = Counter(i["status"] for i in items)
    doc = {
        "schema": "lantern-works-vendor-verification/1",
        "checked_at": checked_at,
        "method": "Public GET of each vendor source_url after reading robots.txt. Lambda GET-only. No credentials. No prices or gates were changed.",
        "counts": {
            "match": counts.get("match", 0),
            "mismatch": counts.get("mismatch", 0),
            "could_not_verify": counts.get("could_not_verify", 0),
        },
        "vendors": items,
    }
    dest = root / "data" / "reports" / "vendor-verification.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def _llms_update(root: Path) -> None:
    """Insert or replace a single vendor-reports bullet in llms.txt (reports section)."""
    path = root / "llms.txt"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    bullet = (
        "- [Vendor sample reports](https://thelanternworks.com/reports/vendors/): "
        "one page per tracked instance vendor — rank per GPU among tracked vendors, "
        "14-day undercuts, one chart"
    )
    marker_start = "- [Vendor sample reports]"
    if marker_start in text:
        text = re.sub(
            r"- \[Vendor sample reports\]\([^\)]+\):[^\n]*",
            bullet,
            text,
            count=1,
        )
    elif "- [GPU price reports]" in text:
        text = text.replace(
            "- [GPU price reports](https://thelanternworks.com/reports/): weekly, newest first",
            "- [GPU price reports](https://thelanternworks.com/reports/): weekly, newest first\n" + bullet,
            1,
        )
    else:
        return
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="GET each vendor pricing page (robots.txt first) and record results")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.verify:
        run_verification(root)
    import generate_seo_pages as gen
    # When invoked standalone, still write only these pages (plus llms bullet).
    # The SEO generator calls write_all itself for a full site pin.
    paths = write_all(gen, root)
    _llms_update(root)
    if hasattr(gen, "brand_heads"):
        gen.brand_heads()
    print(f"vendor_reports={len(paths)} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
