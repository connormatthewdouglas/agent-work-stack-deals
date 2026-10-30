#!/usr/bin/env python3
"""T41 pricing-decision release gate. Runs 21 cases LIVE against the public Lantern Works feeds and the repo's
own core/ + mcp_server tools (in-process, telemetry off). Usage: python3 run_t41.py [out.json]"""
from __future__ import annotations
import html, json, math, os, re, subprocess, sys, time, traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import argparse
HERE = Path(__file__).resolve().parent
_ap = argparse.ArgumentParser(description="T41 pricing-decision release gate")
_ap.add_argument("--source", choices=("local", "live"), default="local",
                 help="local (default): the built feed/site in this checkout, i.e. what is about to ship; live: thelanternworks.com")
_ap.add_argument("--repo", default=str(HERE.parent.parent), help="repo checkout (default: this one)")
_ap.add_argument("--no-fail", action="store_true", help="exit 0 even if cases fail (report only)")
_ap.add_argument("out", nargs="?", help="results JSON path")
ARGS = _ap.parse_args()
REPO = Path(ARGS.repo).resolve()
LOCAL = ARGS.source == "local"
os.environ.pop("LANTERN_TELEMETRY", None)
_LOCAL_FILES = {"LANTERN_GPU_PRICES_FILE": "api/v1/gpu-prices.json", "LANTERN_GPU_CHANGES_FILE": "api/v1/gpu-price-changes.json",
                "LANTERN_GPU_HISTORY_FILE": "api/v1/gpu-prices/history.json", "LANTERN_STACK_PRICING_FILE": "api/v1/stack-pricing.json",
                "LANTERN_DEALS_FILE": "api/v1/deals.json"}
for k, rel in _LOCAL_FILES.items():
    os.environ.pop(k, None)
    if LOCAL:  # MCP tools read the built files instead of the public URLs
        os.environ[k] = str(REPO / rel)
sys.path.insert(0, str(REPO))
UA = "lantern-works-ci/1 (T41 release gate; ref=t41)"  # T51: house traffic is tagged, never counted as outside use
BASE = "https://thelanternworks.com"
WORKER = "https://lantern-works-mcp.lantern-works.workers.dev"


_LOCAL_PATHS = {"/api/v1/gpu-prices.json": "api/v1/gpu-prices.json", "/api/v1/gpu-price-changes.json": "api/v1/gpu-price-changes.json",
                "/": "index.html", "/gpu/price-comparison/": "gpu/price-comparison/index.html"}


def fetch(url: str) -> tuple[str, str]:
    if LOCAL:
        rel = url[len(BASE):] or "/"
        f = REPO / (_LOCAL_PATHS.get(rel) or (rel.strip("/") if rel.endswith(".json") else rel.strip("/") + "/index.html"))
        return f.read_text(), datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    if url.startswith(BASE + "/api/v1/") and url.endswith(".json"):
        url = WORKER + url[len(BASE):] + "?ref=t41"  # re24 (3c): live T41 reads the feeds through the worker (same bytes, counted as house)
    for wait in (0, 15, 30, 45):
        if wait:
            time.sleep(wait)
        p = subprocess.run(["curl", "-s", "-L", "-A", UA, "-w", "\n%{http_code}", url], capture_output=True, text=True, timeout=60)
        body, _, code = p.stdout.rpartition("\n")
        if code == "200":
            time.sleep(3)
            return body, datetime.now(timezone.utc).isoformat(timespec="seconds")
        if code not in ("429", "500", "502", "503", "504"):
            raise RuntimeError(f"{url} -> HTTP {code}")
    raise RuntimeError(f"{url} -> gave up after backoff")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def toks(s):
    return set("".join(c if c.isalnum() else " " for c in (s or "").lower()).split())


feed_txt, feed_at = fetch(f"{BASE}/api/v1/gpu-prices.json")
ch_txt, ch_at = fetch(f"{BASE}/api/v1/gpu-price-changes.json")
home_txt, home_at = fetch(f"{BASE}/")
cmp_txt, cmp_at = fetch(f"{BASE}/gpu/price-comparison/")
FEED, CH = json.loads(feed_txt), json.loads(ch_txt)
RATES = FEED["rates"]

from core import gpu as G, deals as D, stack as S  # noqa: E402
import mcp_server.server as SRV  # noqa: E402  (tools load the same live URLs via the repo's loaders)

NOW = datetime.now(timezone.utc)
if os.environ.get("LW_AVAIL_NOW"):  # injected clock (same variable as core.gpu_availability.now_utc)
    NOW = datetime.fromisoformat(os.environ["LW_AVAIL_NOW"].replace("Z", "+00:00"))
cases = {c["id"]: c for c in json.loads((HERE / "cases.json").read_text())["cases"]}
results = []


def case(cid):
    def deco(fn):
        fails, evidence = [], {}
        try:
            fn(fails, evidence)
        except Exception as e:  # a crash is a failure with its traceback as evidence
            fails.append(f"exception: {e!r}")
            evidence["traceback"] = traceback.format_exc()[-1500:]
        results.append({"id": cid, "intent": cases[cid]["intent"], "status": "PASS" if not fails else "FAIL",
                        "failures": fails[:25], "failure_count": len(fails), "evidence": evidence})
        return fn
    return deco


def rid(r):
    return f"{r.get('advertiser')}|{r.get('gpu')}|{r.get('tier')}"


def tool(fn, *a, **kw):
    return getattr(fn, "fn", fn)(*a, **kw)


@case("T41-01")
def _(f, ev):
    def amounts(s):
        return {float(x.replace(",", "")) for x in re.findall(r"\$\s*([0-9][0-9,]*\.?[0-9]*)", s or "")}
    not_verbatim = []
    for r in RATES:
        e = r.get("evidence") or {}
        for k in ("price_usd", "hourly_equiv_usd"):
            if not isinstance(r.get(k), (int, float)) or isinstance(r.get(k), bool) or r[k] <= 0:
                f.append(f"{rid(r)}: {k}={r.get(k)!r}")
        if not str(r.get("source_url", "")).startswith("https://"): f.append(f"{rid(r)}: source_url {r.get('source_url')!r}")
        if not str(e.get("source_url", "")).startswith("https://"): f.append(f"{rid(r)}: evidence.source_url missing")
        q = e.get("quote") or ""
        if not (1 <= len(q) <= G.MAX_QUOTE): f.append(f"{rid(r)}: evidence.quote length {len(q)}")
        try: ts(r["verified_at"])
        except Exception: f.append(f"{rid(r)}: verified_at {r.get('verified_at')!r}")
        qa = amounts(q)
        pub = r.get("price_per_second_usd") if r.get("billing_unit") == "per-second" else (
            r.get("server_price_usd") if r["unit"] == "month" and (r.get("gpu_count") or 1) > 1 else r["price_usd"])
        if r.get("price_status") == "marketplace":
            pub = r["hourly_equiv_usd"]
        cands = [x for x in (pub, r.get("server_hourly_usd"), r.get("server_price_usd")) if isinstance(x, (int, float))]
        if not any(abs(a - p) < 1e-6 for a in qa for p in cands): f.append(f"{rid(r)}: published ${pub} not in evidence.quote {q!r}")
        missing = [a for a in amounts(r.get("basis")) if not any(abs(a - b) < 1e-6 for b in qa)]
        if missing: f.append(f"{rid(r)}: basis amounts {missing} not in evidence.quote (basis={r.get('basis')!r} | evidence={q!r})")
        if r.get("price_status") == "marketplace":
            m = re.search(r"(\d+) verified rentable", q); lo = re.search(r"min \$([0-9.]+)", q)
            if m and int(m.group(1)) != r.get("offer_count"): f.append(f"{rid(r)}: offer_count {r.get('offer_count')} vs evidence {m.group(1)}")
            if lo and abs(float(lo.group(1)) - (r.get("lowest_offer_usd") or -1)) > 1e-4: f.append(f"{rid(r)}: lowest_offer_usd {r.get('lowest_offer_usd')} vs evidence {lo.group(1)}")
        if r.get("basis") and r["basis"] not in q: not_verbatim.append(rid(r))
    ev["rates_checked"] = len(RATES)
    ev["observation_basis_not_substring_of_evidence_quote"] = {"count": len(not_verbatim), "rows": not_verbatim}


@case("T41-02")
def _(f, ev):
    if FEED.get("hours_per_month") != G.HOURS_PER_MONTH: f.append(f"hours_per_month={FEED.get('hours_per_month')} vs {G.HOURS_PER_MONTH}")
    m = 0
    for r in RATES:
        if r["unit"] == "hour":
            if abs(r["hourly_equiv_usd"] - r["price_usd"]) > 1e-9: f.append(f"{rid(r)}: hourly_equiv {r['hourly_equiv_usd']} != price {r['price_usd']}")
        else:
            m += 1
            exp = r["price_usd"] / G.HOURS_PER_MONTH
            if abs(r["hourly_equiv_usd"] - exp) > 1e-4: f.append(f"{rid(r)}: hourly_equiv {r['hourly_equiv_usd']} != {r['price_usd']}/730={exp:.4f}")
            if (r.get("gpu_count") or 1) > 1 and abs(r["server_price_usd"] - r["price_usd"] * r["gpu_count"]) > 0.01 * r["gpu_count"]:
                f.append(f"{rid(r)}: server_price {r['server_price_usd']} != {r['price_usd']}x{r['gpu_count']}")
    ev["monthly_rows"] = m


@case("T41-03")
def _(f, ev):
    out = tool(SRV.compare_gpu_prices, "H100", limit=25)
    res = out.get("results") or []
    rows = [r for r in RATES if "h100" in toks(r["gpu"]) and D.tier_class(r) != "reserved"]
    # E5: rows the feed marks out of stock are ranked after in-stock/unknown rows, so they are never "cheapest"
    oos = lambda r: (r.get("availability") or {}).get("in_stock") is False
    exp = min((r["hourly_equiv_usd"] for r in rows if not oos(r)), default=min(r["hourly_equiv_usd"] for r in rows))
    ev.update(tool_cheapest=res[0] and {k: res[0][k] for k in ("advertiser", "gpu", "tier", "hourly_usd", "tier_class")}, feed_min=exp,
              feed_rows=len(rows), tool_count=out.get("count"))
    if abs(res[0]["hourly_usd"] - exp) > 1e-9: f.append(f"cheapest {res[0]['hourly_usd']} != feed min {exp}")
    # Never weaker than before E5: the row shown as cheapest must not be reserved, thin or held, whatever its price.
    if res[0].get("tier_class") == "reserved": f.append("reserved row shown as cheapest")
    if res[0].get("price_status") in ("thin", "held", "held_stale"): f.append(f"{res[0].get('price_status')} row shown as cheapest")
    held_keys = {(h.get("vendor"), x.get("gpu"), x.get("tier")) for h in (FEED.get("held_stale") or []) for x in (h.get("records") or [])}
    ranked_keys = {(r.get("advertiser"), r.get("gpu"), r.get("tier")) for r in RATES}
    held_keys -= ranked_keys  # same label also ranked (fresh) is fine; only a held-only row may not lead
    if (res[0].get("advertiser"), res[0].get("gpu"), res[0].get("tier")) in held_keys: f.append("held/thin row shown as cheapest")
    hs = [(x.get("in_stock") is False, x["hourly_usd"]) for x in res]
    if hs != sorted(hs): f.append(f"not sorted ascending (out-of-stock last): {hs}")
    if out.get("total") != len(rows) and len(rows) <= 25 and out.get("count") != len(rows): f.append(f"count {out.get('count')} != feed rows {len(rows)}")
    if out.get("scope") != "cheapest among tracked providers": f.append(f"scope={out.get('scope')!r}")
    if "among tracked providers" not in (out.get("summary") or ""): f.append("summary lacks 'among tracked providers'")


@case("T41-04")
def _(f, ev):
    out = tool(SRV.compare_gpu_prices, "L40S", limit=25, on_demand_only=True)
    res = out.get("results") or []
    l40s = [r for r in RATES if "l40s" in toks(r["gpu"])]
    od = [r for r in l40s if D.tier_class(r) == "on-demand"]
    exp = min(r["hourly_equiv_usd"] for r in od)
    bad = [x for x in res if x["tier_class"] != "on-demand"]
    if bad: f.append(f"non-on-demand results: {[rid(x) for x in bad]}")
    if not res or abs(res[0]["hourly_usd"] - exp) > 1e-9: f.append(f"cheapest on-demand {res and res[0]['hourly_usd']} != feed {exp}")
    exp_ex = len(l40s) - len(od)
    if out.get("excluded_non_on_demand") != exp_ex: f.append(f"excluded_non_on_demand {out.get('excluded_non_on_demand')} != {exp_ex}")
    ev.update(cheapest=res and {k: res[0][k] for k in ("advertiser", "tier", "hourly_usd")}, feed_on_demand_min=exp,
              on_demand_rows=len(od), all_l40s_rows=len(l40s))


@case("T41-05")
def _(f, ev):
    gpu = "H100"
    rows = [r for r in RATES if "h100" in toks(r["gpu"])]
    nres = sum(D.tier_class(r) == "reserved" for r in rows)
    a = tool(SRV.compare_gpu_prices, gpu, limit=25)
    b = tool(SRV.compare_gpu_prices, gpu, limit=25, include_reserved=True)
    if any(x["tier_class"] == "reserved" for x in a["results"]): f.append("default call returned reserved rows")
    if a.get("excluded_reserved") != nres: f.append(f"excluded_reserved {a.get('excluded_reserved')} != {nres}")
    cls = [x["tier_class"] == "reserved" for x in b["results"]]
    if cls != sorted(cls): f.append("include_reserved: a reserved row ranks before a pay-as-you-go row")
    if b["results"] and b["results"][0]["tier_class"] == "reserved": f.append("reserved ranked #1")
    est = G.estimate(RATES, 730)
    ecls = [D.tier_class(x) == "reserved" for x in est]
    if ecls != sorted(ecls): f.append("estimate: reserved not sorted last")
    allres = [r for r in RATES if D.tier_class(r) == "reserved"]
    ev.update(reserved_h100=nres, reserved_total=len(allres),
              cheapest_reserved=min((r["hourly_equiv_usd"], rid(r)) for r in allres) if allres else None,
              first_with_reserved=rid(b["results"][0]) + f" ${b['results'][0]['hourly_usd']}")


@case("T41-06")
def _(f, ev):
    rx = G.INTERRUPTIBLE_TIER_RE  # canonical: "not interruptible" / "non-interruptible" labels are not spot
    for r in RATES:
        tc = D.tier_class(r)
        if r.get("tier_class") != tc: f.append(f"{rid(r)}: feed tier_class {r.get('tier_class')} != computed {tc}")
        if tc not in D.TIER_CLASSES: f.append(f"{rid(r)}: tier_class {tc} not allowed")
        if bool(r.get("interruptible")) != (tc == "interruptible"): f.append(f"{rid(r)}: interruptible={r.get('interruptible')} but class {tc}")
        if rx.search(r["tier"]) and not r.get("interruptible"): f.append(f"{rid(r)}: tier says spot/preempt but interruptible=false")
        if "community" in r["tier"].lower() and tc not in ("community", "interruptible"): f.append(f"{rid(r)}: community tier classed {tc}")
    from collections import Counter
    ev["classes"] = dict(Counter(r.get("tier_class") for r in RATES))


@case("T41-07")
def _(f, ev):
    rx = re.compile(r"spot|preempt|interrupt|batch", re.I)
    n = 0
    for r in RATES:
        if not r.get("interruptible"): continue
        n += 1
        e = r.get("evidence") or {}
        iq = e.get("interruption_quote")
        if iq:
            if not str(e.get("interruption_source_url", "")).startswith("https://"): f.append(f"{rid(r)}: interruption_quote without https source")
            continue
        if not (rx.search(e.get("quote") or "") or rx.search(r["tier"])):
            f.append(f"{rid(r)}: interruptible with no spot/preempt wording in quote/tier and no interruption_quote")
        elif not rx.search(e.get("quote") or ""):
            ev.setdefault("tier_only_support", []).append(f"{rid(r)} quote={e.get('quote')!r}")
    ev["interruptible_rows"] = n


@case("T41-08")
def _(f, ev):
    for r in RATES:
        if G.is_non_dedicated(r["gpu"]): f.append(f"{rid(r)}: non-dedicated GPU")
        if not isinstance(r.get("vram_gb"), (int, float)) or r["vram_gb"] <= 0: f.append(f"{rid(r)}: vram_gb={r.get('vram_gb')!r}")
    ev["gpus"] = sorted({r["gpu"] for r in RATES})


@case("T41-09")
def _(f, ev):
    multi = []
    for r in RATES:
        n, mg = r.get("gpu_count") or 1, r.get("min_gpus") or 1
        if mg > 1:
            multi.append(f"{rid(r)} count={n} min={mg} server_hr={r.get('server_hourly_usd')}")
            if n != mg: f.append(f"{rid(r)}: min_gpus {mg} but gpu_count {n}")
            if r["unit"] == "hour" and r.get("server_hourly_usd") is None: f.append(f"{rid(r)}: server_hourly_usd null")
            if r["unit"] == "month" and r.get("server_price_usd") is None: f.append(f"{rid(r)}: server_price_usd null")
        if n > 1 and r["unit"] == "hour" and r.get("server_hourly_usd") is not None:
            if abs(r["server_hourly_usd"] - r["price_usd"] * n) > 0.02: f.append(f"{rid(r)}: server_hourly {r['server_hourly_usd']} != {r['price_usd']}x{n}")
        if re.search(r"\b8x\b|8-GPU", r["tier"]) and mg != 8: f.append(f"{rid(r)}: tier says 8 GPUs but min_gpus={mg}")
    ev["multi_gpu_rows"] = multi


@case("T41-10")
def _(f, ev):
    est = G.estimate(RATES, 730, gpus=1)
    for x in est:
        per, mg = x.get("gpu_count") or 1, x.get("min_gpus") or 1
        g = math.ceil(max(1, mg) / per) * per
        exp = round(x["price_usd"] * 730 * g, 2) if x["unit"] == "hour" else round(x["price_usd"] * g, 2)
        if abs(x["monthly_cost_usd"] - exp) > 0.011: f.append(f"{rid(x)}: monthly {x['monthly_cost_usd']} != {exp}")
    flipped = [{**r, "affiliate": not r.get("affiliate")} for r in RATES]
    if [rid(x) for x in G.estimate(flipped, 730)] != [rid(x) for x in est]: f.append("rank changed when affiliate flags flipped")
    bad = [k for r in RATES for k in r if re.search(r"commission|payout|bounty", k, re.I)]
    if bad: f.append(f"commission/payout fields present: {sorted(set(bad))}")
    ev.update(rows=len(est), cheapest_payg_1gpu_730h=f"{rid(est[0])} ${est[0]['monthly_cost_usd']}", affiliate_rows=sum(bool(r.get('affiliate')) for r in RATES))


@case("T41-11")
def _(f, ev):
    eight = [r for r in RATES if (r.get("gpu_count") or 1) == 8]
    if not eight: f.append("no live 8-GPU rows to test"); return
    est = {rid(x): x for x in G.estimate(eight, 10, gpus=9)}
    opts = []
    for r in eight:
        x = est[rid(r)]
        exp = round(r["price_usd"] * 10 * 16, 2)
        if abs(x["monthly_cost_usd"] - exp) > 0.011: f.append(f"{rid(r)}: estimate {x['monthly_cost_usd']} != {exp}")
        if "9 requested" not in x["calc"] or "16 billed" not in x["calc"]: f.append(f"{rid(r)}: calc {x['calc']!r}")
        o = S._gpu_options({"rates": [r], "hours_per_month": 730}, 10, None, set(), gpus=9)
        if not o or abs(o[0]["monthly_cost_usd"] - exp) > 0.011: f.append(f"{rid(r)}: stack option {o and o[0]['monthly_cost_usd']} != {exp}")
        opts.append(f"{rid(r)} -> ${x['monthly_cost_usd']}")
    ev["rows"] = opts


@case("T41-12")
def _(f, ev):
    fu = ts(FEED["feed_updated_at"])
    mx = max(ts(r["verified_at"]) for r in RATES)
    if fu + timedelta(seconds=1) < mx: f.append(f"feed_updated_at {fu} < newest verified_at {mx}")
    if NOW - fu > timedelta(hours=36): f.append(f"feed_updated_at {fu} older than 36h")
    out = tool(SRV.compare_gpu_prices, "H100", limit=25)
    for x in out["results"]:
        if x.get("degraded") or x.get("stale"): f.append(f"{rid(x)}: data_age_hours={x.get('data_age_hours')} degraded/stale")
    for k in ("next_refresh_utc",):
        if not out.get(k): f.append(f"compare output missing {k}")
    old = sorted(((NOW - ts(r["verified_at"])).total_seconds() / 3600, rid(r)) for r in RATES)[-1]
    if old[0] > 48: f.append(f"oldest verified row {old[1]} is {old[0]:.1f} h old")
    ev.update(feed_updated_at=FEED["feed_updated_at"], newest_verified=mx.isoformat(), oldest_row_age_h=round(old[0], 1),
              oldest_row=old[1], next_refresh_utc=out.get("next_refresh_utc"), freshness={k: out.get(k) for k in out if "fresh" in k or "checked" in k})


@case("T41-13")
def _(f, ev):
    held = FEED.get("held_stale") or []
    # record-scoped holds key on normalised tier text ('3-month' == '3-month commitment'); vendor holds on vendor/gpu.
    # re30 d: a ranked row with the same vendor, GPU and price as any held row also fails (a hold leaking via a relabel).
    import re as _re
    STOP = {"commitment", "instance", "instances", "term", "plan", "price", "rate", "1x", "gpu"}
    def nt(t):
        return frozenset(x for x in _re.findall(r"[a-z0-9]+", str(t or "").lower().replace("months", "month").replace("mo ", "month ")) if x not in STOP)
    def same_tier(a, b):
        x, y = nt(a), nt(b)
        return bool(x) and bool(y) and (x <= y or y <= x)
    def held_hit(r):
        for h in held:
            for rec in h["records"]:
                if h["vendor"] != r["advertiser"] or rec["gpu"] != r["gpu"]:
                    continue
                if h.get("scope") != "record" or same_tier(rec.get("tier"), r.get("tier")):
                    return "held_stale vendor/gpu is ranked"
                hp = rec.get("hourly_usd", rec.get("price_usd"))
                if isinstance(hp, (int, float)) and abs(hp - (r.get("hourly_equiv_usd") or -1)) < 1e-9:
                    return f"same vendor/gpu/price ${hp:g} as held row ({rec.get('tier')})"
        return None
    for r in RATES:
        why = held_hit(r)
        if why: f.append(f"{rid(r)}: {why}")
    for h in held:
        if not h.get("reason"): f.append(f"{h['vendor']}: held without reason")
        for rec in h["records"]:
            try:
                out = tool(SRV.compare_gpu_prices, rec["gpu"], limit=25)
                hits = [x for x in out.get("results") or [] if x["advertiser"] == h["vendor"] and x.get("gpu") == rec["gpu"]
                        and (h.get("scope") != "record" or same_tier(x.get("tier"), rec.get("tier")))]
                if hits: f.append(f"compare {rec['gpu']} returns held {h['vendor']}")
            except Exception:
                pass
    ev["held"] = [f"{h['vendor']}: {h.get('reason')}"[:160] for h in held]


@case("T41-14")
def _(f, ev):
    chs = CH.get("changes") or []
    from collections import Counter
    cnt = Counter(c["change"] for c in chs)
    if dict(cnt) != {k: v for k, v in (CH.get("counts") or {}).items() if v}: f.append(f"counts {CH.get('counts')} != list {dict(cnt)}")
    for c in chs:
        if c["change"] in ("up", "down"):
            o, n = c["old_hourly_usd"], c["new_hourly_usd"]
            exp = round((n - o) / o * 100, 1)
            if abs((c.get("pct") or 0) - exp) > 0.11: f.append(f"{c['key']}: pct {c.get('pct')} != {exp}")
            if (n > o) != (c["change"] == "up"): f.append(f"{c['key']}: direction {c['change']} but {o}->{n}")
    out = tool(SRV.get_price_changes)
    order = {"down": 0, "up": 1, "removed": 2, "new": 3, "same": 4}  # core.deals.price_changes rank
    seq = [order.get(c.get("change") or c.get("direction"), 9) for c in out.get("changes") or []]
    if seq != sorted(seq): f.append(f"tool order not down->up->removed->new: {seq}")
    nr = out.get("next_refresh_utc") or ""
    if "10:23" not in nr: f.append(f"next_refresh_utc={nr!r}")
    if not out.get("data_checked_at"): f.append("data_checked_at blank")
    ev.update(date=CH.get("date"), counts=CH.get("counts"), tool_count=len(out.get("changes") or []), next_refresh_utc=nr,
              data_checked_at=out.get("data_checked_at"), tool_keys=sorted(out)[:20])


@case("T41-15")
def _(f, ev):
    def key(r):
        return f"{r['advertiser']}|{r['gpu']}|{r['tier']}|{r['vram_gb']}|{r.get('gpu_count') or 1}"
    cur = {key(r): r for r in RATES}
    fdate = FEED["feed_updated_at"][:10]
    ev.update(changes_date=CH.get("date"), feed_date=fdate)
    if CH.get("date") != fdate:
        ev["note"] = "dates differ; only 'removed' checked"
    for c in CH.get("changes") or []:
        r = cur.get(c["key"])
        if c["change"] == "removed":
            if r: f.append(f"{c['key']}: marked removed but still in rates at ${r['hourly_equiv_usd']}")
            continue
        if CH.get("date") != fdate: continue
        if r is None: f.append(f"{c['key']}: change '{c['change']}' but key not in current rates"); continue
        if abs(r["hourly_equiv_usd"] - c["new_hourly_usd"]) > 1e-6: f.append(f"{c['key']}: change new ${c['new_hourly_usd']} vs feed ${r['hourly_equiv_usd']}")


@case("T41-16")
def _(f, ev):
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", home_txt)))
    m = re.search(r"(\d+)\s+rates from\s+(\d+)\s+vendors", t)
    nv = len({r["advertiser"] for r in RATES})
    ev.update(feed_rates=len(RATES), feed_vendors=nv, home_match=m and m.group(0), home_fetched_at=home_at)
    if not m: f.append("homepage has no 'N rates from M vendors' line"); return
    if int(m.group(1)) != len(RATES): f.append(f"homepage {m.group(1)} rates vs feed {len(RATES)}")
    if int(m.group(2)) != nv: f.append(f"homepage {m.group(2)} vendors vs feed {nv}")


@case("T41-17")
def _(f, ev):
    a = tool(SRV.compare_gpu_prices, "Z9999")
    if (a.get("error") or {}).get("code", a.get("error")) not in ("not_found",) and "not_found" not in json.dumps(a)[:300]:
        f.append(f"Z9999 -> {json.dumps(a)[:200]}")
    b = tool(SRV.compare_gpu_prices, "L40", limit=25)
    leak = [x for x in b.get("results") or [] if "l40s" in toks(x["gpu"])]
    if leak: f.append(f"'L40' returned L40S rows: {[rid(x) for x in leak]}")
    ev.update(z9999=json.dumps(a)[:240], l40=[rid(x) for x in b.get("results") or []] or json.dumps(b)[:200])


@case("T41-18")
def _(f, ev):
    a = tool(SRV.compare_gpu_prices, "A100 80GB", limit=25)
    bad = [rid(x) + f" {x['vram_gb']}GB" for x in a.get("results") or [] if x.get("vram_gb") != 80]
    if bad: f.append(f"'A100 80GB' returned other sizes: {bad}")
    if not a.get("results"): f.append(f"'A100 80GB' -> {json.dumps(a)[:200]}")
    sizes = {r["vram_gb"] for r in RATES if "a100" in toks(r["gpu"]) and D.tier_class(r) != "reserved"}
    b = tool(SRV.compare_gpu_prices, "A100", limit=25)
    if len(sizes) > 1 and "Memory sizes differ" not in (b.get("summary") or ""): f.append("plain 'A100' summary lacks 'Memory sizes differ'")
    ev.update(a100_sizes=sorted(sizes), a100_80_count=len(a.get("results") or []))


@case("T41-19")
def _(f, ev):
    rows = []
    for r in RATES:
        if r.get("price_status") == "marketplace":
            rows.append(f"{rid(r)} median ${r['hourly_equiv_usd']} low ${r.get('lowest_offer_usd')} n={r.get('offer_count')}")
            if D.tier_class(r) != "marketplace": f.append(f"{rid(r)}: class {D.tier_class(r)}")
            if not isinstance(r.get("offer_count"), int) or r["offer_count"] < G.MIN_MARKET_OFFERS: f.append(f"{rid(r)}: offer_count {r.get('offer_count')}")
            lo = r.get("lowest_offer_usd")
            if not isinstance(lo, (int, float)) or not 0 < lo <= r["hourly_equiv_usd"]: f.append(f"{rid(r)}: lowest_offer {lo} vs median {r['hourly_equiv_usd']}")
        elif r.get("offer_count") is not None:
            f.append(f"{rid(r)}: non-marketplace row has offer_count {r['offer_count']}")
    ev["marketplace_rows"] = rows


@case("T41-20")
def _(f, ev):
    out = tool(SRV.optimize_stack, gpu_hours=100, gpu_model="H100")
    line = next((l for l in out.get("lines") or out.get("needs") or [] if l.get("need") == "gpu_hours"), None)
    if line is None: f.append(f"no gpu_hours line: {json.dumps(out)[:300]}"); return
    opts = S._gpu_options(FEED, 100, "H100", set(FEED.get("manual_only_deal_ids") or []))
    if not opts: f.append("no options"); return
    ch = line.get("choice") or {}
    if abs((line.get("monthly_cost_usd") or -1) - opts[0]["monthly_cost_usd"]) > 0.011: f.append(f"choice ${line.get('monthly_cost_usd')} != min option ${opts[0]['monthly_cost_usd']} ({opts[0]['vendor']})")
    r = next((r for r in RATES if r["advertiser"] == ch.get("vendor") and ch.get("plan", "").startswith(r["gpu"] + " (") and r["tier"] in ch.get("plan", "")), None)
    if r is None: f.append(f"choice {ch.get('vendor')} {ch.get('plan')} not found in feed")
    else:
        if D.tier_class(r) == "reserved": f.append("choice is a reserved rate")
        g = math.ceil(max(1, r.get("min_gpus") or 1) / (r.get("gpu_count") or 1)) * (r.get("gpu_count") or 1)
        exp = round(r["price_usd"] * 100 * g, 2) if r["unit"] == "hour" else None
        if exp is not None and abs(ch["monthly_cost_usd"] - exp) > 0.011: f.append(f"choice cost {ch['monthly_cost_usd']} != {exp}")
    ev.update(choice=f"{ch.get('vendor')} {ch.get('plan')} ${ch.get('monthly_cost_usd')} calc={ch.get('calc')!r}",
              min_option=f"{opts[0]['vendor']} {opts[0]['plan']} ${opts[0]['monthly_cost_usd']}")


@case("T41-21")
def _(f, ev):
    # /gpu/price-comparison/ per-model summary: the "lowest" cell must be the cheapest pay-as-you-go rate
    # (reserved/commitment rows never win, same rule as compare_gpu_prices).
    tbl = cmp_txt.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    rows = re.findall(r"<tr><td>(.*?)</td><td>(\d+)</td><td>.*?</td><td>(.*?)</td></tr>", tbl)
    if not rows: f.append("summary table not found"); return
    seen = []
    for model_cell, _n, low in rows:
        name = html.unescape(re.sub(r"<[^>]+>", "", model_cell)).replace("(few verified offers)", "").strip()
        rs = [r for r in RATES if r["gpu"] == name or r["gpu"].startswith(name + " ")] if G.family_of(name) else [r for r in RATES if r["gpu"] == name]
        payg = [r for r in rs if D.tier_class(r) != "reserved"] or rs
        if not payg: f.append(f"{name}: no rates in feed"); continue
        best = min(r["hourly_equiv_usd"] for r in payg)
        m = re.search(r"\$([\d,.]+)/(hr|mo|GPU-mo)", html.unescape(low))
        got = float(m.group(1).replace(",", "")) if m else None
        lo_rows = [r for r in payg if r["hourly_equiv_usd"] == best]
        exp = lo_rows[0]["price_usd"]
        if got is None or abs(got - exp) > 0.005: f.append(f"{name}: page lowest {html.unescape(low)!r} != pay-as-you-go min ${exp}")
        seen.append(f"{name}: {html.unescape(low)[:60]}")
    ev.update(rows=seen, page_fetched_at=cmp_at)


@case("T41-22")
def _(f, ev):
    # K1: on every /gpu/cheapest-*-rental/ page, no out-of-stock row may be ranked above a row not marked out of stock
    # (checked per table: pay-as-you-go and reserved tables are ranked separately).
    slugs = sorted(re.findall(r'/gpu/cheapest-([a-z0-9-]+)-rental/', cmp_txt) or [])
    slugs = sorted(set(slugs))
    if not slugs: f.append("no /gpu/cheapest-*-rental/ links found on /gpu/price-comparison/"); return
    seen_pages = []
    for slug in slugs:
        txt, _at = fetch(f"{BASE}/gpu/cheapest-{slug}-rental/")
        n_oos = 0
        for tb in txt.split("<tbody>")[1:]:
            oos_seen = False
            for i, tr in enumerate(re.findall(r"<tr.*?</tr>", tb.split("</tbody>")[0], re.S), 1):
                o = "out of stock when checked" in tr
                n_oos += o
                if oos_seen and not o: f.append(f"{slug}: row #{i} not marked out of stock is ranked below an out-of-stock row")
                oos_seen |= o
        seen_pages.append(f"{slug}: {n_oos} out-of-stock rows, ranked last")
    ev.update(pages=seen_pages)


@case("T41-23")
def _(f, ev):
    # 0.3.30 staleness guard: a Scout stock check 9 h old must render unknown on the site and in compare_gpu_prices
    # (in_stock null, availability_stale true), never lead a summary, and every live stock claim on a page must carry
    # data-av-checked plus the inline expiry script so a static page cannot keep showing it after 8 h.
    import copy, html as H, types
    from datetime import timedelta
    from core.gpu_availability import AVAIL_MAX_AGE_H, stale_guard
    sys.path.insert(0, str(REPO / "scripts"))
    import gpu_pages as GP
    old = (NOW - timedelta(hours=9)).isoformat(timespec="seconds").replace("+00:00", "Z")
    fx = copy.deepcopy(FEED)
    n = 0
    for r in fx["rates"]:
        if r.get("gpu", "").startswith("A100") and r.get("tier_class") != "reserved":
            r["availability"] = {"status": "available when checked", "in_stock": True, "checked_at": old, "origin": "scout",
                                 "note": "fixture", "refresh": "manual snapshot, time shown (prices checked daily)"}
            n += 1
    if not n: f.append("no A100 rows to build the 9h fixture"); return
    out = D.compare_gpu_prices(fx, "A100", limit=25, now=NOW)
    bad = [r["advertiser"] for r in out["results"] if r["in_stock"] is not None or not (r["availability"] or {}).get("availability_stale")]
    if bad: f.append(f"9h-old rows not unknown/stale in compare_gpu_prices: {bad[:5]}")
    if "available when checked" in out["summary"]: f.append("summary leads with a 9h-old in-stock claim")
    cell = GP._avail_cell(types.SimpleNamespace(esc=H.escape), {"availability": stale_guard(fx["rates"][0]["availability"] | {"checked_at": old, "origin": "scout", "in_stock": True}, NOW)})
    if not cell.startswith("unknown (stale availability, last checked "): f.append(f"site cell for 9h-old check renders {cell!r}")
    txt, _at = fetch(f"{BASE}/gpu/cheapest-a100-rental/")
    claims = re.findall(r"<td[^>]*>((?:(?!</td>).)*?(?:available|out of stock) when checked(?:(?!</td>).)*)</td>", txt, re.S)
    naked = [c[:80] for c in claims if "data-av-checked" not in c and "stale availability" not in c]
    if claims and "<!-- av-stale -->" not in txt: f.append("page has stock claims but no expiry script")
    if naked: f.append(f"stock claims without data-av-checked: {naked[:3]}")
    ev.update(fixture_checked_at=old, limit_hours=AVAIL_MAX_AGE_H, fixture_rows=n, summary=out["summary"][:220],
              site_cell=cell, page_claims=len(claims))


@case("T41-24")
def _(f, ev):
    # re17: no-JS check of what is served. No in_stock:true claim in the JSON feeds, and no "available when checked"
    # claim in the raw HTML, may be past checked_at + AVAIL_MAX_AGE_H (availability_expires_at).
    from datetime import timedelta
    from core.gpu_availability import AVAIL_MAX_AGE_H
    lim = timedelta(hours=AVAIL_MAX_AGE_H)
    checked = 0
    def chk_json(name, rates):
        nonlocal checked
        for r in rates:
            a = r.get("availability") if isinstance(r.get("availability"), dict) else {}
            if a.get("in_stock") is not True:
                continue
            checked += 1
            if not a.get("checked_at"): f.append(f"{name}: {rid(r)} in stock with no checked_at"); continue
            exp = ts(a["availability_expires_at"]) if a.get("availability_expires_at") else ts(a["checked_at"]) + lim
            if not a.get("availability_expires_at"): f.append(f"{name}: {rid(r)} in stock without availability_expires_at")
            if NOW > exp or NOW - ts(a["checked_at"]) > lim:
                f.append(f"{name}: {rid(r)} in stock, checked {a['checked_at']}, expired {exp.isoformat()}")
    chk_json("gpu-prices.json", RATES)
    idx = json.loads(fetch(f"{BASE}/api/v1/gpu/index.json")[0])
    fams = sorted(m["url"].rsplit("/", 1)[1] for m in idx["models"])
    for fam in fams:
        d = json.loads(fetch(f"{BASE}/api/v1/gpu/{fam}")[0])
        chk_json(f"gpu/{fam}", (d.get("rows") or []) + ([d["cheapest"]] if isinstance(d.get("cheapest"), dict) else []))
    pages = sorted(set(re.findall(r'/gpu/cheapest-([a-z0-9-]+)-rental/', cmp_txt)))
    n_html = 0
    for slug in pages:
        txt, _at = fetch(f"{BASE}/gpu/cheapest-{slug}-rental/")
        for m in re.finditer(r'data-av-checked="([^"]+)"[^>]*>([^<]*)', txt):
            if "available when checked" not in m.group(2):
                continue
            n_html += 1
            if NOW - ts(m.group(1)) > lim:
                f.append(f"/gpu/cheapest-{slug}-rental/: in-stock claim checked {m.group(1)} is past {AVAIL_MAX_AGE_H} h (no JS)")
    ev.update(json_in_stock_claims=checked, html_in_stock_claims=n_html, families=fams, pages=len(pages))


@case("T41-25")
def _(f, ev):
    # Scout v2.9: available_regions (and available_regions_detail) expire per region (1 h), separately from the 8 h
    # stock claim. No JSON feed and no raw-HTML region list may show a region past its region expiry.
    n_json = 0
    def chk_json(name, rates):
        nonlocal n_json
        for r in rates:
            a = r.get("availability") if isinstance(r.get("availability"), dict) else {}
            det = [d for d in (a.get("available_regions_detail") or []) if isinstance(d, dict)]
            if not (a.get("available_regions") or det):
                continue
            n_json += 1
            for d in det:
                if d.get("availability_expires_at") and NOW > ts(d["availability_expires_at"]):
                    f.append(f"{name}: {rid(r)} lists region {d.get('region')} past its expiry {d['availability_expires_at']}")
            if a.get("available_regions") and det and not a.get("regions_expires_at"):
                f.append(f"{name}: {rid(r)} lists regions without regions_expires_at")
            if a.get("available_regions") and a.get("regions_expires_at") and NOW > ts(a["regions_expires_at"]):
                f.append(f"{name}: {rid(r)} lists available_regions past regions_expires_at {a['regions_expires_at']}")
    chk_json("gpu-prices.json", RATES)
    idx = json.loads(fetch(f"{BASE}/api/v1/gpu/index.json")[0])
    for fam in sorted(m["url"].rsplit("/", 1)[1] for m in idx["models"]):
        d = json.loads(fetch(f"{BASE}/api/v1/gpu/{fam}")[0])
        chk_json(f"gpu/{fam}", (d.get("rows") or []) + ([d["cheapest"]] if isinstance(d.get("cheapest"), dict) else []))
    pages = ["/gpu/price-comparison/"] + [f"/gpu/cheapest-{s}-rental/" for s in sorted(set(re.findall(r'/gpu/cheapest-([a-z0-9-]+)-rental/', cmp_txt)))]
    n_html = 0
    for pg in pages:
        txt, _at = fetch(f"{BASE}{pg}")
        for m in re.finditer(r'data-rg-expires="([^"]+)"', txt):
            n_html += 1
            if NOW > ts(m.group(1)):
                f.append(f"{pg}: region list valid until {m.group(1)} is still in the raw HTML (no JS)")
    ev.update(json_region_rows=n_json, html_region_lists=n_html)



@case("T41-26")
def _(f, ev):
    # re19 N1/N2: no in-stock claim past its own expiry; a claim derived from regions ends with its regions;
    # a RunPod overall claim needs a confirmed region (the GPU-type-wide lowestPrice hint alone is not stock).
    n = 0
    for r in RATES:
        a = r.get("availability") if isinstance(r.get("availability"), dict) else {}
        if a.get("in_stock") is not True:
            continue
        n += 1
        if a.get("availability_expires_at") and NOW > ts(a["availability_expires_at"]):
            f.append(f"{rid(r)} in stock past availability_expires_at {a['availability_expires_at']}")
        if a.get("derived_from_regions") and (not a.get("regions_expires_at") or NOW > ts(a["regions_expires_at"])):
            f.append(f"{rid(r)} region-derived claim in stock without live regions")
        if (str(r.get("advertiser")).startswith(("Lambda", "Verda")) or a.get("derived_from_regions")) and a.get("checked_at") \
                and a.get("availability_expires_at") and (ts(a["availability_expires_at"]) - ts(a["checked_at"])).total_seconds() > 3600:
            f.append(f"{rid(r)} vendor-API/derived claim lasts longer than 1 h (re20 P3)")
        if r.get("advertiser") == "RunPod" and a.get("origin") == "scout" and not a.get("available_regions"):
            f.append(f"{rid(r)} RunPod in stock with no confirmed region")
    ev.update(in_stock_claims=n)


passed = sum(r["status"] == "PASS" for r in results)
doc = {"suite": "T41", "run_at_utc": NOW.isoformat(timespec="seconds"),
       "repo_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
       "repo_version": getattr(D, "VERSION", None),
       "sources": {"gpu_prices": {"url": f"{BASE}/api/v1/gpu-prices.json", "fetched_at": feed_at, "feed_updated_at": FEED.get("feed_updated_at"), "rates": len(RATES)},
                   "gpu_price_changes": {"url": f"{BASE}/api/v1/gpu-price-changes.json", "fetched_at": ch_at, "date": CH.get("date")},
                   "home": {"url": f"{BASE}/", "fetched_at": home_at},
                   "mode": ARGS.source, "mcp_tools": "mcp_server.server tools called in-process (local mode: LANTERN_*_FILE -> built api/v1 files)"},
       "total": len(results), "passed": passed, "failed": len(results) - passed, "results": results}
outp = Path(ARGS.out) if ARGS.out else HERE / f"results-{NOW:%Y-%m-%d}.json"
outp.write_text(json.dumps(doc, indent=1, default=str))
for r in results:
    print(r["id"], r["status"], ("; ".join(r["failures"][:3]))[:300])
print(f"{passed}/{len(results)} passed -> {outp}")
if passed != len(results) and not ARGS.no_fail:
    sys.exit(1)
