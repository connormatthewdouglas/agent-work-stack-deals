"""Agent Stack Optimizer page (/tools/stack-optimizer/) + machine-readable /api/v1/stack-pricing.json.

Static and client-side; the same logic as core/stack.py (MCP tool optimize_stack). Prices come only from
cited records in data/stack_pricing/ and /api/v1/gpu-prices.json; anything unpublished says "No published price".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core import stack  # noqa: E402
from core.data_license import DATA_LICENSE  # noqa: E402

PAGE_PATH = "tools/stack-optimizer"
API_PATH = ROOT / "api" / "v1" / "stack-pricing.json"
EXAMPLE = {"scrape_pages": 50000, "proxy_gb": 10, "emails_sent": 10000, "gpu_hours": 100}
EXAMPLE_GPU = "H100"
DEFAULT_VIEW = ("gpu_hours",)  # shown by default; scraping, proxy, email and search sit behind the "more needs" toggle


from core.deals import latest_checked_at  # noqa: E402


def _gpu_verified() -> list:
    p = ROOT / "api" / "v1" / "gpu-prices.json"
    return [r.get("verified_at") for r in json.loads(p.read_text(encoding="utf-8")).get("rates", [])] if p.exists() else []


def build_payload(gen, deals: list[dict], feed_updated: str) -> dict:
    data = stack.build_payload(deals, base=gen.BASE)
    if data.pop("problems"):
        raise SystemExit("stack pricing records invalid:\n  " + "\n  ".join(stack.build_payload(deals)["problems"]))
    return {
        "schema": "lantern-works-stack-pricing/1",
        "license": DATA_LICENSE,
        "source_feed": f"{gen.BASE}/api/v1/deals.json",
        "gpu_prices": f"{gen.BASE}/api/v1/gpu-prices.json",
        # Derived from the data, never build time (audit T8/M5): newest of the deal feed, every offer's checked_at and GPU rates' verified_at.
        "feed_updated_at": latest_checked_at([feed_updated] + [o.get("checked_at") for o in data.get("offers") or []] + _gpu_verified()),
        "deal_feed_updated_at": feed_updated,
        "ranking": f"Per need, the {stack.TRACKED}, by estimated monthly cost. Affiliate status is not a ranking factor.",
        "methodology": [
            "Offers come from structured per-vendor records (data/stack_pricing/<vendor>.json in the repo); each has the vendor quote, source_url and checked_at, and the same daily job as GPU prices re-fetches every source_url.",
            "Cost = monthly_usd if ceil(quantity x units_per_item) <= included, else monthly_usd + ceil(extra / overage_per) x overage_usd. No published overage price means the plan can't cover more than it includes.",
            "A null monthly_usd, included or units_per_item means the vendor doesn't publish it: the offer is reported as not published, never estimated.",
            "Deals pulled from the public feed are dropped; signup 'manual_only' deals are flagged (a human must sign up).",
            "GPU hours use /api/v1/gpu-prices.json (1 GPU; storage, egress and taxes excluded).",
        ],
        **data,
    }


def _cell_line(gen, l: dict) -> str:
    esc = gen.esc
    c = l["choice"]
    if not c:
        return (f'<tr><td>{esc(l["label"])}<br><small>{l["quantity"]:,} {esc(l["unit"])}</small></td><td><strong>No published price</strong></td>'
                f'<td colspan="3">No tracked provider publishes a price that covers this.</td></tr>')
    flag = ' <strong>Manual signup only</strong>' if c["manual_signup_only"] else ""
    return (f'<tr><td>{esc(l["label"])}<br><small>{l["quantity"]:,} {esc(l["unit"])}</small></td>'
            f'<td><strong>${c["monthly_cost_usd"]:,.2f}</strong></td>'
            f'<td><a href="{esc(c["deal_url"])}">{esc(c["vendor"])}</a> {esc(c["plan"])}{flag}<br><small>{esc(c["calc"])}</small></td>'
            f'<td><a href="{esc(c["source_url"])}" rel="noopener">“{esc(c["quote"])}”</a><br><small>checked {esc((c["checked_at"] or "")[:10])}</small></td>'
            f'<td><small>{esc(" ".join(c["assumptions"]))}</small></td></tr>')


def write(gen, deals: list[dict], feed_updated: str) -> str:
    payload = build_payload(gen, deals, feed_updated)
    API_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    gpu = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    esc = gen.esc
    example = stack.optimize(payload, EXAMPLE, gpu, gpu_model=EXAMPLE_GPU)
    ex_rows = "".join(_cell_line(gen, l) for l in example["lines"])
    gpu_slim = {"hours_per_month": gpu.get("hours_per_month"), "unpriced": [{"advertiser": u.get("advertiser")} for u in gpu.get("unpriced") or []],
                "rates": [{k: r.get(k) for k in ("advertiser", "gpu", "price_usd", "unit", "tier", "billing", "basis", "source_url",
                                                 "verified_at", "deal_id", "affiliate", "redeem_url", "interruptible")} for r in gpu["rates"]]}
    js_data = json.dumps({"s": {k: payload[k] for k in ("needs", "offers", "untracked", "manual_only_deal_ids")}, "g": gpu_slim},
                         ensure_ascii=False).replace("</", "<\\/")
    models = sorted({r["gpu"].split(" ")[0] if r["gpu"].split(" ")[0] in ("H100", "H200", "A100", "L40S", "B200") else r["gpu"] for r in gpu["rates"]})
    opts = "".join(f'<option{" selected" if m == EXAMPLE_GPU else ""}>{esc(m)}</option>' for m in models)
    def _field(k, v):
        return (f'<label>{esc(v["label"])} <small>({esc(v["unit"])})</small> <input id="n-{k}" name="{k}" type="number" min="0" step="any" '
                f'value="{EXAMPLE.get(k, 0)}" inputmode="decimal"></label>')
    fields = "".join(_field(k, v) for k, v in payload["needs"].items() if k in DEFAULT_VIEW)
    more_fields = "".join(_field(k, v) for k, v in payload["needs"].items() if k not in DEFAULT_VIEW)
    gpu_example = stack.optimize(payload, {"gpu_hours": EXAMPLE["gpu_hours"]}, gpu, gpu_model=EXAMPLE_GPU)
    gpu_rows = "".join(_cell_line(gen, l) for l in gpu_example["lines"])
    offers_rows = "".join(
        f'<tr><td>{esc(payload["needs"][o["need"]]["label"])}</td><td><a href="{esc(o["deal_url"])}">{esc(o["vendor"])}</a> {esc(o["plan"])}'
        f'{" <strong>Manual signup only</strong>" if o["signup"] == "manual_only" else ""}</td>'
        f'<td>{"Usage-based, see vendor" if o["monthly_usd"] is None else "$" + format(o["monthly_usd"], ",g") + "/mo"}</td>'
        f'<td>{"Not published" if o["included"] is None else format(o["included"], ",")}{"" if o["units_per_item"] in (1, None) else " credits"}'
        f'{" (" + format(o["units_per_item"], "g") + " per item)" if o["units_per_item"] not in (1, None) else (" (per-item usage not published)" if o["units_per_item"] is None else "")}</td>'
        f'<td>{"none published" if o["overage_usd"] is None else "$" + format(o["overage_usd"], "g") + " per " + format(o["overage_per"], ",g")}</td>'
        f'<td><a href="{esc(o["source_url"])}" rel="noopener">“{esc(o["quote"])}”</a> · {esc(o["checked_at"][:10])}</td></tr>'
        for o in payload["offers"])
    api = f"{gen.BASE}/api/v1/stack-pricing.json"
    body = f"""  <nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › Tools › Agent Stack Optimizer</nav>
  <h1>Agent Stack Optimizer</h1>
  <p>Start with GPU hours: enter how many your agent needs each month and it picks the cheapest tracked GPU rate. Turn on <em>more needs</em> to add scraping, proxy traffic, email and search. It picks the cheapest suitable plan per need, {stack.TRACKED} (vendors we don't track may cost less). Every line shows the vendor quote, its source page, when we checked it, and the assumptions. If a vendor doesn't publish a number, the line says <strong>No published price</strong>; nothing is guessed. Referral links never change the order.</p>
  <form id="opt" onsubmit="return false" aria-label="Monthly needs" hidden>
    <label class="wide">Describe your needs (optional) <input id="desc" type="text" placeholder="scrape 50k pages/mo + 10 GB residential proxies + send 10k emails + 100 H100-hours"></label>
    <p><button type="button" id="parse">Fill the form from this text</button> <small id="parsed" aria-live="polite"></small></p>
    {fields}
    <label>GPU model <select id="gpumodel"><option value="">Any</option>{opts}</select></label>
    <label class="wide check"><input id="showmore" type="checkbox"> More needs: also price scraping, proxies, email and search</label>
    <fieldset id="more" class="wide" hidden style="border:0;padding:0;margin:0;display:contents">{more_fields}</fieldset>
    <label><input id="nomanual" type="checkbox"> Skip plans that need a manual signup</label>
  </form>
  <div id="out" aria-live="polite" hidden></div>
  <p id="plink" hidden><a id="permalink" href="?">Link to this stack</a></p>
  <noscript><p>The interactive optimizer needs JavaScript. Below is a worked example and every tracked offer; agents can call the <code>optimize_stack</code> MCP tool or read <a href="{api}">{api}</a>.</p></noscript>

  <h2 id="example">Example: {EXAMPLE["gpu_hours"]} {EXAMPLE_GPU} hours a month</h2>
  <div class="tscroll"><table class="howto"><thead><tr><th>Need</th><th>Est. / month</th><th>Cheapest tracked plan</th><th>Vendor quote</th><th>Assumptions</th></tr></thead><tbody>{gpu_rows}</tbody></table></div>
  <p>Compare every GPU rate on the <a href="{gen.BASE}/gpu/">GPU price comparison</a>.</p>

  <details id="more-needs"><summary>More needs: scraping, proxies, email and search (full-stack example and every tracked offer)</summary>
  <h3>Example: 50,000 pages + 10 GB residential proxies + 10,000 emails + 100 H100 hours</h3>
  <div class="tscroll"><table class="howto"><thead><tr><th>Need</th><th>Est. / month</th><th>Cheapest tracked plan</th><th>Vendor quote</th><th>Assumptions</th></tr></thead><tbody>{ex_rows}</tbody></table></div>
  <p>Total of priced lines: <strong>${example["total_monthly_usd"]:,.2f}/month</strong>{"" if example["total_is_complete"] else " (some needs have no published price)"}.{" Manual signup needed for: " + esc(", ".join(example["manual_signup_needs"])) + "." if example["manual_signup_needs"] else ""}</p>

  <h2>How it's calculated</h2>
  <ul>
    <li>Each need is priced on its own: a plan's monthly price if your volume fits what it includes, plus published overage (rounded up to whole packs), else the plan doesn't qualify.</li>
    <li>Credit-based plans convert your quantity with the vendor's published rate (e.g. 5 credits per JS-rendered page).</li>
    <li>Monthly list prices before tax; free tiers count when your volume fits. Plans that share one credit pool across needs aren't combined.</li>
    <li>Plans marked <strong>Manual signup only</strong> need a human to sign up; agents shouldn't automate it.</li>
    <li>Prices are re-fetched from each source page daily; confirm on the vendor page before you spend.</li>
  </ul>
  <h3>Every tracked offer</h3>
  <div class="tscroll"><table class="howto"><thead><tr><th>Need</th><th>Vendor plan</th><th>Price</th><th>Included</th><th>Overage</th><th>Vendor quote · checked</th></tr></thead><tbody>{offers_rows}</tbody></table></div>
  </details>
  <p>GPU hours use the <a href="{gen.BASE}/tools/gpu-cost-calculator/">GPU cost calculator</a> data.</p>
  <h2>For agents</h2>
  <p>MCP: <code>optimize_stack(scrape_pages=50000, proxy_gb=10, emails_sent=10000, gpu_hours=100, gpu_model="H100")</code>. Data: <a href="{api}">{api}</a>. Inputs can be preset in the URL, e.g. <code>?scrape_pages=50000&amp;emails_sent=10000</code>.</p>
  <script>
  const D={js_data};
  const $=id=>document.getElementById(id), N=Object.keys(D.s.needs), fmt=n=>"$"+n.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}}), g=n=>n.toLocaleString("en-US",{{maximumFractionDigits:6}});
  function esc(s){{return String(s??"").replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]))}}
  const manual=new Set(D.s.manual_only_deal_ids);
  function cost(o,q){{
    if(o.units_per_item==null) return {{unknown:"usage per item not published"}};
    if(o.monthly_usd==null) return {{unknown:"plan price not published"}};
    if(o.included==null) return {{unknown:"quantity included in the plan not published"}};
    const u=Math.ceil(q*o.units_per_item), conv=o.units_per_item!==1?`${{g(q)}} x ${{g(o.units_per_item)}} = ${{g(u)}} credits; `:"";
    if(u<=o.included) return {{cost:o.monthly_usd,calc:`${{conv}}within ${{g(o.included)}} included at $${{g(o.monthly_usd)}}/mo`}};
    if(o.overage_usd==null) return {{unsuitable:1}};
    const p=Math.ceil((u-o.included)/o.overage_per); let x=p*o.overage_usd, calc=`${{conv}}$${{g(o.monthly_usd)}}/mo incl. ${{g(o.included)}} + ${{g(p)}} x $${{g(o.overage_usd)}} per ${{g(o.overage_per)}} extra`;
    if(o.min_purchase_usd&&x<o.min_purchase_usd){{x=o.min_purchase_usd;calc+=` (raised to the $${{g(o.min_purchase_usd)}} minimum purchase)`}}
    return {{cost:Math.round((o.monthly_usd+x)*100)/100,calc}};
  }}
  function gpuOpts(h,m){{
    const H=D.g.hours_per_month||730;
    return D.g.rates.filter(r=>!m||r.gpu===m||r.gpu.startsWith(m+" ")).map(r=>{{
      const hr=r.unit==="hour", n=Math.max(1,Math.ceil(h/H)), c=hr?r.price_usd*h:r.price_usd*n;
      return {{vendor:r.advertiser,plan:r.gpu+(r.tier?` (${{r.tier}})`:""),deal_id:r.deal_id,monthly_cost_usd:Math.round(c*100)/100,
        calc:hr?`$${{g(r.price_usd)}}/hr x ${{g(h)}} h`:`$${{g(r.price_usd)}}/mo x ${{n}} server(s), flat regardless of hours`,quote:r.basis,source_url:r.source_url,checked_at:r.verified_at,
        assumptions:["Excludes storage, egress, extra vCPU and taxes.","1 GPU; hourly rates bill while running."].concat(r.interruptible?["Interruptible: the vendor may preempt the job."]:[]),
        manual_signup_only:manual.has(r.deal_id),redeem_url:r.redeem_url,deal_url:"{gen.BASE}/deals/"+r.deal_id.replace(/^deal-/,"").replace(/[^a-zA-Z0-9_-]+/g,"-").replace(/^-+|-+$/g,"").toLowerCase()+"/"}}}});
  }}
  function optimize(q,m,nomanual){{
    return N.filter(k=>q[k]>0).map(k=>{{
      const need=D.s.needs[k]; let priced=[],unknown=[],untracked;
      if(k==="gpu_hours"){{priced=gpuOpts(q[k],m);untracked=D.g.unpriced.map(u=>u.advertiser)}}
      else{{for(const o of D.s.offers){{if(o.need!==k)continue;const c=cost(o,q[k]);
        if(c.unknown)unknown.push({{...o,reason:c.unknown}});else if(c.cost!=null)priced.push({{...o,monthly_cost_usd:c.cost,calc:c.calc,manual_signup_only:o.signup==="manual_only"}})}}
        untracked=D.s.untracked[k]||[]}}
      if(nomanual)priced=priced.filter(p=>!p.manual_signup_only);
      priced.sort((a,b)=>a.monthly_cost_usd-b.monthly_cost_usd||a.vendor.localeCompare(b.vendor)||a.plan.localeCompare(b.plan));
      const best=[],seen=new Set();for(const p of priced)if(!seen.has(p.vendor)){{seen.add(p.vendor);best.push(p)}}
      const uv=[],us=new Set();for(const u of unknown)if(!us.has(u.vendor)){{us.add(u.vendor);uv.push(u)}}
      return {{k,need,q:q[k],choice:best[0]||null,alts:best.slice(1,4),unknown:uv,untracked}};
    }});
  }}
  function src(c){{return `<a href="${{esc(c.source_url)}}" rel="noopener">“${{esc(c.quote)}}”</a><br><small>checked ${{esc((c.checked_at||"").slice(0,10))}}</small>`}}
  function render(lines){{
    if(!lines.length){{$("out").innerHTML="<p>Enter at least one quantity above 0.</p>";return}}
    let tot=0,unk=[];
    const rows=lines.map(l=>{{const c=l.choice;
      const head=`<td>${{esc(l.need.label)}}<br><small>${{g(l.q)}} ${{esc(l.need.unit)}}</small></td>`;
      let more="";
      if(l.alts.length)more+=`<br><small>Next: ${{l.alts.map(a=>`${{esc(a.vendor)}} ${{esc(a.plan)}} ${{fmt(a.monthly_cost_usd)}}`).join("; ")}}</small>`;
      if(l.unknown.length)more+=`<br><small>No published price: ${{l.unknown.map(u=>`<a href="${{esc(u.source_url)}}" rel="noopener">${{esc(u.vendor)}}</a> (${{esc(u.reason)}})`).join("; ")}}</small>`;
      if(l.untracked.length)more+=`<br><small>Not priced yet: ${{l.untracked.length}} other tracked deal(s), e.g. ${{l.untracked.slice(0,5).map(esc).join(", ")}}</small>`;
      if(!c){{unk.push(l.need.label);return `<tr>${{head}}<td><strong>No published price</strong></td><td colspan="3">No tracked provider publishes a price that covers this volume.${{more}}</td></tr>`}}
      tot+=c.monthly_cost_usd;
      return `<tr>${{head}}<td><strong>${{fmt(c.monthly_cost_usd)}}</strong></td><td><a href="${{esc(c.redeem_url||c.deal_url)}}" rel="nofollow sponsored noopener" data-deal="${{esc(c.deal_id)}}">${{esc(c.vendor)}}</a> ${{esc(c.plan)}}${{c.manual_signup_only?" <strong>Manual signup only</strong>":""}}<br><small>${{esc(c.calc)}}</small>${{more}}</td><td>${{src(c)}}</td><td><small>${{esc(c.assumptions.join(" "))}}</small></td></tr>`}}).join("");
    $("out").innerHTML=`<p><strong>Estimated ${{fmt(tot)}}/month</strong> for the priced lines${{unk.length?`; no published price for: ${{esc(unk.join(", "))}}`:""}}. Cheapest among tracked providers per need.</p><div class="tscroll"><table class="howto"><thead><tr><th>Need</th><th>Est. / month</th><th>Plan (calculation)</th><th>Vendor quote</th><th>Assumptions</th></tr></thead><tbody>${{rows}}</tbody></table></div>`;
  }}
  const DEF={json.dumps(list(DEFAULT_VIEW))};
  function read(){{const q={{}},more=$("showmore").checked;for(const k of N)q[k]=(DEF.includes(k)||more)?Math.max(0,+$("n-"+k).value||0):0;return q}}
  function showMore(on){{$("showmore").checked=on;$("more").hidden=!on}}
  $("showmore").addEventListener("change",e=>showMore(e.target.checked));
  function run(){{
    const q=read(),m=$("gpumodel").value,nm=$("nomanual").checked; render(optimize(q,m,nm));
    const p=new URLSearchParams();for(const k of N)if(q[k])p.set(k,q[k]);if(m)p.set("gpu",m);if(nm)p.set("nomanual","1");$("permalink").href="?"+p;
  }}
  const num=s=>{{const m=/^([\\d.,]+)\\s*(k|m)?$/i.exec(s.trim());if(!m)return 0;const v=parseFloat(m[1].replace(/,/g,""));return v*({{k:1e3,m:1e6}}[(m[2]||"").toLowerCase()]||1)}};
  function parse(t){{
    t=t.toLowerCase();const q={{}},n="([\\\\d.,]+\\\\s*[km]?)";const R=[
      ["scrape_pages_js",new RegExp(n+"\\\\s*(?:js|javascript)[- ]?(?:rendered\\\\s*)?pages")],
      ["scrape_pages",new RegExp("(?:scrap\\\\w*|crawl\\\\w*)\\\\s*"+n+"\\\\s*(?:web\\\\s*)?pages|"+n+"\\\\s*(?:web\\\\s*)?pages")],
      ["proxy_gb",new RegExp(n+"\\\\s*gb")],["emails_sent",new RegExp(n+"\\\\s*(?:transactional\\\\s*)?e-?mails")],
      ["search_queries",new RegExp(n+"\\\\s*(?:search(?:es)?|queries|serp)")],["gpu_hours",new RegExp(n+"\\\\s*(?:x\\\\s*)?(?:[a-z]*\\\\d+[a-z]*[- ]?)?(?:gpu[- ]?)?h(?:ou)?rs?")]];
    for(const [k,re] of R){{const m=re.exec(t);if(m){{const v=num(m.slice(1).find(Boolean)||"");if(v)q[k]=v}}}}
    const gm=/(h100|h200|a100|l40s|b200|rtx\\s*\\d{{4}})/i.exec(t);return {{q,gm:gm?gm[1].toUpperCase().replace(/RTX\\s*/,"RTX "):""}};
  }}
  $("parse").addEventListener("click",()=>{{const r=parse($("desc").value);for(const k of N)$("n-"+k).value=r.q[k]||0;
    if(N.some(k=>!DEF.includes(k)&&r.q[k]))showMore(true);
    if(r.gm&&[...$("gpumodel").options].some(o=>o.value===r.gm))$("gpumodel").value=r.gm;
    const got=Object.keys(r.q).filter(k=>r.q[k]);$("parsed").textContent=got.length?"Filled: "+got.map(k=>D.s.needs[k].label+" "+g(r.q[k])).join(", ")+". Check the numbers.":"Couldn't read any quantities; fill the fields instead.";run();
    document.dispatchEvent(new CustomEvent("lw:event",{{detail:"optimizer"}}))}});
  const u=new URLSearchParams(location.search);
  if([...u.keys()].length){{for(const k of N)$("n-"+k).value=u.get(k)||0;if(u.get("gpu")!==null)$("gpumodel").value=u.get("gpu");$("nomanual").checked=u.get("nomanual")==="1";showMore(N.some(k=>!DEF.includes(k)&&+(u.get(k)||0)>0))}}
  $("opt").hidden=false;$("out").hidden=false;$("plink").hidden=false;
  $("opt").addEventListener("input",run);run();
  $("opt").addEventListener("input",()=>document.dispatchEvent(new CustomEvent("lw:event",{{detail:"optimizer"}})),{{once:true}});
  </script>
"""
    out = ROOT / PAGE_PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell("Agent Stack Optimizer: cheapest scraping, proxy, email, search and GPU stack — Lantern Works",
                                  "Describe your agent's monthly needs and get the cheapest suitable plan per need among tracked providers, with vendor quotes, source links, check dates and assumptions. Unpublished prices are never guessed.",
                                  f"{gen.BASE}/{PAGE_PATH}/", body), encoding="utf-8")
    return PAGE_PATH
