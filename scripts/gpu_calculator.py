"""GPU cost calculator page (/tools/gpu-cost-calculator/) + machine-readable /api/v1/gpu-prices.json.

Static and client-side. Rates come only from verified pricing notes in the public feed (core/gpu.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.gpu import HOURS_PER_MONTH, build_rates  # noqa: E402
from core.data_license import DATA_LICENSE, REPORT_ISSUE, REPORT_ISSUE_NOTE  # noqa: E402

PAGE_PATH = "tools/gpu-cost-calculator"
API_PATH = ROOT / "api" / "v1" / "gpu-prices.json"
HISTORY_PATH = ROOT / "api" / "v1" / "gpu-prices" / "history.json"


def write_history(gen) -> dict:
    """/api/v1/gpu-prices/history.json from the committed daily snapshots (data/gpu_pricing/snapshots/)."""
    from core import gpu_history
    hist = gpu_history.build_history(gpu_history.load_snapshots())
    hist["source"] = f"{gen.BASE}/api/v1/gpu-prices.json"
    gen.assert_public_clean(hist)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(hist, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return hist


from core.deals import latest_checked_at  # noqa: E402


def build_payload(gen, deals: list[dict], feed_updated: str) -> dict:
    data = build_rates(deals)
    if data["problems"]:  # invalid pricing records fail the build instead of silently dropping rates
        raise SystemExit("gpu pricing records invalid:\n  " + "\n  ".join(data["problems"]))
    payload = {
        "schema": "lantern-works-gpu-prices/1",
        "license": DATA_LICENSE,
        "report_issue": REPORT_ISSUE,
        "source_feed": f"{gen.BASE}/api/v1/deals.json",
        # Derived from the data, never build time (audit T8/M5): the newest of the deal feed's updated_at and every rate's verified_at.
        "feed_updated_at": latest_checked_at([feed_updated] + [r.get("verified_at") for r in data["rates"]]),
        "prices_verified_through": latest_checked_at(r.get("verified_at") for r in data["rates"]),
        "deal_feed_updated_at": feed_updated,
        "hours_per_month": HOURS_PER_MONTH,
        "ranking": "Ascending estimated monthly cost for the requested usage. Affiliate status is not a ranking factor.",
        "methodology": [
            "Rates come from structured per-vendor pricing records (data/gpu_pricing/<vendor>.json in the repo); each rate has source_url and checked_at, and 'basis' is a summary of the vendor's price line, not a verbatim quote; evidence.quote is the verbatim text found on the source page (or API) at checked_at.",
            "price_check 'manual snapshot' rows (e.g. Clore.ai, whose API blocks the daily job) are not re-checked daily: snapshot_at is when they were captured and hold_after is when they are automatically held unless re-checked. price_check 'rotating snapshot' rows (Spheron RTX 5090) are re-read daily, but the vendor rotates the row text, so the quote is the span seen at checked_at. For marketplace rows (Vast.ai, Clore.ai) evidence.quote summarises API fields rather than page text.",
            "A daily job re-reads every source_url (robots.txt respected) and updates a price only where it parsed it from the vendor's own page or API; verified_at is when the price was last parsed, checked_at the last attempt. A rate not re-verified for 7 days is held (held_stale) and never ranked. Price history: /api/v1/gpu-prices/history.json.",
            "billing_unit is per-second, hourly or monthly; price_usd/unit give the hourly (unit 'hour') or flat monthly price; per-second prices are also in price_per_second_usd. interruptible=true means the vendor may preempt the job.",
            "Hourly rates bill while running; monthly rates are flat dedicated servers (ceil(hours/730) servers per GPU).",
            "Vendors with stale published prices (vendor-level `stale`) are listed in held_stale and never ranked. price_status 'marketplace' rates are variable host prices: price_usd is the median per-GPU offer, with lowest_offer_usd and offer_count. min_gpus > 1 means the instance is only sold with that many GPUs; estimates charge at least that many.",
            "All prices are per GPU. Multi-GPU servers (gpu_count > 1) are divided by gpu_count; server_price_usd / server_hourly_usd give the whole-server price. Each rate's evidence {source_url, quote, checked_at} is the last live check of the vendor page.",
            "Totals exclude storage, egress, extra vCPU and taxes; each vendor's published egress/storage/interruption terms (or \"not published\") are in vendors[].extras with source_url. Confirm on the vendor page before spending.",
            REPORT_ISSUE_NOTE,
        ],
        "rates": data["rates"],
        "vendors": data["vendors"],
        "free_credits": data["free_credits"],
        "unpriced": data["unpriced"],
        "held_stale": data["held_stale"],
    }
    gen.assert_public_clean(payload)
    return payload


def write(gen, deals: list[dict], feed_updated: str) -> str:
    payload = build_payload(gen, deals, feed_updated)
    write_history(gen)
    API_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    esc = gen.esc
    data_js = json.dumps(payload["rates"], ensure_ascii=False).replace("</", "<\\/")
    from core.gpu import FAMILIES
    gpus = sorted({r["gpu"] for r in payload["rates"]} | {f for f in FAMILIES.values() if any(r["gpu"].startswith(f + " ") for r in payload["rates"])})
    opts = "".join(f'<option value="{esc(g)}">{esc(g)}</option>' for g in gpus)
    unpriced = ", ".join(f'<a href="{gen.BASE}/deals/{gen.slug_for(u["deal_id"])}/">{esc(u["advertiser"])}</a>'
                         for u in payload["unpriced"]) or "none"
    credits = "".join(f'<li><a href="{gen.BASE}/deals/{gen.slug_for(c["deal_id"])}/">{esc(c["advertiser"])}</a>: {esc(c["unit"] or "")}</li>'
                      for c in payload["free_credits"])
    api = f"{gen.BASE}/api/v1/gpu-prices.json"
    body = f"""  <nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/categories/gpu-compute/">GPU &amp; compute</a> › GPU cost calculator</nav>
  <h1>GPU cost calculator</h1>
  <p>Estimate monthly GPU cost from prices published by vendors in the Lantern Works feed. Every row shows how its cost was calculated and the vendor quote it came from. Results are sorted by your estimated cost, cheapest among tracked providers first (vendors we don't track may cost less); referral links don't change the order.</p>
  <form id="calc" onsubmit="return false" aria-label="GPU cost inputs">
    <label>GPU hours per month <input id="hours" type="number" min="0.01" max="20000" step="1" value="100" inputmode="numeric"></label>
    <label>GPUs <input id="gpus" type="number" min="1" max="64" step="1" value="1" inputmode="numeric"></label>
    <label>GPU model <select id="gpu"><option value="">Any</option>{opts}</select></label>
    <label>Min VRAM (GB) <select id="vram"><option value="">Any</option><option>24</option><option>48</option><option>80</option></select></label>
    <label><input id="flat" type="checkbox" checked> Include flat monthly servers</label>
  </form>
  <p><span id="summary" aria-live="polite"></span> <a id="permalink" href="?">Link to this estimate</a></p>
  <div class="tscroll"><table class="howto" id="results"><thead><tr><th>Est. / month</th><th>GPU</th><th>Vendor</th><th>Billing</th><th>Calculation</th><th>Vendor quote (verified)</th><th>Link</th></tr></thead><tbody></tbody></table></div>
  <noscript><p>The calculator needs JavaScript. The same data is at <a href="{api}">{api}</a>.</p></noscript>

  <h2>Calculation basis</h2>
  <ul>
    <li>Hourly: rate × hours × GPUs. Billed while the instance runs.</li>
    <li>Monthly dedicated servers: flat price × ceil(hours ÷ {HOURS_PER_MONTH}) × GPUs, whatever your usage.</li>
    <li>Excludes storage, egress, extra vCPU, taxes and promo credits. Prices are "from" prices; confirm on the vendor page before spending.</li>
  </ul>
{__import__("gpu_pages").accuracy_html(gen, payload["rates"])}  <p>Model guides and comparisons: <a href="{gen.BASE}/gpu/price-comparison/">all GPU prices</a> · {__import__("gpu_pages").links_html(gen.BASE, deals)}</p>
  <h2>Free GPU-adjacent credits</h2>
  <ul>{credits}</ul>
  <h2>Not priced yet</h2>
  <p>These GPU deals have no verified, structured GPU price in the feed, so they're left out instead of guessed: {unpriced}.</p>
  <p>Held out as stale (published prices not current, never ranked): {", ".join(f'<a href="{esc(h["source_url"])}" rel="noopener">{esc(h["vendor"])}</a> (vendor page last updated {esc(h.get("page_last_updated") or "not stated")})' for h in payload["held_stale"]) or "none"}.</p>
  <h2>For agents</h2>
  <p>Machine-readable rates: <a href="{api}">{api}</a> (each rate has <code>deal_id</code>, <code>price_usd</code>, <code>unit</code>, <code>hourly_equiv_usd</code>, <code>basis</code>, <code>verified_at</code>). Inputs can be preset in the URL, e.g. <code>?hours=300&amp;gpu=A100</code>.</p>
  <script>
  const R={data_js}, H={HOURS_PER_MONTH};
  const $=id=>document.getElementById(id), fmt=n=>"$"+n.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}});
  const q=new URLSearchParams(location.search);
  for (const k of ["hours","gpus","gpu","vram"]) if (q.get(k)!==null) $(k).value=q.get(k);
  if (q.get("flat")==="0") $("flat").checked=false;
  function esc(s){{return String(s??"").replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]))}}
  // BILL_START (T42): same billing contract as core.gpu.estimate: whole servers/instances only, never fractional GPUs
  function bill(r,h,g){{
    const per=r.gpu_count||1, servers=Math.ceil(Math.max(g,r.min_gpus||1)/per), gg=servers*per;
    if(r.unit==="hour"){{
      let calc=`$${{r.price_usd}}/hr × ${{h}} h × ${{gg}} GPU`;
      if(gg>g) calc+=` (${{g}} requested, ${{gg}} billed: `+(per>1?`sold only as whole ${{per}}-GPU servers, ${{servers}} instance${{servers>1?"s":""}})`:`minimum ${{gg}} GPUs per instance)`);
      if(r.price_status==="marketplace") calc+=`; variable marketplace median, lowest offer $${{r.lowest_offer_usd}}/hr`;
      return {{cost:Math.round(r.price_usd*h*gg*100)/100,calc,requested_gpus:g,billed_gpus:gg,instances:servers}};
    }}
    const n=Math.max(1,Math.ceil(h/H))*gg;
    const calc=per>1?`$${{r.price_usd}}/GPU-mo × ${{n}} GPU-month(s) (sold as ${{per}}-GPU servers at $${{Number(r.server_price_usd).toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}})}}/mo; ${{g}} requested, ${{gg}} billed), flat regardless of hours`:`$${{r.price_usd}}/mo × ${{n}} server(s), flat regardless of hours`;
    return {{cost:Math.round(r.price_usd*n*100)/100,calc,requested_gpus:g,billed_gpus:gg,instances:servers}};
  }}
  // BILL_END
  function run(){{
    // re24 (2): same input contract as the MCP/engine (invalid_argument), no silent clamping
    const hs=String($("hours").value).trim(), gs=String($("gpus").value).trim(), h=Number(hs), g=Number(gs), m=$("gpu").value, v=+$("vram").value||0, flat=$("flat").checked;
    const bad=!(hs!==""&&Number.isFinite(h)&&h>0)?"hours must be a number > 0":!(gs!==""&&Number.isInteger(g)&&g>=1)?"gpus must be an integer >= 1":"";
    if(bad){{ $("results").tBodies[0].innerHTML='<tr><td colspan="7">Invalid input: '+bad+'. No estimate shown.</td></tr>'; $("summary").textContent="invalid_argument: "+bad; return; }}
    const rows=R.filter(r=>(!m||r.gpu===m||r.gpu.startsWith(m+" "))&&(!v||(r.vram_gb||0)>=v)&&(flat||r.unit==="hour")).map(r=>{{
      return {{...r,...bill(r,h,g)}};
    }}).sort((a,b)=>((a.tier_class==="reserved")-(b.tier_class==="reserved"))||a.cost-b.cost||a.advertiser.localeCompare(b.advertiser));
    $("results").tBodies[0].innerHTML=rows.map((r,i)=>(r.tier_class==="reserved"&&(i===0||rows[i-1].tier_class!=="reserved")?'<tr><th colspan="7" id="reserved-rates">Reserved and term-commitment prices: need a reservation or minimum term (see Billing), so they are listed separately, sorted by estimated cost</th></tr>':"")+`<tr><td><strong>${{fmt(r.cost)}}</strong></td><td>${{esc(r.gpu)}}${{r.vram_gb?` ${{r.vram_gb}} GB`:""}}</td><td><a href="${{esc(r.redeem_url)}}" rel="${{r.affiliate?"nofollow sponsored noopener":"noopener"}}" data-deal="${{esc(r.deal_id)}}">${{esc(r.advertiser)}}</a></td><td>${{esc(r.tier)}}, ${{esc(r.billing)}}</td><td>${{esc(r.calc)}}</td><td><a href="${{esc(r.source_url)}}" rel="noopener">“${{esc(r.basis)}}”</a> · ${{esc((r.verified_at||"").slice(0,10))}}</td><td>${{r.affiliate?"Referral link":"Direct link"}}</td></tr>`).join("")||'<tr><td colspan="7">No priced option matches.</td></tr>';
    $("summary").textContent=rows.length?`${{rows.length}} options. Cheapest among tracked providers: ${{rows[0].advertiser}} ${{rows[0].gpu}} at ${{fmt(rows[0].cost)}}/month.`:"No priced option matches these filters.";
    const p=new URLSearchParams({{hours:h,gpus:g}}); if(m)p.set("gpu",m); if(v)p.set("vram",v); if(!flat)p.set("flat","0");
    $("permalink").href="?"+p;
  }}
  $("calc").addEventListener("input",run); run();
  $("calc").addEventListener("input",()=>document.dispatchEvent(new CustomEvent("lw:event",{{detail:"calculator"}})),{{once:true}});
  </script>
"""
    out = ROOT / PAGE_PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell("GPU cost calculator — Lantern Works",
                                  "Estimate monthly GPU cost (A100, H100, RTX 4090 and more) from verified prices of tracked vendors, with the calculation shown and the cheapest among tracked providers first.",
                                  f"{gen.BASE}/{PAGE_PATH}/", body), encoding="utf-8")
    return PAGE_PATH
