/* Lantern Works live GPU price badge. Data: Lantern Works, CC BY 4.0. https://thelanternworks.com/embed/ */
(function(){
var BASE="https://thelanternworks.com", FAM={"H100": "h100", "A100": "a100", "H200": "h200", "L40S": "l40s", "RTX 4090": "rtx-4090", "RTX 5090": "rtx-5090", "RTX A6000": "rtx-a6000"};
var BUCKETS={"on-demand":["on-demand"],"spot":["interruptible","community","marketplace"]};
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
/* Price order for the live GPU badge. Mirrors core.deals.gpu_rate_rank_key:
   reserved last, out-of-stock last, then hourly price, advertiser, gpu.
   Affiliate status is not an input. min_gpus is not an input: singleGpuHeadline
   skips min_gpus above 1 because the engine rank does not.
   isServerlessRate mirrors core.gpu.price_bucket == "serverless" (the word serverless
   in the tier), plus billing_unit "per-second", plus a billing or tier line that says
   per-second or function. headlineEligible is the shared headline rule. The homepage
   and the GPU calculator inline isServerlessRate and headlineEligible from this file. */
function gpuRateRankKey(r) {
  var a = r.availability;
  var oos = a && a.in_stock === false ? 1 : 0;
  var reserved = r.tier_class === "reserved" ? 1 : 0;
  return [reserved, 0, oos, Number(r.hourly_equiv_usd), r.advertiser || "", r.gpu || ""];
}
function cmpGpuRank(a, b) {
  var ka = gpuRateRankKey(a), kb = gpuRateRankKey(b);
  for (var i = 0; i < ka.length; i++) {
    if (ka[i] < kb[i]) return -1;
    if (ka[i] > kb[i]) return 1;
  }
  return 0;
}
function isSingleGpuRate(r) {
  var n = Number(r.min_gpus);
  return !(n > 1);
}
function minGpusLabel(r) {
  var n = Number(r.min_gpus);
  return n > 1 ? (n + "x GPU minimum") : "";
}
function isServerlessRate(r) {
  var tier = String(r.tier || "");
  var billing = String(r.billing || "");
  var blob = (billing + " " + tier).toLowerCase();
  if (tier.toLowerCase().indexOf("serverless") >= 0) return true;
  if (r.billing_unit === "per-second") return true;
  return blob.indexOf("per-second") >= 0 || blob.indexOf("per second") >= 0 || blob.indexOf("function") >= 0;
}
function headlineEligible(r) {
  if (!isSingleGpuRate(r)) return false;
  if (r.tier_class === "reserved") return false;
  if (isServerlessRate(r)) return false;
  return true;
}
function rankGpuRates(rows) {
  return (rows || []).slice().sort(cmpGpuRank);
}
function singleGpuHeadline(rows) {
  var rs = (rows || []).filter(headlineEligible);
  rs.sort(cmpGpuRank);
  return rs.length ? rs[0] : null;
}
function pickRow(d,gpu,match,bucket){
  var held={};(d.held_stale||[]).forEach(function(h){if(h.scope!=="record")held[h.vendor]=1});
  var ok=BUCKETS[bucket]||BUCKETS["on-demand"];
  var rs=(d.rates||[]).filter(function(r){
    if(r.hourly_equiv_usd==null||held[r.advertiser]||r.billing_unit!=="hourly")return false;
    if(ok.indexOf(r.tier_class)<0)return false; /* reserved / monthly never used */
    if(!headlineEligible(r))return false; /* single GPU; not reserved; not serverless or per-second */
    return match==="exact"?r.gpu===gpu:(r.gpu===gpu||r.gpu.indexOf(gpu+" ")===0);
  });
  rs.sort(cmpGpuRank);
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
  el.innerHTML='<a style="'+css+'" href="'+link+'" target="_blank" rel="noopener" title="Lowest per-GPU-hour '+label+' single-GPU rate among '+p.n+' tracked rates from '+p.vendors+' providers. Reserved, monthly, serverless and multi-GPU minimums excluded. Confirm on the vendor page before spending.">'+
    '<strong>'+esc(r.gpu)+(r.vram_gb?' '+esc(r.vram_gb)+' GB':'')+'</strong> from <strong>$'+Number(r.hourly_equiv_usd).toFixed(2)+'/GPU-hr</strong> '+
    '<span style="color:#475569">lowest tracked '+label+' rate · '+esc(r.advertiser)+(minGpusLabel(r)?' ('+esc(minGpusLabel(r))+')':'')+' · checked '+esc(day)+'</span>'+
    '<br><span style="color:#64748b;font-size:11px">GPU price data: Lantern Works, CC BY 4.0</span></a>';
}
var els=document.querySelectorAll(".lantern-gpu-badge:not([data-lw-done])");
if(!els.length)return;
fetch(BASE+"/api/v1/gpu-prices.json").then(function(r){return r.json()}).then(function(d){
  if(!/^lantern-works-gpu-prices\/1$/.test(d.schema||""))throw 0;
  for(var i=0;i<els.length;i++){els[i].setAttribute("data-lw-done","1");render(els[i],d);}
}).catch(function(){for(var i=0;i<els.length;i++){els[i].innerHTML='<a href="'+withRef(els[i],BASE+'/gpu/price-comparison/')+'" target="_blank" rel="noopener">GPU prices · Lantern Works</a>';}});
})();
