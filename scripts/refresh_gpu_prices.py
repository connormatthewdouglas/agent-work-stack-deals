#!/usr/bin/env python3
"""Daily GPU price refresh (run by .github/workflows/gpu-refresh.yml).

For each tracked record in data/gpu_pricing/<vendor>.json, re-read the vendor's own public pricing page/API and
update the price ONLY where it was actually parsed:

* Listed prices: the record's last evidence quote is turned into a pattern (its words must appear in the same
  order on today's page, prices become capture groups). The record's price is updated only if that context is
  found and gives exactly one value. The new evidence {source_url, quote, checked_at} is the matched page text.
* Marketplace medians (Vast.ai): the same public offers API and filter as before (verified, rentable, not rented,
  on-demand, exact VRAM, per GPU); a median is published only with >= MIN_MARKET_OFFERS offers.
* Anything unreadable keeps its old price and verified_at; checked_at records the attempt. A rate not verified for
  STALE_DAYS gets an automatic hold (stale.auto = true): listed under held_stale, never ranked or "verified",
  until a later run parses it again.
* Manual holds (vendor-level stale such as TensorDock, record-level holds without auto) are left untouched.
* Marketplace (Vast) records use the automatic rule: held (stale.auto) below MIN_MARKET_OFFERS qualifying offers,
  released with a fresh median, quote and checked_at once MIN_MARKET_OFFERS+ return.
* A change larger than MAX_AUTO_CHANGE_PCT is not applied automatically (flagged for a human instead).

Politeness: robots.txt is honoured, one request per URL per run, REQUEST_GAP_S between requests, plain UA that
identifies Lantern Works and links the repo. Then today's snapshot is written (data/gpu_pricing/snapshots/).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.gpu import HOURS_PER_MONTH, MAX_QUOTE, MIN_MARKET_OFFERS, PRICING_DIR, STALE_DAYS  # noqa: E402
from core import gpu_history  # noqa: E402

UA = "LanternWorksPriceCheck/1.1 (+https://github.com/connormatthewdouglas/agent-work-stack-deals)"
REQUEST_GAP_S = 3.0
MAX_AUTO_CHANGE_PCT = 50.0
PRICE_RE = re.compile(r"\$\s?([\d,]*\.?\d+)")
FACTOR = {"per-second": 3600, "hourly": 1, "monthly": 1 / HOURS_PER_MONTH}


def _walk_desc(o, out: list) -> None:
    """JSON-LD (the vendor's own structured data): collect every 'description' string."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "description" and isinstance(v, str):
                out.append(v)
            else:
                _walk_desc(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_desc(v, out)


class _Text(HTMLParser):
    """Visible text (skips script/style/svg and aria-hidden subtrees) + meta/og/JSON-LD descriptions."""
    SKIP = {"script", "style", "noscript", "svg", "template"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.meta, self.skip, self.ld = [], [], 0, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("name") or a.get("property") or "").lower() in ("description", "og:description"):
            self.meta.append(a.get("content") or "")
        if tag in self.VOID:
            return
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self.ld = []
        if self.skip or tag in self.SKIP or (a.get("aria-hidden") or "").lower() == "true":
            self.skip += 1

    def handle_startendtag(self, tag, attrs):
        if tag == "meta":
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "script" and self.ld is not None:
            try:
                _walk_desc(json.loads("".join(self.ld)), self.meta)
            except ValueError:
                pass
            self.ld = None
        if tag not in self.VOID and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.ld is not None:
            self.ld.append(data)
        if not self.skip:
            self.parts.append(data)


def page_text(body: str) -> str:
    p = _Text()
    try:
        p.feed(body)
        p.close()
    except Exception:
        pass
    norm = lambda s: " ".join(s.replace("\u2060", "").split())
    return norm(" ".join(p.parts)) + " || " + " || ".join(norm(m) for m in p.meta)


def quote_pattern(quote: str) -> tuple[re.Pattern, list[str]]:
    """Regex from an evidence quote: words literal (any whitespace between), each $price a capture group."""
    q = " ".join(quote.replace("\u2060", "").split())
    parts, prices, pos = [], [], 0
    for m in PRICE_RE.finditer(q):
        parts.append(q[pos:m.start()])
        prices.append(m.group(1))
        pos = m.end()
    parts.append(q[pos:])
    lit = lambda s: r"\s*".join(re.escape(w) for w in s.split())
    rx = ""
    for i, part in enumerate(parts):
        rx += lit(part)
        if i < len(prices):
            rx += r"\s*\$\s?([\d,]*\.?\d+)\s*"
    return re.compile(rx), prices


def _shape(q: str) -> str:
    return " ".join(PRICE_RE.sub("$", q or "").split())


def _current_quote(display: str, matched: str | None, old, new_s: str) -> str:
    """Display quote after a check: when it is the same line as the page match (same words, prices aside), use the
    page text so every price on it is current; otherwise swap just this record's price."""
    if matched and r_shape_eq(display, matched):
        return matched
    return display if float(new_s) == old else _swap_quote_price(display, old, new_s)


def r_shape_eq(a: str, b: str) -> bool:
    return _shape(a) == _shape(b)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def price_index(r: dict, quote: str) -> int | None:
    """Which $ figure in the evidence quote is this record's price (by value; tier words break ties)."""
    _, prices = quote_pattern(quote)
    idx = [i for i, p in enumerate(prices) if abs(_num(p) - r["price_usd"]) < 1e-9]
    if len(idx) == 1:
        return idx[0]
    if len(idx) > 1:
        q = " ".join(quote.split())
        segs = PRICE_RE.split(q)[0::2]  # literal text before each price
        tw = (r.get("tier") or "").split()[0].lower() if r.get("tier") else ""
        hit = [i for i in idx if tw and tw in segs[i].lower().split()[-3:]]
        if len(hit) == 1:
            return hit[0]
    return None


def parse_listed(r: dict, text: str) -> tuple[str | None, str | None, str]:
    """-> (new price string, matched quote, message). price None = unreadable."""
    quote = r["evidence"]["quote"]
    rx, _ = quote_pattern(quote)
    i = price_index(r, quote)
    if i is None:
        return None, None, "evidence quote does not identify this record's price"
    vals, quotes = set(), []
    for m in rx.finditer(text):
        vals.add(_num(m.group(i + 1)))
        quotes.append(" ".join(m.group(0).split()))
    if not vals:
        return None, None, "quoted context not found on page"
    if len(vals) > 1:
        return None, None, f"ambiguous: {len(vals)} different values for the same context"
    m = next(rx.finditer(text))
    return m.group(i + 1).replace(",", ""), quotes[0][:MAX_QUOTE], "parsed"


def market_stats(body: str, vram_gb: int) -> list[float] | None:
    try:
        offers = json.loads(body).get("offers") or []
        return sorted(o["dph_total"] / max(1, o.get("num_gpus") or 1) for o in offers
                      if o.get("verified", True) and o.get("verification", "verified") == "verified"
                      and not o.get("is_bid") and o.get("rentable", True) and not o.get("rented")
                      and o.get("gpu_ram") and round(o["gpu_ram"] / 1024) == vram_gb)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


class Fetcher:
    def __init__(self, gap: float = REQUEST_GAP_S):
        self.gap, self.last, self.cache, self.robots = gap, 0.0, {}, {}

    def allowed(self, url: str) -> bool:
        host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
            try:
                st, body = self._get(host + "/robots.txt")
                rp.parse(body.splitlines() if st == 200 else [])
                if st in (401, 403):
                    rp.disallow_all = True
            except Exception:
                rp.parse([])
            self.robots[host] = rp
        return self.robots[host].can_fetch(UA, url)

    def _get(self, url: str) -> tuple[int | None, str]:
        wait = self.gap - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json,*/*"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception as e:
            return None, f"{type(e).__name__}"

    def get(self, url: str) -> tuple[int | None, str]:
        if url not in self.cache:
            self.cache[url] = (None, "disallowed by robots.txt") if not self.allowed(url) else self._get(url)
        return self.cache[url]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _set_price(r: dict, new: float) -> None:
    n = r.get("gpu_count", 1)
    r["price_usd"] = new
    r["hourly_usd"] = round(new * FACTOR[r["billing_unit"]] / n, 4)
    if n > 1:
        r["server_hourly_usd"] = round(new * FACTOR[r["billing_unit"]], 4)


def _swap_quote_price(quote: str, old: float, new_s: str) -> str:
    for m in PRICE_RE.finditer(quote):
        if abs(_num(m.group(1)) - old) < 1e-9:
            fmt = f"{float(new_s):,.{len(new_s.split('.')[1]) if '.' in new_s else 0}f}" if "," in m.group(1) else new_s
            return quote[:m.start(1)] + fmt + quote[m.end(1):]
    return quote


def refresh(docs: list[dict], fetcher, now: datetime, stale_days: int = STALE_DAYS) -> list[dict]:
    """Mutates docs in place. Returns one result row per record (for the run report)."""
    stamp, report = _iso(now), []
    for doc in docs:
        if doc.get("stale"):
            report += [{"vendor": doc["vendor"], "gpu": r["gpu"], "tier": r["tier"], "result": "held (vendor-level, untouched)"}
                       for r in doc["records"]]
            continue
        for r in doc["records"]:
            row = {"vendor": doc["vendor"], "gpu": r["gpu"], "tier": r["tier"], "old": r["hourly_usd"]}
            r.setdefault("verified_at", r["evidence"]["checked_at"])
            manual_hold = r.get("stale") and not r["stale"].get("auto")
            st, body = fetcher.get(r["source_url"])
            new_s, quote, msg = None, None, ""
            if st != 200:
                msg = f"unreachable ({st or body})"
            elif r.get("price_status") == "marketplace":
                per = market_stats(body, r["vram_gb"])
                if per is None:
                    msg = "marketplace API not parseable"
                elif manual_hold:
                    msg = f"held (manual); live {len(per)} offers"
                elif len(per) < MIN_MARKET_OFFERS:
                    msg = f"marketplace too thin ({len(per)} < {MIN_MARKET_OFFERS} offers)"
                    r["stale"] = {"reason": f"Marketplace too thin to publish: {len(per)} verified rentable on-demand "
                                            f"{r['gpu']} {r['vram_gb']}GB offers at {stamp} (need {MIN_MARKET_OFFERS}).", "auto": True}
                else:
                    med, lo = round(statistics.median(per), 4), round(per[0], 4)
                    name = re.search(r"%22gpu_name%22%3A%7B%22eq%22%3A%22(.*?)%22", r["source_url"])
                    name = urllib.parse.unquote(name.group(1)) if name else r["gpu"]
                    quote = (f"Vast public offers API: {len(per)} verified rentable on-demand {name} {r['vram_gb']}GB "
                             f"offers; per-GPU dph_total median ${med:.4f}/hr, min ${lo:.4f}/hr")
                    new_s, msg = f"{med:.4f}", "parsed"
                    r["lowest_offer_usd"], r["offer_count"] = lo, len(per)
            elif manual_hold:
                msg = "held (manual), untouched"
            else:
                new_s, quote, msg = parse_listed(r, page_text(body))
            if new_s is not None:
                new = float(new_s)
                old = r["price_usd"]
                pct = (new - old) / old * 100 if old else 0
                if abs(pct) > MAX_AUTO_CHANGE_PCT:
                    row.update(result=f"NOT applied: {old} -> {new} ({pct:+.1f}%) exceeds {MAX_AUTO_CHANGE_PCT:.0f}%; re-check by hand")
                    new_s = None
                else:
                    if abs(new - old) > 1e-9:
                        # use the text matched on the page: a quote holding several prices (e.g. on-demand + spot on one line)
                        # must not keep a sibling's old price (that broke the live source check on 2026-10-29)
                        r["quote"] = _current_quote(r["quote"], quote, old, new_s)
                        _set_price(r, new)
                    if abs(new - old) <= 1e-9:
                        r["quote"] = _current_quote(r["quote"], quote, old, new_s)  # sibling prices on the line may move
                    r["evidence"] = {"source_url": r["source_url"], "quote": quote, "checked_at": stamp}
                    r["verified_at"] = r["checked_at"] = stamp
                    if r.get("stale", {}).get("auto"):
                        del r["stale"]
                    row.update(result="changed" if abs(new - old) > 1e-9 else "unchanged", new=r["hourly_usd"])
            if new_s is None:
                r["checked_at"] = stamp
                age = now - datetime.fromisoformat(r["verified_at"])
                if not r.get("stale") and age > timedelta(days=stale_days):
                    r["stale"] = {"reason": f"Price not re-verified on the vendor page since {r['verified_at'][:10]} "
                                            f"(> {stale_days} days); held out of rankings until re-verified.", "auto": True}
                row.setdefault("result", f"unreadable: {msg}" + ("; HELD (stale)" if r.get("stale", {}).get("auto") else ""))
                if manual_hold:
                    row["result"] = msg
            report.append(row)
        doc["checked_at"] = stamp
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", help="write a Markdown run summary here")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    files = sorted(PRICING_DIR.glob("*.json"))
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    now = datetime.now(timezone.utc)
    rep = refresh(docs, Fetcher(), now)
    if not a.no_write:
        for f, d in zip(files, docs):
            f.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        gpu_history.write_snapshot(docs, now.date().isoformat())
    counts = {}
    for row in rep:
        k = row["result"].split(":")[0].split(" (")[0]
        counts[k] = counts.get(k, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    lines = [f"GPU price refresh {_iso(now)}: {len(rep)} records: {summary}", ""]
    lines += [f"- {r['vendor']} {r['gpu']} ({r['tier']}): {r['result']}"
              + (f" {r['old']} -> {r['new']}" if r.get("result") == "changed" else "") for r in rep]
    print("\n".join(lines))
    if a.report:
        Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
