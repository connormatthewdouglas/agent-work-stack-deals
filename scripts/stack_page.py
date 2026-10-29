"""/stack/: plan an agent's stack from a plain-text description (same parse + data as MCP optimize_agent_stack).

Presets are computed at build time with core/agent_stack.py from the published GPU, stack-pricing and deal data.
The form parses text in the browser with the SAME regexes (exported from core/agent_stack.py) and hands the
quantities to /tools/stack-optimizer/ (prefilled via URL parameters); components the optimizer doesn't cover
show the cheapest cited entry price computed at build time. Nothing without a cited price is estimated.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core import agent_stack as a  # noqa: E402
from core import stack  # noqa: E402
from core.compliance import allowed_deal_ids  # noqa: E402

PAGE_PATH = "stack"
PRESETS = [
    ("Research agent", "Scrapes 20k JS-rendered pages a month through 5 GB of residential proxies, runs 3,000 search queries, "
                       "summarizes with an LLM and sends 2,000 emails."),
    ("Self-hosted model", "Serves a 13B model on one GPU for 200 GPU hours a month, hosted API with uptime monitoring."),
    ("Outreach agent", "Finds leads with 5,000 search queries, scrapes 10k pages and sends 10,000 emails a month."),
]
OPT_NEEDS = ("scrape_pages", "scrape_pages_js", "proxy_gb", "emails_sent", "search_queries", "gpu_hours")


def optimizer_link(gen, r: dict) -> str:
    q = r["parsed"]["quantities"]
    p = {k: f"{q[k]:g}" for k in OPT_NEEDS if q.get(k)}
    if r["parsed"].get("gpu_model"):
        p["gpu"] = r["parsed"]["gpu_model"]
    return f"{gen.BASE}/tools/stack-optimizer/" + (("?" + urlencode(p)) if p else "")


def _row(gen, l: dict) -> str:
    esc = gen.esc
    c = l.get("choice")
    if not c:
        return f'<tr><td>{esc(l["label"])}</td><td><strong>{esc(a.NO_DATA.capitalize())}</strong></td><td colspan="2">{esc(l.get("note") or "")}</td></tr>'
    cost = (f'${l["monthly_cost_usd"]:,.2f}/mo' if isinstance(l.get("monthly_cost_usd"), (int, float))
            else "Needs a quantity" if l["status"] == "needs_quantity" else "Usage-based")
    if l["status"] == "entry_price":
        cost += " (entry plan)"
    flags = (' <strong>Manual signup only</strong>' if c.get("manual_signup_only") else "") + \
            (f'<br><small>{esc(c["referral_disclosure"])}</small>' if c.get("referral_disclosure") else "")
    who = f'<a href="{esc(c["deal_url"])}">{esc(c["vendor"])}</a>' if c.get("deal_url") else esc(c.get("vendor") or "")
    return (f'<tr><td>{esc(l["label"])}{(" <small>" + format(l["quantity"], ",g") + " " + esc(l.get("unit") or "") + "</small>") if l.get("quantity") else ""}</td>'
            f'<td><strong>{cost}</strong></td><td>{who} {esc(c.get("plan") or "")}{flags}<br><small>{esc(c.get("calc") or "")}'
            f'{("; " + esc(l["note"])) if l.get("note") and l["status"] != "priced" else ""}</small></td>'
            f'<td><a href="{esc(c["source_url"])}" rel="noopener">source</a><br><small>checked {esc(str(c.get("verified_at") or "")[:10])}</small></td></tr>')


def render_plan(gen, r: dict) -> str:
    esc = gen.esc
    rows = "".join(_row(gen, l) for l in r["lines"])
    total = (f'<p><strong>Estimate: {esc(r["estimate_math"])}</strong>' if r["estimate_math"] else "<p><strong>No cited prices for these components.</strong>") + \
            ("" if r["estimate_is_complete"] else f' Incomplete: no monthly figure for {esc(", ".join(r["missing_components"]))}.') + "</p>"
    return (f'<div class="tscroll"><table class="sticky1"><thead><tr><th>Component</th><th>Monthly</th><th>Cheapest cited option</th><th>Source</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>{total}')


def write(gen, deals: list[dict], feed_updated: str) -> str:
    esc = gen.esc
    gpu = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    sp = json.loads((ROOT / "api" / "v1" / "stack-pricing.json").read_text(encoding="utf-8"))
    presets = []
    for name, desc in PRESETS:
        r = a.plan(desc, deals, sp, gpu)
        presets.append(f'<h3>{esc(name)}</h3><p><em>“{esc(desc)}”</em></p>{render_plan(gen, r)}'
                       f'<p><a href="{esc(optimizer_link(gen, r))}">Adjust these quantities in the Stack Optimizer</a></p>')
    allowed = allowed_deal_ids(deals)
    manual = {d["id"] for d in deals if d.get("signup") == "manual_only"}
    entry = {}
    for c, (label, need, _, tags) in a.COMPONENTS.items():
        if need:
            continue
        rows = a._deal_fallback(deals, tags, allowed, manual)
        b = rows[0] if rows else None
        entry[c] = {"label": label, "row": None if not b else {k: b.get(k) for k in (
            "vendor", "plan", "calc", "source_url", "verified_at", "deal_url", "referral_disclosure", "manual_signup_only")}}
    js_data = json.dumps({"comp": {c: v[2] for c, v in a.COMPONENTS.items()}, "labels": {c: v[0] for c, v in a.COMPONENTS.items()},
                          "qty": a.QTY_PATTERNS, "js": a.JS_RE, "entry": entry, "nodata": a.NO_DATA,
                          "opt": f"{gen.BASE}/tools/stack-optimizer/"}, ensure_ascii=False).replace("</", "<\\/")
    body = f"""
  <p class="crumbs"><a href="{gen.BASE}/">Home</a> › Plan an agent stack</p>
  <h1>Plan an agent stack</h1>
  <p>Describe the agent you're building. A keyword parse (no AI model) maps it to components (GPU, scraping, proxies,
  search API, LLM API, email, hosting, database, monitoring) and shows the cheapest option with a cited price among
  tracked providers. Where no tracked vendor publishes a price, it says <strong>{esc(a.NO_DATA)}</strong>. Vendors we
  don't track may cost less. Referral links are labelled and never affect ranking. Data as of {esc((sp.get('feed_updated_at') or feed_updated)[:10])} (newest price check in the data).</p>
  <form id="sf" onsubmit="return false" hidden>
    <label class="wide">What does your agent do? <textarea id="d" rows="3" style="width:100%" placeholder="{esc(PRESETS[0][1])}"></textarea></label>
    <p><button type="button" id="go">Plan it</button></p>
  </form>
  <div id="res" aria-live="polite"></div>
  <h2>Example agents</h2>
  {''.join(presets)}
  <p>Agents can do the same over MCP: <code>optimize_agent_stack</code> in <a href="{gen.BASE}/install/">lantern-works-deals-mcp</a>.
  Quantities per need: <a href="{gen.BASE}/tools/stack-optimizer/">Stack Optimizer</a>. Data:
  <a href="{gen.BASE}/api/v1/gpu-prices.json">gpu-prices.json</a>, <a href="{gen.BASE}/api/v1/stack-pricing.json">stack-pricing.json</a>,
  <a href="{gen.BASE}/api/v1/deals.json">deals.json</a>.</p>
  <script>
  const S={js_data};
  const $=id=>document.getElementById(id), E=s=>String(s??"").replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}})[c]);
  const num=(n,s)=>parseFloat(n.replace(/,/g,""))*({{k:1e3,m:1e6}}[(s||"").toLowerCase()]||1);
  function parse(t){{t=t.slice(0,2000).toLowerCase();const comps=[],q={{}};
    for(const [c,rx] of Object.entries(S.comp))if(new RegExp(rx).test(t))comps.push(c);
    for(const [k,rx] of Object.entries(S.qty)){{const m=t.match(new RegExp(rx));if(m)q[k]=num(m[1],m[2])}}
    if(q.proxy_gb&&!comps.includes("proxy"))delete q.proxy_gb; if(q.emails_sent&&!comps.includes("email"))delete q.emails_sent;
    for(const [k,c] of [["gpu_hours","gpu"],["scrape_pages","scraping"],["proxy_gb","proxy"],["search_queries","search"],["emails_sent","email"]])if(q[k]&&!comps.includes(c))comps.push(c);
    if(q.scrape_pages&&new RegExp(S.js).test(t)){{q.scrape_pages_js=q.scrape_pages;delete q.scrape_pages}}
    const g=t.match(/\\b(h100|h200|a100|b200|l40s|l4|a10g?|rtx\\s?\\d{{4}})\\b/);let gm=null;if(g){{const u=g[1].toUpperCase().replace(/\\s/g,"");gm=u.startsWith("RTX")?"RTX "+u.slice(3):u}}
    return {{comps,q,gm}}}}
  function show(){{const r=parse($("d").value);if(!r.comps.length){{$("res").innerHTML="<p>No components recognised. Mention e.g. GPU, scraping, proxies, search API, LLM, email, hosting, database or monitoring.</p>";return}}
    const p=new URLSearchParams();for(const [k,v] of Object.entries(r.q))if(v)p.set(k,v);if(r.gm)p.set("gpu",r.gm);
    const opt=r.comps.filter(c=>!S.entry[c]);let h="<p>Found: "+r.comps.map(c=>E(S.labels[c])).join(", ")+"</p>";
    if(opt.length)h+='<p><a href="'+S.opt+(p.toString()?"?"+p:"")+'"><strong>Price '+opt.map(c=>E(S.labels[c])).join(", ")+' in the Stack Optimizer</strong></a> ('+(Object.keys(r.q).length?"quantities prefilled; check them":"add monthly quantities there")+")</p>";
    const rows=r.comps.filter(c=>S.entry[c]).map(c=>{{const x=S.entry[c].row;if(!x)return "<tr><td>"+E(S.labels[c])+"</td><td colspan=3><strong>"+E(S.nodata)+"</strong></td></tr>";
      return "<tr><td>"+E(S.labels[c])+"</td><td>"+E(x.calc)+"</td><td>"+(x.deal_url?'<a href="'+E(x.deal_url)+'">'+E(x.vendor)+"</a>":E(x.vendor))+(x.manual_signup_only?" <strong>Manual signup only</strong>":"")+(x.referral_disclosure?"<br><small>"+E(x.referral_disclosure)+"</small>":"")+'</td><td><a href="'+E(x.source_url)+'" rel="noopener">source</a> <small>checked '+E(String(x.verified_at).slice(0,10))+"</small></td></tr>"}}).join("");
    if(rows)h+="<p>Cheapest cited entry prices (your usage may need a bigger plan):</p><div class='tscroll'><table class='sticky1'><thead><tr><th>Component</th><th>Price</th><th>Vendor</th><th>Source</th></tr></thead><tbody>"+rows+"</tbody></table></div>";
    $("res").innerHTML=h;document.dispatchEvent(new CustomEvent("lw:event",{{detail:"stack"}}))}}
  $("go").addEventListener("click",show);$("sf").hidden=false;
  </script>
"""
    out = ROOT / PAGE_PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell("Plan an agent stack: cheapest cited GPU, scraping, proxy, search, LLM and email costs — Lantern Works",
                                  "Describe the agent you're building and see the cheapest option with a cited price per component among tracked providers, with the math, source links and check dates. No sourced price means no number.",
                                  f"{gen.BASE}/{PAGE_PATH}/", body), encoding="utf-8")
    return PAGE_PATH
