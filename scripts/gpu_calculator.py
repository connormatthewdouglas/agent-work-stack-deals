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

PAGE_PATH = "tools/gpu-cost-calculator"
API_PATH = ROOT / "api" / "v1" / "gpu-prices.json"


def build_payload(gen, deals: list[dict], feed_updated: str) -> dict:
    data = build_rates(deals)
    if data["problems"]:  # invalid pricing records fail the build instead of silently dropping rates
        raise SystemExit("gpu pricing records invalid:\n  " + "\n  ".join(data["problems"]))
    payload = {
        "schema": "lantern-works-gpu-prices/1",
        "source_feed": f"{gen.BASE}/api/v1/deals.json",
        "feed_updated_at": feed_updated,
        "hours_per_month": HOURS_PER_MONTH,
        "ranking": "Ascending estimated monthly cost for the requested usage. Affiliate status is not a ranking factor.",
        "methodology": [
            "Rates come from structured per-vendor pricing records (data/gpu_pricing/<vendor>.json in the repo); each rate has source_url and checked_at, and 'basis' is the exact vendor quote.",
            "A daily job re-fetches every source_url and flags records older than 7 days or unreachable pages; prices are never auto-edited.",
            "billing_unit is per-second, hourly or monthly; price_usd/unit give the hourly (unit 'hour') or flat monthly price; per-second prices are also in price_per_second_usd. interruptible=true means the vendor may preempt the job.",
            "Hourly rates bill while running; monthly rates are flat dedicated servers (ceil(hours/730) servers per GPU).",
            "Totals exclude storage, egress, extra vCPU and taxes; each vendor's published egress/storage/interruption terms (or \"unknown\") are in vendors[].extras with source_url. Confirm on the vendor page before spending.",
        ],
        "rates": data["rates"],
        "vendors": data["vendors"],
        "free_credits": data["free_credits"],
        "unpriced": data["unpriced"],
    }
    gen.assert_public_clean(payload)
    return payload


def write(gen, deals: list[dict], feed_updated: str) -> str:
    payload = build_payload(gen, deals, feed_updated)
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
    <label>GPU hours per month <input id="hours" type="number" min="0" max="20000" step="1" value="100" inputmode="numeric"></label>
    <label>GPUs <input id="gpus" type="number" min="1" max="64" step="1" value="1" inputmode="numeric"></label>
    <label>GPU model <select id="gpu"><option value="">Any</option>{opts}</select></label>
    <label>Min VRAM (GB) <select id="vram"><option value="">Any</option><option>24</option><option>48</option><option>80</option></select></label>
    <label><input id="flat" type="checkbox" checked> Include flat monthly servers</label>
  </form>
  <p><span id="summary" aria-live="polite"></span> <a id="permalink" href="?">Link to this estimate</a></p>
  <div style="overflow-x:auto"><table class="howto" id="results"><thead><tr><th>Est. / month</th><th>GPU</th><th>Vendor</th><th>Billing</th><th>Calculation</th><th>Vendor quote (verified)</th><th>Label</th></tr></thead><tbody></tbody></table></div>
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
  <h2>For agents</h2>
  <p>Machine-readable rates: <a href="{api}">{api}</a> (each rate has <code>deal_id</code>, <code>price_usd</code>, <code>unit</code>, <code>hourly_equiv_usd</code>, <code>basis</code>, <code>verified_at</code>). Inputs can be preset in the URL, e.g. <code>?hours=300&amp;gpu=A100</code>.</p>
  <script>
  const R={data_js}, H={HOURS_PER_MONTH};
  const $=id=>document.getElementById(id), fmt=n=>"$"+n.toLocaleString("en-US",{{minimumFractionDigits:2,maximumFractionDigits:2}});
  const q=new URLSearchParams(location.search);
  for (const k of ["hours","gpus","gpu","vram"]) if (q.get(k)!==null) $(k).value=q.get(k);
  if (q.get("flat")==="0") $("flat").checked=false;
  function esc(s){{return String(s??"").replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]))}}
  function run(){{
    const h=Math.max(0,+$("hours").value||0), g=Math.max(1,Math.floor(+$("gpus").value||1)), m=$("gpu").value, v=+$("vram").value||0, flat=$("flat").checked;
    const rows=R.filter(r=>(!m||r.gpu===m||r.gpu.startsWith(m+" "))&&(!v||(r.vram_gb||0)>=v)&&(flat||r.unit==="hour")).map(r=>{{
      if(r.unit==="hour") return {{...r,cost:r.price_usd*h*g,calc:`$${{r.price_usd}}/hr × ${{h}} h × ${{g}}`}};
      const n=Math.max(1,Math.ceil(h/H))*g; return {{...r,cost:r.price_usd*n,calc:`$${{r.price_usd}}/mo × ${{n}} server(s)`}};
    }}).sort((a,b)=>a.cost-b.cost||a.advertiser.localeCompare(b.advertiser));
    $("results").tBodies[0].innerHTML=rows.map(r=>`<tr><td><strong>${{fmt(r.cost)}}</strong></td><td>${{esc(r.gpu)}}${{r.vram_gb?` ${{r.vram_gb}} GB`:""}}</td><td><a href="${{esc(r.redeem_url)}}" rel="nofollow sponsored noopener" data-deal="${{esc(r.deal_id)}}">${{esc(r.advertiser)}}</a></td><td>${{esc(r.tier)}}, ${{esc(r.billing)}}</td><td>${{esc(r.calc)}}</td><td><a href="${{esc(r.source_url)}}" rel="noopener">“${{esc(r.basis)}}”</a> · ${{esc((r.verified_at||"").slice(0,10))}}</td><td>${{r.affiliate?"referral":"public"}}</td></tr>`).join("")||'<tr><td colspan="7">No priced option matches.</td></tr>';
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
