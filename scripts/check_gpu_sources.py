#!/usr/bin/env python3
"""Daily GPU + stack pricing source check (read-only; never edits prices).

Also covers data/stack_pricing/<vendor>.json (Agent Stack Optimizer offers) the same way.

For every data/gpu_pricing/<vendor>.json: validates the records, flags records whose checked_at is
older than 7 days, fetches each source_url and flags pages that are unreachable, and flags records whose
quoted price no longer appears on the fetched page (possible price change: a human must re-check and
update the record by hand). Exit 1 if anything is flagged. --report FILE writes a Markdown summary
(used as the GitHub issue body by the scheduled workflow).

Geo-variant vendors (GEO_VARIANT below): some vendors serve a regional pricing page to cloud CI
runners, so a quoted price can be absent from CI while present from other networks. For a vendor listed
there ONLY, a "price not found" result is a warning ("unverifiable from CI"), not a failure, and only while
at least one other quoted price for that vendor is still found on the same page (so a broken, blocked or
redesigned page still fails). Unreachable pages, invalid records and staleness still fail as usual.
Vendors with a top-level "manual_snapshot" (e.g. Clore.ai) are not re-checked here: unreachable is a warning,
and staleness still holds them after STALE_DAYS.
A ranked marketplace record that is momentarily below MIN_MARKET_OFFERS is also only a warning: the daily
refresh auto-holds it (and releases it again at 5+ offers). Warnings appear in the output and report; re-check them from a non-CI network
(`python3 scripts/check_gpu_sources.py` on another machine) before changing any price.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEO_VARIANT = {
    # 2026-10-27: GitHub runners get a SendPulse SMTP page without the Pro/Enterprise/Pay As You Go prices
    # that the same URL shows from other networks (checked by hand the same day: all four present).
    # No region-neutral URL or currency parameter changes this.
    "SendPulse": "regional pricing page served to CI runners; quoted prices verified from a non-CI network",
}
sys.path.insert(0, str(ROOT))
from core.gpu import MIN_MARKET_OFFERS, STALE_DAYS, load_vendor_files, record_problems, stale_records  # noqa: E402
from core import stack  # noqa: E402

UA = "Mozilla/5.0 (compatible; LanternWorksPriceCheck/1.0; +https://thelanternworks.com/for-agents/)"


def fetch(url: str) -> tuple[int | None, str]:
    """Gauge re32: one retry on a network error or 5xx before a page counts as unreachable."""
    st, body = _fetch(url)
    if st is None or st >= 500:
        import time
        time.sleep(5)
        st, body = _fetch(url)
    return st, body


def _fetch(url: str) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # DNS, TLS, timeout, refused
        return None, f"{type(e).__name__}: {e}"


def price_tokens(quote: str) -> list[str]:
    """Numbers in the vendor quote that must still appear on the page (e.g. '3.99', '1,256.32', '0.001261')."""
    return re.findall(r"\$\s?([\d,]*\.?\d+)", quote)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    ap.add_argument("--offline", action="store_true", help="schema + staleness only, no fetches")
    a = ap.parse_args()
    docs = load_vendor_files()
    flags: list[str] = []
    warnings: list[str] = []
    for doc in docs:
        flags += [f"invalid record: {p}" for p in record_problems(doc)]
    # Vendors held out as stale (doc["stale"]) are never ranked, so their record age isn't a live-site failure.
    flags += [f"stale (> {STALE_DAYS} days): {s}" for s in stale_records([d for d in docs if not d.get("stale")])]
    checked = 0
    if not a.offline:
        pages: dict[str, tuple[int | None, str]] = {}
        for doc in docs:
            urls = {doc["source_url"]} | {r["source_url"] for r in doc["records"]}
            for u in sorted(urls):
                if u not in pages:
                    pages[u] = fetch(u)
                    st, body = pages[u]
                    print(f"{doc['vendor']}: {u} -> {st if st else body}")
                    if st != 200:
                        (warnings if doc.get("manual_snapshot") else flags).append(
                            f"unreachable: {doc['vendor']} {u} -> {st if st else body}")
            for r in doc["records"]:
                st, body = pages[r["source_url"]]
                if st != 200:
                    continue
                checked += 1
                if doc.get("manual_snapshot"):
                    # Manual snapshot (e.g. Clore.ai, whose API 401s CI runners): not re-checked here; the record
                    # auto-holds after STALE_DAYS unless a person re-snapshots it.
                    warnings.append(f"manual snapshot, not re-checked from CI: {doc['vendor']} {r['gpu']} (checked {r['checked_at']})")
                    continue
                if r.get("price_status") == "marketplace":
                    # Host-set prices move minute to minute: exact figures can't be re-found. Require live offers
                    # and report today's median for a human re-check instead.
                    try:
                        offers = json.loads(body).get("offers") or []
                        per = sorted(o["dph_total"] / max(1, o.get("num_gpus") or 1) for o in offers
                                     if o.get("verified", True) and o.get("verification", "verified") == "verified"
                                     and not o.get("is_bid") and o.get("rentable", True) and not o.get("rented")
                                     and o.get("gpu_ram") and round(o["gpu_ram"] / 1024) == r["vram_gb"])
                    except (ValueError, KeyError, TypeError, AttributeError):
                        per = None
                    if per is None:
                        flags.append(f"marketplace source not parseable: {doc['vendor']} {r['gpu']} at {r['source_url']}")
                    elif not per:
                        flags.append(f"marketplace has no live offers: {doc['vendor']} {r['gpu']} at {r['source_url']}")
                    else:
                        print(f"  {doc['vendor']} {r['gpu']} {r['vram_gb']} GB verified on-demand: live {len(per)} offers, "
                              f"min ${per[0]:.4f}, median ${statistics.median(per):.4f} (published median ${r['hourly_usd']})")
                        if r.get("stale"):
                            print(f"  held (not ranked): {r['stale']['reason']}")
                        elif len(per) < MIN_MARKET_OFFERS:
                            # Expected market churn: refresh_gpu_prices.py auto-holds the record at its next run
                            # (and releases it at 5+ offers), so this is a warning, not a failure.
                            warnings.append(f"marketplace thin right now, auto-held at next refresh ({len(per)} < {MIN_MARKET_OFFERS} offers): "
                                         f"{doc['vendor']} {r['gpu']} {r['vram_gb']} GB at {r['source_url']}")
                    continue
                if r.get("stale"):
                    # Held records are not shown or ranked; a missing quote is expected (e.g. row removed by the vendor).
                    warnings.append(f"held, not re-checked: {doc['vendor']} {r['gpu']} ({r['tier']}): {r['stale']['reason']}")
                    continue
                text = " ".join(re.sub(r"<[^>]+>", " ", body).split()) + body
                missing = [t for t in price_tokens(r["quote"]) if t not in text]
                if missing:
                    flags.append(f"price not found on page (re-check by hand): {doc['vendor']} {r['gpu']} "
                                 f"({r['tier']}) quote {r['quote']!r} missing {missing} at {r['source_url']}")
    sdocs = stack.load_vendor_files()
    for doc in sdocs:
        flags += [f"invalid stack record: {p}" for p in stack.record_problems(doc)]
    flags += [f"stale (> {STALE_DAYS} days): {s}" for s in stale_records(
        [{"vendor": d["vendor"], "checked_at": d["checked_at"], "records": [{**o, "gpu": o["need"], "tier": o["plan"],
          "checked_at": o.get("checked_at") or d["checked_at"]} for o in d["offers"]]} for d in sdocs])]
    if not a.offline:
        for doc in sdocs:
            u = doc["source_url"]
            if u not in pages:
                pages[u] = fetch(u)
                print(f"{doc['vendor']}: {u} -> {pages[u][0] or pages[u][1]}")
            st, body = pages[u]
            if st != 200:
                flags.append(f"unreachable: {doc['vendor']} {u} -> {st if st else body}")
                continue
            text = " ".join(re.sub(r"<[^>]+>", " ", body).split()) + body
            miss = []
            for o in doc["offers"]:
                checked += 1
                missing = [t for t in price_tokens(o["quote"]) if t not in text]
                if missing:
                    miss.append(f"price not found on page (re-check by hand): {doc['vendor']} {o['need']} "
                                f"({o['plan']}) quote {o['quote']!r} missing {missing} at {u}")
            if miss and doc["vendor"] in GEO_VARIANT and len(miss) < len(doc["offers"]):
                warnings += [f"unverifiable from CI ({GEO_VARIANT[doc['vendor']]}): {m}" for m in miss]
            else:
                flags += miss
    # Gauge re32: a single vendor timing out (after the retry) is a warning, not a failure; two or more still fail.
    tmo = [f for f in flags if f.startswith("unreachable:") and re.search(r"time(d)? ?out", f, re.I)]
    if len({(re.search(r"https?://([^/ ]+)", f) or re.search(r"(.*)", f)).group(1) for f in tmo}) == 1:
        flags = [f for f in flags if f not in tmo]
        warnings += [f"single vendor timeout tolerated: {f}" for f in tmo]
    n = sum(len(d["records"]) for d in docs) + sum(len(d["offers"]) for d in sdocs)
    summary = f"{len(docs) + len(sdocs)} vendor files, {n} records, {checked} prices re-found on live pages, {len(flags)} flag(s), {len(warnings)} warning(s)"
    print(summary)
    for f in flags:
        print("FLAG:", f)
    for w in warnings:
        print("WARNING:", w)
    if a.report:
        body = [f"Daily GPU pricing source check: {summary}.", "",
                "Prices change only where scripts/refresh_gpu_prices.py parses them (daily). Re-check each flagged record on its source page, then update "
                "`data/gpu_pricing/<vendor>.json` (price and `checked_at`) by hand.", ""]
        body += [f"- {f}" for f in flags] or ["- none"]
        if warnings:
            body += ["", "Warnings (not failures; geo-variant vendors, re-check from a non-CI network):"] + [f"- {w}" for w in warnings]
        Path(a.report).write_text("\n".join(body) + "\n", encoding="utf-8")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
