#!/usr/bin/env python3
"""Daily GPU pricing source check (read-only; never edits prices).

For every data/gpu_pricing/<vendor>.json: validates the records, flags records whose checked_at is
older than 7 days, fetches each source_url and flags pages that are unreachable, and flags records whose
quoted price no longer appears on the fetched page (possible price change: a human must re-check and
update the record by hand). Exit 1 if anything is flagged. --report FILE writes a Markdown summary
(used as the GitHub issue body by the scheduled workflow).
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.gpu import STALE_DAYS, load_vendor_files, record_problems, stale_records  # noqa: E402

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
    flags += [f"stale (> {STALE_DAYS} days): {s}" for s in stale_records(docs)]
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
                text = " ".join(re.sub(r"<[^>]+>", " ", body).split()) + body
                missing = [t for t in price_tokens(r["quote"]) if t not in text]
                if missing:
                    flags.append(f"price not found on page (re-check by hand): {doc['vendor']} {r['gpu']} "
                                 f"({r['tier']}) quote {r['quote']!r} missing {missing} at {r['source_url']}")
    n = sum(len(d["records"]) for d in docs)
    summary = f"{len(docs)} vendor files, {n} records, {checked} prices re-found on live pages, {len(flags)} flag(s)"
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
