"""/report-price/: static 'wrong price' report flow (T40). No server: the form builds a prefilled GitHub issue
from .github/ISSUE_TEMPLATE/wrong-price.yml (GitHub issue forms prefill fields from query params by field id).
Vendor/GPU choices and the shown price are read in the browser from the live /api/v1/gpu-prices.json, never baked in.
Deep link: /report-price/?deal_id=...&gpu=...&tier=...&vram_gb=... preselects a row."""
from __future__ import annotations

import json
from pathlib import Path

PATH = "report-price"
REPO = "https://github.com/connormatthewdouglas/agent-work-stack-deals"
TEMPLATE = "wrong-price.yml"
FIELDS = ("vendor", "gpu", "shown_price", "observed_price", "source_url", "page_url", "deal_id", "observed_at", "notes")


def issue_url(**vals: str) -> str:
    """Python twin of the page's JS, used by tests and for no-JS fallback links."""
    from urllib.parse import urlencode
    q = {"template": TEMPLATE, "title": f"[wrong price] {vals.get('vendor', '')} {vals.get('gpu', '')}".strip()}
    q.update({k: v for k, v in vals.items() if k in FIELDS and v})
    return f"{REPO}/issues/new?{urlencode(q)}"


JS = """<script>
(function(){
const REPO=%(repo)s, TPL=%(tpl)s, f=document.getElementById("rp"), out=document.getElementById("rp-link"), st=document.getElementById("rp-status");
const $=id=>document.getElementById(id); let rows=[];
const key=r=>[r.deal_id,r.gpu,r.vram_gb,r.tier,r.gpu_count].join("|");
const label=r=>r.gpu+(r.vram_gb?" "+r.vram_gb+" GB":"")+" · "+r.tier+(r.gpu_count>1?" · "+r.gpu_count+"x":"");
function vendors(){const s=$("rp-vendor");const vs=[...new Set(rows.map(r=>r.advertiser))].sort((a,b)=>a.localeCompare(b));
 s.innerHTML='<option value="">Choose vendor</option>'+vs.map(v=>'<option>'+v.replace(/</g,"&lt;")+'</option>').join("");}
function gpus(){const v=$("rp-vendor").value,s=$("rp-row");const rs=rows.filter(r=>r.advertiser===v);
 s.innerHTML='<option value="">Choose GPU</option>'+rs.map(r=>'<option value="'+key(r).replace(/"/g,"&quot;")+'">'+label(r).replace(/</g,"&lt;")+'</option>').join("");pick();}
function pick(){const r=rows.find(x=>key(x)===$("rp-row").value);
 $("rp-shown").value=r&&r.hourly_equiv_usd!=null?r.hourly_equiv_usd:"";$("rp-src").value=r?(r.source_url||""):"";build();}
function build(){const r=rows.find(x=>key(x)===$("rp-row").value);const v=$("rp-vendor").value;
 const gpu=r?label(r):"";const q=new URLSearchParams({template:TPL,title:("[wrong price] "+v+" "+(r?r.gpu:"")).trim()});
 const add=(k,x)=>{if(x)q.set(k,x)};add("vendor",v);add("gpu",gpu);add("shown_price",$("rp-shown").value);
 add("observed_price",$("rp-obs").value);add("source_url",$("rp-src").value);add("page_url",$("rp-page").value);
 add("deal_id",r?r.deal_id:"");add("observed_at",new Date().toISOString());add("notes",$("rp-notes").value);
 out.href=REPO+"/issues/new?"+q.toString();}
f.addEventListener("input",build);$("rp-vendor").addEventListener("change",gpus);$("rp-row").addEventListener("change",pick);
fetch("/api/v1/gpu-prices.json").then(r=>r.json()).then(d=>{rows=(d.rates||[]);vendors();
 const p=new URLSearchParams(location.search);$("rp-page").value=p.get("page")||document.referrer||"";
 const m=rows.find(r=>r.deal_id===p.get("deal_id")&&(!p.get("gpu")||r.gpu===p.get("gpu"))&&(!p.get("tier")||r.tier===p.get("tier"))&&(!p.get("vram_gb")||String(r.vram_gb)===p.get("vram_gb")));
 if(m){$("rp-vendor").value=m.advertiser;gpus();$("rp-row").value=key(m);pick();}
 st.textContent="Loaded "+rows.length+" tracked rates from the live feed ("+(d.feed_updated_at||"")+").";build();})
 .catch(()=>{st.textContent="Couldn't load the live feed; type the details on GitHub instead.";});
build();
})();
</script>
"""


def write(g) -> str:
    base = g.BASE
    fallback = issue_url()
    body = f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › <a href="{base}/methodology/">Methodology</a> › Report a wrong price</nav>
  <h1>Report a wrong GPU price</h1>
  <p>Saw a different price on a vendor's page than the one Lantern Works shows? Tell us and it will be re-checked by hand against the vendor's own page. Nothing changes in the feed until it is verified there (see <a href="{base}/methodology/">how prices are checked</a>).</p>
  <p>This form doesn't send anything by itself: it opens a prefilled issue on GitHub (a free GitHub account is needed) that you review and submit. Reports are public, so don't include account or billing details.</p>
  <form id="rp" class="report-form" onsubmit="return false">
    <p id="rp-status" class="meta">Loading tracked rates from the live feed…</p>
    <label>Vendor<br><select id="rp-vendor"><option value="">Choose vendor</option></select></label>
    <label>GPU and tier<br><select id="rp-row"><option value="">Choose GPU</option></select></label>
    <label>Price we show (USD per GPU-hour)<br><input id="rp-shown" inputmode="decimal" readonly></label>
    <label>Price you saw (USD, with its unit)<br><input id="rp-obs" placeholder="e.g. 2.49/hr per GPU"></label>
    <label>Vendor page URL where you saw it<br><input id="rp-src" type="url" placeholder="https://"></label>
    <label>Lantern Works page you were on<br><input id="rp-page" type="url"></label>
    <label>Notes (region, min GPUs, spot or on-demand…)<br><textarea id="rp-notes" rows="3"></textarea></label>
    <p><a id="rp-link" class="btn" href="{fallback}" rel="noopener" target="_blank">Open prefilled report on GitHub</a></p>
  </form>
  <noscript><p>JavaScript is off: <a href="{fallback}">open the blank report form on GitHub</a>.</p></noscript>
  <h2 id="fields">What a report contains</h2>
  <ul>
    <li><strong>Vendor</strong>, <strong>GPU</strong> (with VRAM and tier) and the feed <code>deal_id</code></li>
    <li><strong>Shown price</strong>: our <code>hourly_equiv_usd</code> for that row, read from the live feed</li>
    <li><strong>Observed price</strong> and the <strong>source URL</strong> where you saw it, plus when you checked</li>
  </ul>
  <p class="meta">Agents and scripts can open the same report directly: <code>{REPO}/issues/new?template={TEMPLATE}&amp;vendor=…&amp;gpu=…&amp;shown_price=…&amp;observed_price=…&amp;source_url=…</code></p>
  <style>.report-form label{{display:block;margin:.6em 0;max-width:100%}}.report-form select,.report-form input,.report-form textarea{{width:100%;max-width:32em;box-sizing:border-box;font:inherit;padding:.35em}}.report-form .btn{{display:inline-block;padding:.5em .9em;border:1px solid currentColor;border-radius:6px;text-decoration:none}}</style>
{JS % {"repo": json.dumps(REPO), "tpl": json.dumps(TEMPLATE)}}"""
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell("Report a wrong GPU price | Lantern Works",
                                "Saw a different GPU rental price on a vendor's page? Open a prefilled report so Lantern Works re-checks it against the vendor's own page.",
                                f"{base}/{PATH}/", body), encoding="utf-8")
    return PATH
