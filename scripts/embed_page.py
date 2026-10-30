"""/embed/: embeddable live GPU price badge (T22). embed/badge.js and embed/badge.html read
/api/v1/gpu-prices.json in the visitor's browser (CORS *), so no number is baked into the badge or this page.
Rules: GPU-only feed; reserved and dedicated-monthly rows are never used; held_stale vendors are skipped;
wording is 'lowest tracked', never 'cheapest overall'; every badge credits Lantern Works (CC BY 4.0)."""
from __future__ import annotations

import html
import json
from pathlib import Path

PATH = "embed"
FAMILIES = {"H100": "h100", "A100": "a100", "H200": "h200", "L40S": "l40s", "RTX 4090": "rtx-4090",
            "RTX 5090": "rtx-5090", "RTX A6000": "rtx-a6000"}

BADGE_JS = r"""/* Lantern Works live GPU price badge. Data: Lantern Works, CC BY 4.0. https://thelanternworks.com/embed/ */
(function(){
var BASE="__BASE__", FAM=__FAM__;
var BUCKETS={"on-demand":["on-demand"],"spot":["interruptible","community","marketplace"]};
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function pickRow(d,gpu,match,bucket){
  var held={};(d.held_stale||[]).forEach(function(h){if(h.scope!=="record")held[h.vendor]=1});
  var ok=BUCKETS[bucket]||BUCKETS["on-demand"];
  var rs=(d.rates||[]).filter(function(r){
    if(r.hourly_equiv_usd==null||held[r.advertiser]||r.billing_unit!=="hourly")return false;
    if(ok.indexOf(r.tier_class)<0)return false; /* reserved / monthly never used */
    return match==="exact"?r.gpu===gpu:(r.gpu===gpu||r.gpu.indexOf(gpu+" ")===0);
  });
  rs.sort(function(a,b){return a.hourly_equiv_usd-b.hourly_equiv_usd});
  return {row:rs[0],n:rs.length,vendors:rs.map(function(r){return r.advertiser}).filter(function(v,i,a){return a.indexOf(v)===i}).length};
}
/* T54: optional data-ref="your-tag" (or ?ref= on badge.html) is appended to the outbound link; [a-z0-9-_], max 64 chars */
function refOf(el){var r=String(el.getAttribute("data-ref")||"").toLowerCase().replace(/[^a-z0-9_-]/g,"").slice(0,64);return r;}
function withRef(el,url){var r=refOf(el);return r?url+(url.indexOf("?")<0?"?":"&")+"ref="+encodeURIComponent(r):url;}
function render(el,d){
  var gpu=el.getAttribute("data-gpu")||"H100",match=el.getAttribute("data-match")||"family",bucket=el.getAttribute("data-bucket")||"on-demand";
  var p=pickRow(d,gpu,match,bucket),fam=FAM[gpu],link=BASE+(fam?"/gpu/"+fam+"-rental-price/":"/gpu/price-comparison/");
  link=withRef(el,link);
  var label=bucket==="spot"?"spot/community":"on-demand";
  var css="display:inline-block;max-width:100%;box-sizing:border-box;font:13px/1.35 system-ui,sans-serif;border:1px solid #cbd5e1;border-radius:8px;padding:6px 10px;background:#fff;color:#0f172a;text-decoration:none;overflow-wrap:anywhere";
  if(!p.row){el.innerHTML='<a style="'+css+'" href="'+link+'" target="_blank" rel="noopener">'+esc(gpu)+' GPU prices · Lantern Works</a>';return;}
  var r=p.row,day=(r.verified_at||d.feed_updated_at||"").slice(0,10);
  el.innerHTML='<a style="'+css+'" href="'+link+'" target="_blank" rel="noopener" title="Lowest per-GPU-hour '+label+' rate among '+p.n+' tracked rates from '+p.vendors+' providers. Reserved and monthly rates excluded. Confirm on the vendor page before spending.">'+
    '<strong>'+esc(r.gpu)+(r.vram_gb?' '+esc(r.vram_gb)+' GB':'')+'</strong> from <strong>$'+Number(r.hourly_equiv_usd).toFixed(2)+'/GPU-hr</strong> '+
    '<span style="color:#475569">lowest tracked '+label+' rate · '+esc(r.advertiser)+(r.min_gpus>1?' (sold as '+esc(r.min_gpus)+'-GPU only)':'')+' · checked '+esc(day)+'</span>'+
    '<br><span style="color:#64748b;font-size:11px">GPU price data: Lantern Works, CC BY 4.0</span></a>';
}
var els=document.querySelectorAll(".lantern-gpu-badge:not([data-lw-done])");
if(!els.length)return;
fetch(BASE+"/api/v1/gpu-prices.json").then(function(r){return r.json()}).then(function(d){
  if(!/^lantern-works-gpu-prices\/1$/.test(d.schema||""))throw 0;
  for(var i=0;i<els.length;i++){els[i].setAttribute("data-lw-done","1");render(els[i],d);}
}).catch(function(){for(var i=0;i<els.length;i++){els[i].innerHTML='<a href="'+withRef(els[i],BASE+'/gpu/price-comparison/')+'" target="_blank" rel="noopener">GPU prices · Lantern Works</a>';}});
})();
"""

FRAME = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Lantern Works GPU price badge</title>
<style>html,body{margin:0;padding:2px;background:transparent}</style></head><body>
<div class="lantern-gpu-badge" id="b"></div>
<script>var q=new URLSearchParams(location.search),b=document.getElementById("b");["gpu","match","bucket","ref"].forEach(function(k){if(q.get(k))b.setAttribute("data-"+k,q.get(k))});</script>
<script src="badge.js"></script></body></html>
"""


def write(g) -> str:
    base = g.BASE
    d = Path(g.ROOT) / PATH
    d.mkdir(parents=True, exist_ok=True)
    (d / "badge.js").write_text(BADGE_JS.replace("__BASE__", base).replace("__FAM__", json.dumps(FAMILIES)), encoding="utf-8")
    (d / "badge.html").write_text(FRAME, encoding="utf-8")
    js_snip = f'<span class="lantern-gpu-badge" data-gpu="H100"></span>\n<script async src="{base}/embed/badge.js"></script>'
    if_snip = f'<iframe src="{base}/embed/badge.html?gpu=H100" title="H100 GPU price (Lantern Works)"\n  width="340" height="64" style="border:0;max-width:100%" loading="lazy"></iframe>'
    gpus = ", ".join(f"<code>{html.escape(k)}</code>" for k in FAMILIES)
    body = f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › <a href="{base}/for-agents/">For agents</a> › Embed</nav>
  <h1>Embed a live GPU price badge</h1>
  <p>Show the lowest tracked GPU rental rate on your site, blog or docs. The badge reads the live <a href="{base}/api/v1/gpu-prices.json">GPU price feed</a> in the reader's browser each time it loads, so it is always the latest daily check. No API key, no cookies, no tracking.</p>
  <h2 id="preview">Live preview</h2>
  <p><span class="lantern-gpu-badge" data-gpu="H100"></span></p>
  <p><span class="lantern-gpu-badge" data-gpu="RTX 4090" data-bucket="spot"></span></p>
  <h2 id="script">Script tag (recommended)</h2>
  <div class="codebox"><pre>{html.escape(js_snip)}</pre></div>
  <h2 id="iframe">Iframe (no script on your page)</h2>
  <div class="codebox"><pre>{html.escape(if_snip)}</pre></div>
  <h2 id="options">Options</h2>
  <ul>
    <li><code>data-ref</code> (iframe: <code>?ref=</code>): optional tag such as <code>t54-gpuhunt</code>, added as <code>?ref=</code> to the link to Lantern Works so referrals can be counted. Lowercase letters, digits, <code>-</code> and <code>_</code> only, max 64 characters.</li>
    <li><code>data-gpu</code> (iframe: <code>?gpu=</code>): GPU name as in the feed, e.g. {gpus}. Default <code>H100</code>.</li>
    <li><code>data-match</code>: <code>family</code> (default; <code>H100</code> also covers H100 SXM, PCIe and NVLink rows) or <code>exact</code> (only rows whose GPU name is exactly the value).</li>
    <li><code>data-bucket</code>: <code>on-demand</code> (default) or <code>spot</code> (interruptible, community and marketplace rates).</li>
  </ul>
  <h2 id="rules">What the badge shows</h2>
  <ul>
    <li>The lowest per-GPU-hour rate among tracked providers in the chosen bucket, with the vendor, VRAM and the date it was last verified. It never claims to be the cheapest anywhere, only among the providers Lantern Works tracks.</li>
    <li>Reserved, contract and monthly rates are never used. Vendors whose prices are on hold (see <a href="{base}/methodology/#held">methodology</a>) are skipped.</li>
    <li>If a rate is only sold as a multi-GPU server, the badge says so. Some vendor links on Lantern Works are referral links; affiliate status does not affect which rate is shown.</li>
    <li>If the feed can't be loaded, the badge falls back to a plain link and shows no number.</li>
  </ul>
  <h2 id="license">License and credit</h2>
  <p>The data is <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener">CC BY 4.0</a>. The badge already carries the credit line &ldquo;GPU price data: Lantern Works, CC BY 4.0&rdquo; and links back; please keep it if you restyle the badge. See the <a href="{base}/methodology/#license">license section</a>.</p>
  <script async src="{base}/embed/badge.js"></script>
"""
    (d / "index.html").write_text(g.page_shell("Embed a live GPU price badge | Lantern Works",
                                               "Free embeddable badge showing the lowest tracked GPU rental rate (H100, A100, RTX 4090 and more), read live from the Lantern Works price feed. Script or iframe, CC BY 4.0.",
                                               f"{base}/{PATH}/", body), encoding="utf-8")
    return PATH
