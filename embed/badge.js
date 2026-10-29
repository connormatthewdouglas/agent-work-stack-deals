/* Lantern Works live GPU price badge. Data: Lantern Works, CC BY 4.0. https://thelanternworks.com/embed/ */
(function(){
var BASE="https://thelanternworks.com", FAM={"H100": "h100", "A100": "a100", "H200": "h200", "L40S": "l40s", "RTX 4090": "rtx-4090", "RTX 5090": "rtx-5090", "RTX A6000": "rtx-a6000"};
var BUCKETS={"on-demand":["on-demand"],"spot":["interruptible","community","marketplace"]};
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function pickRow(d,gpu,match,bucket){
  var held={};(d.held_stale||[]).forEach(function(h){held[h.vendor]=1});
  var ok=BUCKETS[bucket]||BUCKETS["on-demand"];
  var rs=(d.rates||[]).filter(function(r){
    if(r.hourly_equiv_usd==null||held[r.advertiser]||r.billing_unit!=="hourly")return false;
    if(ok.indexOf(r.tier_class)<0)return false; /* reserved / monthly never used */
    return match==="exact"?r.gpu===gpu:(r.gpu===gpu||r.gpu.indexOf(gpu+" ")===0);
  });
  rs.sort(function(a,b){return a.hourly_equiv_usd-b.hourly_equiv_usd});
  return {row:rs[0],n:rs.length,vendors:rs.map(function(r){return r.advertiser}).filter(function(v,i,a){return a.indexOf(v)===i}).length};
}
function render(el,d){
  var gpu=el.getAttribute("data-gpu")||"H100",match=el.getAttribute("data-match")||"family",bucket=el.getAttribute("data-bucket")||"on-demand";
  var p=pickRow(d,gpu,match,bucket),fam=FAM[gpu],link=BASE+(fam?"/gpu/"+fam+"-rental-price/":"/gpu/price-comparison/");
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
}).catch(function(){for(var i=0;i<els.length;i++){els[i].innerHTML='<a href="'+BASE+'/gpu/price-comparison/" target="_blank" rel="noopener">GPU prices · Lantern Works</a>';}});
})();
