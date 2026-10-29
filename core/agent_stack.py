"""optimize_agent_stack: free-text agent description -> per-component cheapest SOURCED option (dependency-free).

Parsing is deterministic (keywords + regex, no LLM). Prices come only from cited data: /api/v1/gpu-prices.json,
/api/v1/stack-pricing.json and priced deals in the public feed (price_usd + source_url + verified_at). A component
with no cited price says "no sourced price tracked"; nothing is estimated. Pulled / not-relistable listings are
excluded; manual-only signups are flagged. Affiliate status is never a ranking factor; it is only disclosed.
"""
from __future__ import annotations

import copy
import math
import re

from . import stack
from .compliance import allowed_deal_ids
from .quote import offer_rate_id

NO_DATA = "no sourced price tracked"
DISCLOSURE = "Referral link: Lantern Works may be paid if you sign up through it. This never affects ranking."
MAX_DESC = 2000
NOT_A_SERVICE_TAGS = {"control-panel", "open-source", "antidetect-browser"}  # software you run yourself, not a priced service

# component -> (label, stack need or None, keyword regex, deal tags for the priced-deal fallback)
COMPONENTS = {
    "gpu": ("GPU compute", "gpu_hours",
            r"\bgpus?\b|\bh100\b|\ba100\b|\bh200\b|\bl40s?\b|\brtx\s?\d{4}\b|\bfine[- ]?tun\w*|\btrain(?:ing)?\b|"
            r"\bself[- ]host\w*\s+(?:an?\s+)?(?:llm|model)|\bvllm\b|\bollama\b|\b\d+(?:\.\d+)?\s?b\b(?:\s+(?:param|model))?", {"gpu"}),
    "scraping": ("Web scraping", "scrape_pages", r"\bscrap\w*|\bcrawl\w*|\bextract\w*\s+(?:data|content)\s+from\s+(?:web|site)", {"scrape", "scraping", "crawl"}),
    "proxy": ("Residential proxies", "proxy_gb", r"\bprox(?:y|ies)\b|\bresidential\s+ips?\b|\bip\s+rotation\b", {"proxy", "proxies", "residential-proxy"}),
    "search": ("Web search API", "search_queries", r"\bserp\b|\bsearch\s+(?:api|engine|results)\b|\bweb\s+search\b|\bgoogle\s+results\b", {"serp", "search-api", "serp-api"}),
    "llm_api": ("LLM API", None, r"\bllms?\b|\bgpt\b|\bclaude\b|\bopenai\b|\blanguage\s+model|\bchat\s?bot|\bsummari[sz]\w*|\binference\s+api\b", {"llm-api", "llm", "inference"}),
    "email": ("Transactional email", "emails_sent", r"\be-?mails?\b|\bsmtp\b|\bnewsletters?\b", {"transactional-email", "transactional", "smtp"}),
    "hosting": ("Hosting / VPS", None, r"\bhost(?:ing|ed)?\b(?!\s+(?:an?\s+)?(?:llm|model))|\bvps\b|\bdeploy\w*|\bserver\b", {"vps", "cloud-hosting", "paas"}),
    "database": ("Database", None, r"\bdatabase\b|\bpostgres\w*|\bvector\s+(?:db|store|database)\b|\brag\b", {"database"}),
    "monitoring": ("Monitoring", None, r"\bmonitor\w*|\buptime\b|\bobservability\b|\blogs?\b", {"uptime-monitoring", "observability", "monitoring"}),
}
_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*([km])?"
QTY_PATTERNS = {
    "gpu_hours": _NUM + r"\s*(?:gpu[- ]?)?(?:hours|hrs|h)\b",
    "scrape_pages": _NUM + r"(?:\s+[a-z-]+){0,3}?\s*(?:pages|urls|sites?)\b",
    "proxy_gb": _NUM + r"\s*gb\b(?:\s+of)?(?:\s+(?:proxy|residential|traffic|bandwidth))?",
    "search_queries": _NUM + r"\s*(?:search(?:es)?|queries|serp\s+(?:calls|requests))\b",
    "emails_sent": _NUM + r"(?:\s+[a-z-]+){0,2}?\s*e-?mails?\b",
}
JS_RE = r"\bjs\b|javascript|headless|render\w*|dynamic\s+(?:pages|sites)|single[- ]page\s+app|\bspa\b"
BUDGET_RE = (r"(?:budget|under|max(?:imum)?|up\s+to|less\s+than|spend(?:ing)?|cap)\s*(?:of\s*|is\s*|:\s*)?(?:about\s*)?\$\s?"
             + _NUM)  # a bare "$N/mo" is a price someone pays (e.g. a free plan at $0/mo), not a budget
NEGATION_RE = re.compile(r"\b(?:no|without|not|never|don'?t\s+need|doesn'?t\s+need|zero)\s+(?:\w+\s+){0,2}$")
MODEL_SIZE_RE = r"\b(\d+(?:\.\d+)?)\s?b\b(?:\s*(?:param\w*|model|llm))?"


def _n(num: str, suf: str | None) -> float:
    v = float(num.replace(",", ""))
    return v * {"k": 1e3, "m": 1e6}.get((suf or "").lower(), 1)


def parse(description: str) -> dict:
    """Deterministic keyword/regex parse. Returns components, quantities, model size, budget and what matched."""
    text = (description or "")[:MAX_DESC].lower()
    comps, matched, excluded = [], {}, []
    for c, (_, _, rx, _) in COMPONENTS.items():
        # Skip mentions that are negated ("no GPUs", "without proxies"); count the first non-negated one.
        m = next((x for x in re.finditer(rx, text) if not NEGATION_RE.search(text[max(0, x.start() - 40):x.start()])), None)
        if m:
            comps.append(c); matched[c] = m.group(0).strip()
        elif re.search(rx, text):
            excluded.append(c)
    qty = {}
    for need, rx in QTY_PATTERNS.items():
        m = re.search(rx, text)
        if m:
            qty[need] = _n(m.group(1), m.group(2))
    # "100 GB" alone is only proxy traffic when proxies are mentioned; GB of VRAM etc. is not traffic.
    if "proxy_gb" in qty and "proxy" not in comps:
        qty.pop("proxy_gb")
    if "emails_sent" in qty and "email" not in comps:
        qty.pop("emails_sent")
    size = None
    ms = re.search(MODEL_SIZE_RE, text)
    if ms:
        size = float(ms.group(1))
    gm = None
    mg = re.search(r"\b(h100|h200|a100|b200|l40s|l4|a10g?|rtx\s?\d{4})\b", text)
    if mg:
        g = mg.group(1).upper().replace(" ", "")
        gm = "RTX " + g[3:] if g.startswith("RTX") else g
    js = bool(re.search(JS_RE, text))
    budget = None
    mb = re.search(BUDGET_RE, text)
    if mb:
        g = mb.groups()
        budget = _n(g[0], g[1]) or None  # a $0 "budget" is not a budget
    for need, c in (("gpu_hours", "gpu"), ("scrape_pages", "scraping"), ("proxy_gb", "proxy"),
                    ("search_queries", "search"), ("emails_sent", "email")):
        if need in qty and c not in comps and c not in excluded:
            comps.append(c); matched.setdefault(c, f"quantity: {qty[need]:g}")
    return {"components": comps, "quantities": qty, "model_size_b": size, "gpu_model": gm, "js_rendering": js,
            "monthly_budget_usd": budget, "matched": matched, "excluded": excluded}


def _disclose(o: dict) -> dict:
    o = dict(o)
    o["referral_disclosure"] = DISCLOSURE if o.get("affiliate") else None
    if o.get("manual_signup_only") or o.get("signup") == "manual_only":
        o["manual_signup_only"] = True
        o["signup_note"] = o.get("signup_note") or "A human must sign up; the vendor bans automated signups."
    return o


def vram_needed_gb(size_b: float) -> float:
    """FP16 weights (2 bytes/param) + 20% for KV cache/activations. Shown to the caller as an assumption."""
    return round(size_b * 2 * 1.2, 1)


def _deal_fallback(deals: list[dict], tags: set, allowed: set, manual: set) -> list[dict]:
    rows = []
    for d in deals:
        if d["id"] not in allowed or d.get("example") or not (set(d.get("tags") or []) & tags) \
                or set(d.get("tags") or []) & NOT_A_SERVICE_TAGS:
            continue
        if not isinstance(d.get("price_usd"), (int, float)) or not d.get("source_url") or not d.get("verified_at"):
            continue
        per = d.get("billing_period")
        monthly = (float(d["price_usd"]) if per == "month" or d["price_usd"] == 0
                   else round(d["price_usd"] / 12, 2) if per == "year" else None)
        calc = (f"entry price ${d['price_usd']:g}/mo ({d.get('unit') or 'plan'})" if per == "month"
                else f"${d['price_usd']:g}/yr / 12 = ${monthly:,.2f}/mo ({d.get('unit') or 'plan'})" if per == "year" and d["price_usd"]
                else "free tier ($0)" if d["price_usd"] == 0 else
                f"${d['price_usd']:g} {d.get('unit') or ''}".strip() + " (usage price; monthly total depends on usage you didn't give)")
        rows.append(_disclose({"rate_id": offer_rate_id(d.get("advertiser"), "deal", deal_id=d["id"]), "vendor": d.get("advertiser"), "plan": d.get("unit") or d.get("title"), "deal_id": d["id"],
                               "monthly_cost_usd": monthly, "unit_price_usd": d["price_usd"], "billing_period": per, "calc": calc,
                               "quote": d.get("pricing_note"), "source_url": d.get("source_url"), "verified_at": d.get("verified_at"),
                               "affiliate": bool(d.get("affiliate")), "signup": d.get("signup"), "signup_note": d.get("signup_note"),
                               "manual_signup_only": d["id"] in manual, "deal_url": stack.deal_page_url(d["id"])}))
    rows.sort(key=lambda r: (r["monthly_cost_usd"] is None, r["monthly_cost_usd"] or 0, r["unit_price_usd"], r["vendor"] or ""))
    return rows


def _apply_data_age(lines: list[dict], max_h, now) -> int:
    """T37: flag every option with data_age_hours/degraded/stale; with max_h drop older options, promote the
    freshest remaining alternative, and mark a line no_data if nothing fresh is left. Returns options dropped."""
    from . import data_age
    try:
        max_h = data_age.validate_max_age(max_h)
    except ValueError as e:
        raise stack.StackError(str(e))
    dropped = 0
    for l in lines:
        opts = [o for o in [l.get("choice")] + list(l.get("alternatives") or []) if o]
        for o in opts:
            o.update(data_age.age_fields(o, now))
        if max_h is None or not opts:
            continue
        keep = [o for o in opts if not data_age.too_old(o, max_h, now)]
        dropped += len(opts) - len(keep)
        if keep and keep[0] is l.get("choice"):
            l["alternatives"] = keep[1:]
        elif keep:
            l.update(choice=keep[0], alternatives=keep[1:])
            if l.get("status") in ("priced", "entry_price"):
                l["monthly_cost_usd"] = keep[0].get("monthly_cost_usd")
        else:
            l.update(status="no_data", choice=None, monthly_cost_usd=None, alternatives=[],
                     note=f"{NO_DATA} verified within {max_h:g} hours")
    return dropped


def plan(description: str, deals: list[dict], stack_data: dict, gpu_data: dict | None, *, workload: str | None = None,
         gpu_hours: float | None = None, gpu_model: str | None = None, model_size_b: float | None = None,
         scrape_pages: float | None = None, js_rendering: bool | None = None, proxy_gb: float | None = None,
         search_queries: float | None = None, emails_sent: float | None = None, llm_api: bool | None = None,
         monthly_budget_usd: float | None = None, exclude_manual_signup: bool = False,
         max_data_age_hours: float | None = None, now=None) -> dict:
    if not (description or "").strip() and not workload and not any(
            v for v in (gpu_hours, gpu_model, model_size_b, scrape_pages, proxy_gb, search_queries, emails_sent, llm_api)):
        raise stack.StackError("describe the agent (e.g. 'scrapes 20k JS pages and summarizes them with an LLM') or set a field")
    for k, v in (("gpu_hours", gpu_hours), ("model_size_b", model_size_b), ("scrape_pages", scrape_pages), ("proxy_gb", proxy_gb),
                 ("search_queries", search_queries), ("emails_sent", emails_sent), ("monthly_budget_usd", monthly_budget_usd)):
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or v > stack.MAX_QTY):
            raise stack.StackError(f"{k} must be a number 0-{stack.MAX_QTY}")
    p = parse(" ".join(filter(None, [description, workload])))
    q = dict(p["quantities"])
    comps = list(p["components"])
    for need, val, comp in (("gpu_hours", gpu_hours, "gpu"), ("scrape_pages", scrape_pages, "scraping"), ("proxy_gb", proxy_gb, "proxy"),
                            ("search_queries", search_queries, "search"), ("emails_sent", emails_sent, "email")):
        if val is not None:
            q[need] = val
            if val and comp not in comps:
                comps.append(comp)
    size = model_size_b if model_size_b is not None else p["model_size_b"]
    if (gpu_model or size) and "gpu" not in comps and not ("gpu" in p["excluded"] and gpu_model is None and model_size_b is None):
        comps.append("gpu")
    if llm_api and "llm_api" not in comps:
        comps.append("llm_api")
    gpu_model = gpu_model or p["gpu_model"]
    js = p["js_rendering"] if js_rendering is None else js_rendering
    budget = monthly_budget_usd if monthly_budget_usd is not None else p["monthly_budget_usd"]
    if not comps:
        raise stack.StackError("no components recognised; mention e.g. GPU, scraping, proxies, search API, LLM API, email, "
                               "hosting, database or monitoring, or set the structured fields")

    allowed = allowed_deal_ids(deals)
    manual = {d["id"] for d in deals if d.get("signup") == "manual_only"}
    sdata = copy.deepcopy(stack_data)
    before = len(sdata.get("offers") or [])
    sdata["offers"] = [o for o in sdata.get("offers") or [] if o.get("deal_id") in allowed]
    excluded = before - len(sdata["offers"])
    gdata = copy.deepcopy(gpu_data) if gpu_data else None
    assumptions = []
    if gdata:
        n0 = len(gdata.get("rates") or [])
        gdata["rates"] = [r for r in gdata.get("rates") or [] if not r.get("deal_id") or r["deal_id"] in allowed]
        excluded += n0 - len(gdata["rates"])

    lines = []
    for c in comps:
        label, need, _, tags = COMPONENTS[c]
        if c == "scraping" and js:
            need = "scrape_pages_js"
            q.setdefault("scrape_pages_js", q.pop("scrape_pages", None))
            if q["scrape_pages_js"] is None:
                q.pop("scrape_pages_js")
        line = {"component": c, "label": label + (" (JS rendering)" if need == "scrape_pages_js" else ""),
                "matched": p["matched"].get(c, "structured field")}
        if need == "gpu_hours":
            if not gdata:
                lines.append({**line, "status": "no_data", "note": NO_DATA, "choice": None, "monthly_cost_usd": None}); continue
            if size:
                need_gb = vram_needed_gb(size)
                gdata["rates"] = [r for r in gdata["rates"] if (r.get("vram_gb") or 0) >= need_gb]
                line["vram_needed_gb"] = need_gb
                assumptions.append(f"{size:g}B model: {size:g} x 2 bytes (FP16) x 1.2 overhead = {need_gb:g} GB VRAM on one GPU for inference; "
                                   "quantized models need less, full fine-tuning needs several times more.")
            hours = q.get("gpu_hours")
            opts = stack._gpu_options(gdata, hours or 1, gpu_model, manual)
            if exclude_manual_signup:
                opts = [o for o in opts if not (o.get("manual_signup_only") or o.get("deal_id") in manual)]
            opts.sort(key=lambda x: (x["monthly_cost_usd"], x["vendor"] or ""))
            if not opts:
                why = f" with >= {line.get('vram_needed_gb')} GB VRAM on one GPU" if size else ""
                lines.append({**line, "status": "no_data", "note": NO_DATA + why + (f" for {gpu_model}" if gpu_model else ""),
                              "choice": None, "monthly_cost_usd": None}); continue
            opts = [_disclose({**o, "verified_at": o.pop("checked_at", None)}) for o in opts]
            if hours:
                line.update(status="priced", quantity=hours, unit="GPU-hours/month", choice=opts[0],
                            monthly_cost_usd=opts[0]["monthly_cost_usd"], alternatives=opts[1:4])
            else:
                best = opts[0]
                line.update(status="needs_quantity", choice=best, monthly_cost_usd=None, alternatives=opts[1:4],
                            note=f"cheapest sourced rate shown (calc at 1 hour: {best['calc']}); give gpu_hours for a monthly estimate")
            lines.append(line); continue
        if need:
            qty = q.get(need)
            r = stack.optimize(sdata, {need: qty or 1}, None, exclude_manual_signup=exclude_manual_signup)["lines"][0]
            if r["status"] == "priced":
                ch = _disclose({**r["choice"], "verified_at": r["choice"].pop("checked_at", None)})
                alts = [_disclose({**a, "verified_at": a.pop("checked_at", None)}) for a in r["alternatives"]]
                if qty:
                    line.update(status="priced", quantity=qty, unit=r["unit"], choice=ch, monthly_cost_usd=ch["monthly_cost_usd"], alternatives=alts)
                else:
                    line.update(status="needs_quantity", unit=r["unit"], choice=ch, monthly_cost_usd=None, alternatives=alts,
                                note=f"entry plan shown (cheapest plan at minimal usage: ${ch['monthly_cost_usd']:g}/mo); "
                                     f"give a quantity in {r['unit']} for an estimate")
                line["untracked_providers"] = r.get("untracked_providers", [])
                lines.append(line); continue
        rows = _deal_fallback(deals, tags, allowed, manual)
        if exclude_manual_signup:
            rows = [x for x in rows if not x["manual_signup_only"]]
        if rows:
            best = rows[0]
            line.update(status="entry_price" if best["monthly_cost_usd"] is not None else "unit_price", choice=best,
                        monthly_cost_usd=best["monthly_cost_usd"], alternatives=rows[1:4],
                        note="cheapest cited entry price among tracked providers; your usage may need a bigger plan")
        else:
            line.update(status="no_data", note=NO_DATA, choice=None, monthly_cost_usd=None, alternatives=[])
        lines.append(line)

    excluded_too_old = _apply_data_age(lines, max_data_age_hours, now)
    known = [l for l in lines if l["status"] in ("priced", "entry_price") and isinstance(l["monthly_cost_usd"], (int, float))]
    total = round(sum(l["monthly_cost_usd"] for l in known), 2)
    math_line = " + ".join(f"${l['monthly_cost_usd']:,.2f} ({l['component']})" for l in known) + f" = ${total:,.2f}/mo" if known else None
    complete = len(known) == len(lines)
    out = {
        "parsed": {"components": comps, "quantities": {k: v for k, v in q.items() if v is not None}, "model_size_b": size,
                   "gpu_model": gpu_model, "js_rendering": js, "monthly_budget_usd": budget, "matched": p["matched"], "excluded": p["excluded"],
                   "method": "deterministic keyword/regex parse; no LLM"},
        "lines": lines,
        "monthly_estimate_usd": total, "estimate_math": math_line, "estimate_is_complete": complete,
        "missing_components": [l["component"] for l in lines if l not in known],
        "budget": None,
        "excluded_for_compliance": excluded,
        "max_data_age_hours": max_data_age_hours, "excluded_too_old": excluded_too_old,
        "manual_signup_components": [l["component"] for l in lines if (l.get("choice") or {}).get("manual_signup_only")],
        "ranking": f"Per component, the {stack.TRACKED} with a cited price (vendors we don't track may cost less). "
                   "Affiliate status is never a ranking factor; referral links are disclosed per option.",
        "assumptions": assumptions + [
            "Each component is priced on its own, monthly list prices before tax.",
            f"'{NO_DATA}' means no cited price exists in the data; nothing is estimated.",
            "Confirm on each source_url and get the user's approval before any paid signup."],
    }
    if budget is not None:
        out["budget"] = {"monthly_budget_usd": budget, "estimate_usd": total,
                         "within_budget": (total <= budget) if complete else None,
                         "note": None if complete else "estimate is incomplete (see missing_components); can't judge the budget"}
    return out
