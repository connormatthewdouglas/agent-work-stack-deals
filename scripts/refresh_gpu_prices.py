#!/usr/bin/env python3
"""Daily GPU price refresh (run by .github/workflows/gpu-refresh.yml).

For each tracked record in data/gpu_pricing/<vendor>.json, re-read the vendor's own public pricing page/API and
update the price ONLY where it was actually parsed:

* Listed prices: the record's last evidence quote is turned into a pattern (its words must appear in the same
  order on today's page, prices become capture groups). The record's price is updated only if that context is
  found and gives exactly one value. The new evidence {source_url, quote, checked_at} is the matched page text.
* Marketplace medians (Vast.ai): the same public offers API and filter as before (verified, rentable, not rented,
  on-demand, exact VRAM, per GPU); a median is published only with >= MIN_MARKET_OFFERS offers.
* Anything unreadable keeps its old price, verified_at and checked_at; last_failed_check_at records the attempt. A rate not verified for
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
    # "..." (or "…") in a quote marks elided page text between two literal fragments (bounded, non-greedy).
    gap = lambda s: r"[\s\S]{0,600}?".join(lit(x) for x in re.split(r"\.\.\.|…", s))
    rx = ""
    for i, part in enumerate(parts):
        rx += gap(part)
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


ROTATING = "rotating snapshot"  # price_check value: the page rotates the spec words (RAM/vCPU/NVMe) on every read
# Gauge spheron84: Spheron's /pricing/ rows rotate RAM/vCPU/NVMe per read; treated as rotating without a data edit.
ROTATING_SOURCES = {"Spheron": "spheron.network/pricing"}
ROTATING_CONFIRM_S = 60  # a rotating-snapshot price changes only when two reads >= 60 s apart agree


def is_rotating(r: dict, vendor: str | None = None) -> bool:
    if r.get("price_check") == ROTATING:
        return True
    src = ROTATING_SOURCES.get(vendor or r.get("vendor") or "")
    return bool(src and src in (r.get("source_url") or ""))


def rotating_regex(gpu: str, vram_gb) -> re.Pattern:
    """GPU name, then (an optional architecture word) its VRAM 'NN GB', then the row's first '$X /hr'. RAM, vCPU and
    NVMe figures in between are bounded filler and never matched."""
    lit = r"\s*".join(re.escape(w) for w in gpu.split())
    vram = rf"[^$]{{0,40}}?\b{int(vram_gb)}\s*GB\b" if vram_gb else ""
    return re.compile(r"(?<![\w-])" + lit + r"(?![\w-])" + vram + r"[^$]{0,160}?\$\s?([\d,]*\.?\d+)\s*/\s*hr")


def parse_rotating(r: dict, text: str) -> tuple[str | None, str | None, str]:
    """-> (price, matched row text, message). The record's own price wins if present; otherwise one distinct value
    is the candidate new price; several values are ambiguous. The matched text is display evidence only."""
    gpu = r.get("gpu") or ""
    if not gpu:
        return None, None, "rotating snapshot without a gpu name"
    hits = [(_num(m.group(1)), " ".join(m.group(0).split())) for m in rotating_regex(gpu, r.get("vram_gb")).finditer(text)]
    if not hits:
        return None, None, "quoted context not found on page"
    old = r.get("price_usd")
    same = [h for h in hits if old is not None and abs(h[0] - old) < 1e-9]
    if same:
        v, q = same[0]
    elif len({h[0] for h in hits}) == 1:
        v, q = hits[0]
    else:
        return None, None, f"ambiguous: {len({h[0] for h in hits})} different values for the same context"
    return f"{v:g}", q[:MAX_QUOTE], "parsed (rotating snapshot: gpu + VRAM + $/hr)"


# Vendor relabelled a plan on its page (same row, same specs, same per-GPU price). Tried only when the original
# context is not found; the new evidence quote is the matched page text, as usual. Prices are never mapped.
LABEL_ALIASES = {
    "lambda.ai/pricing": [("NVIDIA B200 SXM6 180 GB 208", "NVIDIA HGX B200 180 GB 208"),  # 2026-11-02: 8x plans -> "HGX"
                          ("NVIDIA H100 SXM 80 GB 208", "NVIDIA HGX H100 80 GB 208"),
                          ("NVIDIA A100 SXM 80 GB 240", "NVIDIA HGX A100 80 GB 240")],
}


def _aliased_quotes(r: dict, quote: str) -> list[str]:
    q = " ".join(quote.split())
    return [q.replace(old, new) for src, pairs in LABEL_ALIASES.items() if src in (r.get("source_url") or "")
            for old, new in pairs if old in q]


def parse_listed(r: dict, text: str) -> tuple[str | None, str | None, str]:
    """-> (new price string, matched quote, message). price None = unreadable."""
    if is_rotating(r):
        return parse_rotating(r, text)
    quote = r["evidence"]["quote"]
    rx, _ = quote_pattern(quote)
    i = price_index(r, quote)
    n = r.get("gpu_count", 1) or 1
    per_gpu = False
    if i is None and n > 1:  # vendor quotes a per-GPU price for a multi-GPU instance (e.g. Lambda 8x)
        i = price_index({**r, "price_usd": r["hourly_usd"]}, quote)
        per_gpu = i is not None
    if i is None:
        return None, None, "evidence quote does not identify this record's price"
    vals, quotes = set(), []
    for m in rx.finditer(text):
        vals.add(_num(m.group(i + 1)))
        quotes.append(" ".join(m.group(0).split()))
    if not vals:
        for aq in _aliased_quotes(r, quote):
            arx, _ = quote_pattern(aq)
            if any(True for _ in arx.finditer(text)):
                rx = arx
                for m in rx.finditer(text):
                    vals.add(_num(m.group(i + 1)))
                    quotes.append(" ".join(m.group(0).split()))
                break
    if not vals:
        return None, None, "quoted context not found on page"
    if len(vals) > 1:
        return None, None, f"ambiguous: {len(vals)} different values for the same context"
    m = next(rx.finditer(text))
    v = m.group(i + 1).replace(",", "")
    if per_gpu:
        v = f"{round(_num(v) * n, 4):g}"
    return v, quotes[0][:MAX_QUOTE], "parsed"


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
            self.fetched_at = getattr(self, "fetched_at", {})
            self.fetched_at[url] = datetime.now(timezone.utc)
            self.cache[url] = (None, "disallowed by robots.txt") if not self.allowed(url) else self._get(url)
        return self.cache[url]

    def reread(self, url: str, min_gap_s: float) -> tuple[int | None, str]:
        """A fresh read at least min_gap_s after the first (cached) one, for the rotating-snapshot two-read rule."""
        first = getattr(self, "fetched_at", {}).get(url)
        if first:
            wait = min_gap_s - (datetime.now(timezone.utc) - first).total_seconds()
            if wait > 0:
                time.sleep(wait)
        if not self.allowed(url):
            return None, "disallowed by robots.txt"
        return self._get(url)


# Vendor pages that swap the live rate line for an explicit no-capacity sentence (Spheron, 2026-11-02).
NO_CAPACITY = {"Spheron": r"On Spheron the NVIDIA {gpu} has no capacity right now\.?|Spheron Your price \$\s?[\d.]+\s?/hr Last known\s*-\s*No capacity now"}
NO_CAPACITY_REASON = "no capacity per vendor page"
# Vendor pages that withdraw a published rate for "priced upon request" (CloudRift A100, 2026-11-04). {gpu} = model word.
PRICE_WITHDRAWN = {"CloudRift": r"the {gpu} is priced upon request"}


def no_capacity_sentence(vendor: str, gpu: str, text: str) -> str | None:
    """The vendor's exact no-capacity sentence for this GPU, as shown on the page, or None."""
    pat = NO_CAPACITY.get(vendor)
    m = re.search(pat.replace("{gpu}", re.escape(gpu)), text) if pat else None
    return m.group(0) if m else None


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
        if doc.get("manual_snapshot"):
            # Not auto-refreshed (Clore.ai: API 401s CI; Vast parser doesn't apply). Staleness hold still applies below.
            for r in doc["records"]:
                r.setdefault("verified_at", r["evidence"]["checked_at"])
                if not r.get("stale") and now - datetime.fromisoformat(r["verified_at"]) > timedelta(days=stale_days):
                    r["stale"] = {"reason": f"Manual snapshot not re-verified for > {stale_days} days", "auto": True}
            report += [{"vendor": doc["vendor"], "gpu": r["gpu"], "tier": r["tier"], "result": "manual snapshot (not auto-refreshed)"}
                       for r in doc["records"]]
            continue
        # Vendor checked_at moves only when every record we tried to re-read was actually re-verified.
        # A partial read (one row parsed, another unreachable or over the auto-change cap) leaves it unchanged.
        attempted = succeeded = 0
        for r in doc["records"]:
            row = {"vendor": doc["vendor"], "gpu": r["gpu"], "tier": r["tier"], "old": r["hourly_usd"]}
            r.setdefault("verified_at", r["evidence"]["checked_at"])
            manual_hold = r.get("stale") and not r["stale"].get("auto")
            st, body = fetcher.get(r["source_url"])
            # verified_at = when THIS page was actually fetched (not the run start), when the fetcher records it
            fat = (getattr(fetcher, "fetched_at", None) or {}).get(r["source_url"])
            fstamp = _iso(fat) if fat else stamp
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
                text = page_text(body)
                pw = PRICE_WITHDRAWN.get(doc["vendor"])
                pw = pw and re.search(pw.replace("{gpu}", re.escape(r["gpu"].split()[0])), text, re.I)
                if pw:
                    # price no longer published: auto hold (released by the next successful parse), price/quote untouched
                    r["stale"] = {"reason": f"Rate withdrawn on {r['source_url']} (page: \"{pw.group(0)}\") at {stamp}; "
                                            "held, not shown or ranked, until a price is published again.", "auto": True}
                nc = no_capacity_sentence(doc["vendor"], r["gpu"], text)
                if nc:
                    # Gauge T73 fix7 #1: the vendor says no capacity now. Keep the last sourced price and quote (never
                    # rewritten), mark the row out of stock with the read time; core/gpu.py keeps it out of rankings.
                    r["no_capacity"] = {"reason": NO_CAPACITY_REASON, "read_at": fstamp, "source_url": r["source_url"], "page_text": nc}
                    msg = NO_CAPACITY_REASON
                else:
                    new_s, quote, msg = parse_listed({**r, "vendor": doc["vendor"]}, text)
                    if new_s is not None and is_rotating(r, doc["vendor"]) and abs(float(new_s) - r["price_usd"]) > 1e-9:
                        # Gauge spheron84: the page flips values between reads; change only when a second read
                        # >= ROTATING_CONFIRM_S later agrees (no second read available -> not applied)
                        rr = getattr(fetcher, "reread", None)
                        st2, body2 = rr(r["source_url"], ROTATING_CONFIRM_S) if rr else (None, "")
                        v2 = parse_rotating(r, page_text(body2))[0] if st2 == 200 else None
                        if v2 != new_s:
                            row["result"] = (f"NOT applied: rotating snapshot read {new_s} then {v2} "
                                             f"(needs two reads >= {ROTATING_CONFIRM_S}s apart to agree)")
                            new_s = None
                    if new_s is not None:
                        r.pop("no_capacity", None)
            if new_s is not None:
                new = float(new_s)
                old = r["price_usd"]
                pct = (new - old) / old * 100 if old else 0
                # A per-GPU quote cannot substantiate a changed whole-instance total in the
                # current evidence gate. Fail closed instead of writing an unpublishable price.
                n = r.get("gpu_count", 1) or 1
                quoted = [_num(m.group(1)) for m in PRICE_RE.finditer(quote or "")]
                if n > 1 and abs(new - old) > 1e-9 and not any(abs(v - new) < 1e-9 for v in quoted):
                    r["stale"] = {"reason": "Changed per-GPU vendor quote cannot substantiate the whole-instance total "
                                            "under the current evidence contract; held until re-sourced with supported evidence.", "auto": True}
                    row.update(result="HELD: changed whole-instance total missing from vendor quote")
                    new_s = None
                elif abs(pct) > MAX_AUTO_CHANGE_PCT:
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
                    if quote and r.get("price_status") == "marketplace":
                        r["quote"] = quote  # count/median/min all from this one API snapshot (Vast basis drifted 2026-10-29)
                    eq = quote
                    if quote and re.search(r"\.\.\.|…", r["evidence"]["quote"]):  # keep the elided form (stays matchable)
                        eq = r["evidence"]["quote"]
                        if abs(new - old) > 1e-9:
                            eq = _swap_quote_price(eq, old, new_s)
                        r["quote"] = eq
                    r["evidence"] = {**{k: v for k, v in (r.get("evidence") or {}).items() if k not in ("source_url", "quote", "checked_at")},
                                     "source_url": r["source_url"], "quote": eq, "checked_at": fstamp}  # keep extra cited quotes (e.g. Modal preemption)
                    r["verified_at"] = r["checked_at"] = fstamp
                    if r.get("stale", {}).get("auto"):
                        del r["stale"]
                    row.update(result="changed" if abs(new - old) > 1e-9 else "unchanged", new=r["hourly_usd"])
                    succeeded += 1
            if not manual_hold:
                attempted += 1
            if new_s is None:
                if not manual_hold:
                    # Gauge strat2: a row that failed re-verification keeps its checked_at (no bump); the failed attempt
                    # is recorded separately (additive) so the feed never implies a check that did not confirm the price
                    r["last_failed_check_at"] = stamp
                age = now - datetime.fromisoformat(r["verified_at"])
                if not r.get("stale") and age > timedelta(days=stale_days):
                    r["stale"] = {"reason": f"Price not re-verified on the vendor page since {r['verified_at'][:10]} "
                                            f"(> {stale_days} days); held out of rankings until re-verified.", "auto": True}
                row.setdefault("result", f"unreadable: {msg}" + ("; HELD (stale)" if r.get("stale", {}).get("auto") else ""))
                if manual_hold:
                    row["result"] = msg
            report.append(row)
        if attempted and succeeded == attempted:
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
