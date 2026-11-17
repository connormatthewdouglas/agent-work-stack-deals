#!/usr/bin/env python3
"""Daily GPU + stack pricing source check (read-only; never edits prices).

Also covers data/stack_pricing/<vendor>.json (Agent Stack Optimizer offers) the same way.

For every data/gpu_pricing/<vendor>.json: validates the records, fetches each source_url and flags
pages that are unreachable, and flags records whose quoted price no longer appears on the fetched page
(possible price change: a human must re-check and update the record by hand). A record whose verified_at
is older than STALE_DAYS is a warning when the price is still on the page or the row is held — the
warning shows the last verified_at, hours old, and the threshold it passed. A stale row whose price is
also missing or has changed still fails, as strict as a fresh missing/changed row. This check never
edits prices or refreshes timestamps. Exit 1 if anything is flagged. --report FILE writes a Markdown
summary (used as the GitHub issue body by the scheduled workflow).

Geo-variant vendors (GEO_VARIANT below): some vendors serve a regional pricing page to cloud CI
runners, so a quoted price can be absent from CI while present from other networks. For a vendor listed
there ONLY, a "price not found" result is a warning ("unverifiable from CI"), not a failure, and only while
at least one other quoted price for that vendor is still found on the same page (so a broken, blocked or
redesigned page still fails). Unreachable pages and invalid records still fail as usual; staleness
alone is a warning (missing or changed prices still fail).
Vendors with a top-level "manual_snapshot" (e.g. Clore.ai) are not re-checked here: unreachable is a warning,
and a row that has passed STALE_DAYS is a warning with its true age unless the price is also missing.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Vendor pages that replace the rate line with a no-capacity line while a GPU has no capacity (Spheron RTX 5090,
# 2026-11-02: '$1.62/hr per GPU' with capacity, 'has no capacity right now ... $0.89/hr ... last rate' without).
CAPACITY_VARIANT = {"Spheron": r"On Spheron the NVIDIA {gpu} has no capacity right now"}  # refresh_gpu_prices.NO_CAPACITY marks it out of stock
GEO_VARIANT = {
    # 2026-10-27: GitHub runners get a SendPulse SMTP page without the Pro/Enterprise/Pay As You Go prices
    # that the same URL shows from other networks (checked by hand the same day: all four present).
    # No region-neutral URL or currency parameter changes this.
    "SendPulse": "regional pricing page served to CI runners; quoted prices verified from a non-CI network",
}
# Client-rendered pages (T73 F2): the server HTML carries no visible price text; the quoted price exists only as a
# literal "$x/unit" string in the page's script bundle. For a vendor listed here ONLY, a price missing from visible
# text but present as that exact "$x" string in a script is a warning ("client-rendered, not visible in server HTML"),
# never a match. A price absent from the scripts too still fails.
CLIENT_RENDERED = {
    "9Proxy": "pricing page renders client-side (Next.js); server HTML has only the title/meta, the plan prices are script strings",
}
sys.path.insert(0, str(ROOT))
from core.gpu import MIN_MARKET_OFFERS, STALE_DAYS, load_vendor_files, record_problems  # noqa: E402
from core.data_age import STALE_HOURS  # noqa: E402
from core import http_fetch, stack  # noqa: E402

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
    # Cookie-aware, host-bounded redirects: OVH's CDN 307s the same URL once
    # to set a cookie; urllib alone reports 307 and the live-check flags
    # unreachable even when the pricing page is unchanged (runs 44096997549,
    # 44097812689). Unsafe or exhausted redirects still return the last status
    # so the flag is not suppressed.
    return http_fetch.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"}, timeout=30)


MAX_UNRENDERED_AGE_DAYS = 7


def quote_age_days(doc: dict, now=None) -> float | None:
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(doc["checked_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return ((now or datetime.now(timezone.utc)) - t).total_seconds() / 86400


RENDER_ERROR = re.compile(r"Application error: a client-side exception has occurred", re.I)


def rendered_text(url: str, timeout: int = 60, tries: int = 3) -> str:
    """Visible text of a client-rendered page after headless Chrome runs its scripts. '' means the render FAILED (no
    Chrome, timeout, empty DOM, or the app's own client-side error page); callers count that as a failure, never a pass.
    Headless Chrome sometimes returns an empty DOM, so it is retried up to `tries` times. Only the outcome is logged."""
    import shutil
    import subprocess
    exe = next((shutil.which(x) for x in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser") if shutil.which(x)), None)
    if not exe:
        return ""
    for _ in range(tries):
        try:
            dom = subprocess.run([exe, "--headless=new", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=15000",
                                  f"--user-agent={UA}", "--dump-dom", url], capture_output=True, text=True, timeout=timeout).stdout
        except (subprocess.SubprocessError, OSError):
            continue
        t = visible_text(dom) if dom else ""
        if len(t) >= 500 and not RENDER_ERROR.search(t):
            return t
    return ""


def visible_text(body: str) -> str:
    """The text the daily refresh reads prices from (scripts/refresh_gpu_prices.page_text): visible text with
    script/style/noscript/svg/template and aria-hidden subtrees skipped, plus the vendor's own meta/og/JSON-LD
    descriptions. Attributes (image src/srcset, data-*, SVG path data) are never read."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from refresh_gpu_prices import page_text
    return page_text(body)


_SHOWN = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?|\.\d+)(?![\d.,]*\d)(\s?/\s?h(?:r|rs|our|ours)?(?![a-z]))?", re.I)


def price_found(token: str, quote: str, text: str) -> bool:
    """A quoted price counts only as a displayed price in visible text: '$' + the same amount (3.5 == 3.50), followed
    by '/h' (/hr, /hour) when the quote shows it that way (the $x/h pattern). A bare digit run never counts, so
    '2.248' inside SVG path data, an image path or a data attribute is not a match."""
    want = float(token.replace(",", ""))
    per_h = any(m.group(2) and float(m.group(1).replace(",", "")) == want for m in _SHOWN.finditer(quote))
    return any(float(m.group(1).replace(",", "")) == want and (m.group(2) or not per_h) for m in _SHOWN.finditer(text))


def price_tokens(quote: str) -> list[str]:
    """Numbers in the vendor quote that must still appear on the page (e.g. '3.99', '1,256.32', '0.001261')."""
    return re.findall(r"\$\s?([\d,]*\.?\d+)", quote)



def record_verified_at(record: dict, doc: dict | None = None) -> str | None:
    """The last verification stamp as stored. Never invent or refresh a timestamp."""
    v = record.get("verified_at") or record.get("checked_at")
    if not v and doc is not None:
        v = doc.get("checked_at")
    return v


def stale_age(record: dict, now: datetime, doc: dict | None = None) -> tuple[str, float, bool] | None:
    """Return (verified_at, hours_old, past_threshold) using the same cut as stale_records (age > STALE_DAYS)."""
    v = record_verified_at(record, doc)
    if not v:
        return None
    try:
        t = datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None
    age = now - t
    return v, age.total_seconds() / 3600.0, age > timedelta(days=STALE_DAYS)


def format_stale_warning(label: str, verified_at: str, hours_old: float, kind: str) -> str:
    """Honest stale warning: last verified_at, hours old, and which threshold it passed."""
    return (f"stale ({kind}): {label}: last verified_at {verified_at}, "
            f"{hours_old:.1f} h old, passed {STALE_HOURS:g} h / {STALE_DAYS} day threshold")


def _stale_kind(key: tuple, record: dict, doc: dict, present_keys: set, offline: bool) -> str:
    if record.get("stale") or doc.get("stale"):
        return "held"
    if key in present_keys:
        return "price still on the page"
    return "not re-checked on the page this run"


def evaluate_sources(docs, sdocs, *, offline: bool = False, pages=None,
                     now: datetime | None = None, fetch_fn=None,
                     check_schema: bool = True) -> tuple[list[str], list[str], int]:
    """Run the pricing-source check over `docs` / `sdocs`.

    Missing or changed prices stay flags (failures). A row that is only past the
    STALE_DAYS threshold (price still on the page, or the row is held / not
    re-checked) is a warning that reports the true verified_at age. Timestamps
    are never refreshed. `pages` maps URL -> (status, body) so tests can inject
    fixtures without fetching.
    """
    now = now or datetime.now(timezone.utc)
    get = fetch_fn or fetch
    flags: list[str] = []
    warnings: list[str] = []
    present_keys: set[tuple] = set()
    price_fail_keys: set[tuple] = set()
    if check_schema:
        for doc in docs:
            flags += [f"invalid record: {p}" for p in record_problems(doc)]
    checked = 0
    injected = set((pages or {}))
    pages = dict(pages or {})
    if not offline:
        for doc in docs:
            urls = {doc["source_url"]} | {r["source_url"] for r in doc["records"] if r.get("batch") != "wider-gpu"}  # API calls, not pages
            for u in sorted(urls):
                first = u not in pages
                if first:
                    pages[u] = get(u)
                st, body = pages[u]
                if first:
                    print(f"{doc['vendor']}: {u} -> {st if st else body}")
                # Same as before on a live fetch: only the first vendor to request a URL is flagged.
                # Fixture pages (tests) start already in `pages`, so still record unreachable for that vendor.
                if st != 200 and (first or u in injected):
                    msg = f"unreachable: {doc['vendor']} {u} -> {st if st else body}"
                    if msg not in flags and msg not in warnings:
                        (warnings if doc.get("manual_snapshot") else flags).append(msg)
                    if u in injected:
                        injected.discard(u)  # one flag per injected URL, matching live first-writer behavior
            for r in doc["records"]:
                key = (doc["vendor"], r.get("gpu"), r.get("tier"), r.get("quote"), r.get("source_url"))
                if r.get("batch") == "wider-gpu":
                    warnings.append(f"Scout API batch, not re-checked on page: {doc['vendor']} {r['gpu']} (verified {r['checked_at']})")
                    continue
                st, body = pages[r["source_url"]]
                if st != 200:
                    continue
                checked += 1
                if r.get("batch") == "wider-gpu":
                    # Scout wider-GPU batch: priced from vendor APIs (source_url names the API call), re-verified by Scout's
                    # own cycle; not re-found on the HTML pricing page. Auto-holds after STALE_DAYS like any record.
                    warnings.append(f"Scout API batch, not re-checked on page: {doc['vendor']} {r['gpu']} (verified {r['checked_at']})")
                    continue
                if doc.get("manual_snapshot"):
                    # Manual snapshot (e.g. Clore.ai, whose API 401s CI runners): not re-checked here; a row past
                    # STALE_DAYS is a warning with its true age (add_stale_warnings), not a failure, unless a
                    # missing/changed price is also detected on a path that does re-check.
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
                text = visible_text(body)
                missing = [t for t in price_tokens(r["quote"]) if not price_found(t, r["quote"], text)]
                if missing:
                    # Gauge spheron84: rotating-snapshot rows (Spheron /pricing/ rotates RAM/vCPU/NVMe per read) are
                    # matched on GPU name + VRAM + '$X /hr' only; the full quote stays as display evidence.
                    from refresh_gpu_prices import is_rotating, parse_rotating
                    if is_rotating(r, doc["vendor"]):
                        v = parse_rotating(r, text)[0]
                        if v is not None and abs(float(v) - r["hourly_usd"]) < 1e-9:
                            missing = []
                if missing and r.get("price_rotates"):
                    # T87 follow-up: the vendor rotates this row's price over the day, so the exact amount is not
                    # required; the GPU name + VRAM + a '$X /hr' price must still be on the page.
                    from refresh_gpu_prices import rotating_regex
                    if rotating_regex(r["gpu"], r.get("vram_gb")).search(text):
                        warnings.append(f"rotating marketplace price, exact amount not required: {doc['vendor']} {r['gpu']} "
                                        f"(listed ${r['hourly_usd']}, verified {r.get('verified_at') or r['checked_at']})")
                        continue
                cv = CAPACITY_VARIANT.get(doc["vendor"])
                if missing and cv and re.search(cv.format(gpu=re.escape(r["gpu"])), text):
                    # the vendor's page swaps its rate line for a no-capacity line while capacity is out; that is
                    # a stock signal, not a price change (the refresh keeps the last sourced price; age past
                    # STALE_DAYS is a warning via add_stale_warnings, not a silent pass)
                    warnings.append(f"vendor page shows no capacity right now, rate line absent: {doc['vendor']} {r['gpu']} "
                                    f"quote {r['quote']!r} (verified {r.get('verified_at') or r['checked_at']}) at {r['source_url']}")
                    continue
                if missing:
                    flags.append(f"price not found on page (re-check by hand): {doc['vendor']} {r['gpu']} "
                                 f"({r['tier']}) quote {r['quote']!r} missing {missing} at {r['source_url']}")
                    price_fail_keys.add(key)
                else:
                    present_keys.add(key)
    if check_schema:
        for doc in sdocs:
            flags += [f"invalid stack record: {p}" for p in stack.record_problems(doc)]
    if not offline:
        for doc in sdocs:
            u = doc["source_url"]
            if u not in pages:
                pages[u] = get(u)
                print(f"{doc['vendor']}: {u} -> {pages[u][0] or pages[u][1]}")
            st, body = pages[u]
            if st != 200:
                flags.append(f"unreachable: {doc['vendor']} {u} -> {st if st else body}")
                continue
            text = visible_text(body)
            miss = []
            found = []
            for o in doc["offers"]:
                checked += 1
                key = (doc["vendor"], o.get("need"), o.get("plan"), o.get("quote"), u)
                missing = [t for t in price_tokens(o["quote"]) if not price_found(t, o["quote"], text)]
                if missing:
                    miss.append(f"price not found on page (re-check by hand): {doc['vendor']} {o['need']} "
                                f"({o['plan']}) quote {o['quote']!r} missing {missing} at {u}")
                else:
                    found.append(key)
            if miss and doc["vendor"] in CLIENT_RENDERED:
                # Gauge T73 F1-F6 #7: render the page headless and read the prices a visitor sees; the i18n script
                # strings alone are labels, not plan data, so they never pass a quote on their own
                rtext = rendered_text(u)
                if rtext:
                    miss = [m for o in doc["offers"] for m in miss if o["quote"] in m
                            and any(not price_found(t, o["quote"], rtext) for t in price_tokens(o["quote"]))]
                    if not miss:
                        print(f"{doc['vendor']}: prices found in the rendered page (headless Chrome)")
                        found = [(doc["vendor"], o.get("need"), o.get("plan"), o.get("quote"), u) for o in doc["offers"]]
                else:
                    # Gauge T73 fix7 #2: a render error is a failure, never a silent fallback to the server HTML
                    flags.append(f"headless render failed (empty DOM or client-side error page): {doc['vendor']} {u}")
                    miss = []
            if miss and doc["vendor"] in CLIENT_RENDERED:
                age = quote_age_days(doc, now)
                if age is not None and age > MAX_UNRENDERED_AGE_DAYS:  # warning-only stops at 7 days
                    flags += [f"client-rendered quote not re-verified for {age:.1f} days (> {MAX_UNRENDERED_AGE_DAYS}; "
                              f"checked_at {doc['checked_at']}) and not found in a headless render: {m}" for m in miss]
                    miss = []
                in_script = [m for o in doc["offers"] for m in miss if o["quote"] in m
                             and all(re.search(r"\$\s?" + re.escape(t) + r"(?![\d.])", body) for t in price_tokens(o["quote"]))]
                warnings += [f"client-rendered, not visible in server HTML ({CLIENT_RENDERED[doc['vendor']]}): {m}" for m in in_script]
                miss = [m for m in miss if m not in in_script]
            if miss and doc["vendor"] in GEO_VARIANT and len(miss) < len(doc["offers"]):
                warnings += [f"unverifiable from CI ({GEO_VARIANT[doc['vendor']]}): {m}" for m in miss]
            else:
                flags += miss
                for m, o in ((m, o) for o in doc["offers"] for m in miss if o["quote"] in m):
                    price_fail_keys.add((doc["vendor"], o.get("need"), o.get("plan"), o.get("quote"), u))
            present_keys.update(found)
            # offers that ended in miss were not present
            for o in doc["offers"]:
                key = (doc["vendor"], o.get("need"), o.get("plan"), o.get("quote"), u)
                if any(o["quote"] in m for m in miss):
                    present_keys.discard(key)
    # Gauge re32: a single vendor timing out (after the retry) is a warning, not a failure; two or more still fail.
    tmo = [f for f in flags if f.startswith("unreachable:") and re.search(r"time(d)? ?out", f, re.I)]
    if len({(re.search(r"https?://([^/ ]+)", f) or re.search(r"(.*)", f)).group(1) for f in tmo}) == 1:
        flags = [f for f in flags if f not in tmo]
        warnings += [f"single vendor timeout tolerated: {f}" for f in tmo]
    add_stale_warnings(docs, sdocs, flags, warnings, now, present_keys, offline, price_fail_keys)
    return flags, warnings, checked


def add_stale_warnings(docs, sdocs, flags, warnings, now, present_keys, offline, price_fail_keys) -> None:
    """Recategorize age-only rows as warnings. Missing or changed prices already in flags stay failures."""

    def emit(doc, record, name, plan, url, quote):
        info = stale_age(record, now, doc)
        if not info:
            return
        v, hours, past = info
        if not past:
            return
        key = (doc["vendor"], name, plan, quote, url)
        if key in price_fail_keys:
            return  # missing/changed stays a FAIL; do not demote it to a stale warning
        kind = _stale_kind(key, record, doc, present_keys, offline)
        label = f"{doc['vendor']} {name} ({plan})"
        warnings.append(format_stale_warning(label, v, hours, kind))

    for doc in docs:
        for r in doc.get("records") or []:
            emit(doc, r, r.get("gpu"), r.get("tier"), r.get("source_url"), r.get("quote"))
    for doc in sdocs:
        for o in doc.get("offers") or []:
            rec = {**o, "gpu": o["need"], "tier": o["plan"], "checked_at": o.get("checked_at") or doc["checked_at"]}
            emit(doc, rec, o.get("need"), o.get("plan"), doc.get("source_url"), o.get("quote"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    ap.add_argument("--offline", action="store_true", help="schema + staleness only, no fetches")
    a = ap.parse_args()
    docs = load_vendor_files()
    sdocs = stack.load_vendor_files()
    flags, warnings, checked = evaluate_sources(docs, sdocs, offline=a.offline)
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
                "`data/gpu_pricing/<vendor>.json` (price and `checked_at`) by hand. A stale warning reports the last verified_at and hours old; it is not a failure unless the price is also missing or has changed.", ""]
        body += [f"- {f}" for f in flags] or ["- none"]
        if warnings:
            body += ["", "Warnings (not failures; stale rows whose price is still on the page or held, geo-variant vendors, re-check from a non-CI network):"] + [f"- {w}" for w in warnings]
        Path(a.report).write_text("\n".join(body) + "\n", encoding="utf-8")
    return 1 if flags else 0



if __name__ == "__main__":
    sys.exit(main())
