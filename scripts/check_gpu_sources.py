#!/usr/bin/env python3
"""Daily GPU + stack pricing source check (read-only; never edits prices).

Also covers data/stack_pricing/<vendor>.json (Agent Stack Optimizer offers) the same way.

For every data/gpu_pricing/<vendor>.json: validates the records, flags records whose checked_at is
older than 7 days, fetches each source_url and flags pages that are unreachable, and flags records whose
quoted price no longer appears on the fetched page (possible price change: a human must re-check and
update the record by hand). Exit 1 if anything is flagged. --report FILE writes a Markdown summary
(used as the GitHub issue body by the scheduled workflow).
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
sys.path.insert(0, str(ROOT))
from core.gpu import STALE_DAYS, load_vendor_files, record_problems, stale_records  # noqa: E402
from core import stack  # noqa: E402

UA = "Mozilla/5.0 (compatible; LanternWorksPriceCheck/1.0; +https://thelanternworks.com/for-agents/)"


def fetch(url: str) -> tuple[int | None, str]:
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
                        flags.append(f"unreachable: {doc['vendor']} {u} -> {st if st else body}")
            for r in doc["records"]:
                st, body = pages[r["source_url"]]
                if st != 200:
                    continue
                checked += 1
                if r.get("price_status") == "marketplace":
                    # Host-set prices move minute to minute: exact figures can't be re-found. Require live offers
                    # and report today's median for a human re-check instead.
                    try:
                        offers = json.loads(body).get("offers") or []
                        per = sorted(o["dph_total"] / max(1, o.get("num_gpus") or 1) for o in offers)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        per = None
                    if per is None:
                        flags.append(f"marketplace source not parseable: {doc['vendor']} {r['gpu']} at {r['source_url']}")
                    elif not per:
                        flags.append(f"marketplace has no live offers: {doc['vendor']} {r['gpu']} at {r['source_url']}")
                    else:
                        print(f"  {doc['vendor']} {r['gpu']}: live {len(per)} offers, min ${per[0]:.4f}, "
                              f"median ${statistics.median(per):.4f} (published median ${r['hourly_usd']})")
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
            for o in doc["offers"]:
                checked += 1
                missing = [t for t in price_tokens(o["quote"]) if t not in text]
                if missing:
                    flags.append(f"price not found on page (re-check by hand): {doc['vendor']} {o['need']} "
                                 f"({o['plan']}) quote {o['quote']!r} missing {missing} at {u}")
    n = sum(len(d["records"]) for d in docs) + sum(len(d["offers"]) for d in sdocs)
    summary = f"{len(docs) + len(sdocs)} vendor files, {n} records, {checked} prices re-found on live pages, {len(flags)} flag(s)"
    print(summary)
    for f in flags:
        print("FLAG:", f)
    if a.report:
        body = [f"Daily GPU pricing source check: {summary}.", "",
                "Prices are never edited automatically. Re-check each flagged record on its source page, then update "
                "`data/gpu_pricing/<vendor>.json` (price and `checked_at`) by hand.", ""]
        body += [f"- {f}" for f in flags] or ["- none"]
        Path(a.report).write_text("\n".join(body) + "\n", encoding="utf-8")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
