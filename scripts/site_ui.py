"""Shared site navigation plus homepage search/filter/compare UI (static, progressive enhancement).

Without JavaScript the homepage is the full, ordered list of deals and the filter form stays hidden;
with JavaScript the form filters the cards in place and up to 3 deals can be compared side by side.
"""
from __future__ import annotations

from html import escape

NAV_ITEMS = [
    ("", "GPU prices"),
    ("deals/", "Deals"),
    ("ai-agent-tool-deals/", "Compare & categories"),
    ("gpu/price-comparison/", "All GPU rates"),
    ("tools/gpu-cost-calculator/", "GPU calculator"),
    ("stack/", "Plan a stack"),
    ("tools/stack-optimizer/", "Stack optimizer"),
    ("install/", "Install (MCP)"),
    ("for-agents/", "For agents"),
    ("changelog/", "Changelog"),
]

SECTIONS = {"ai-agent-tool-deals/": ("compare/", "categories/", "guides/"), "gpu/price-comparison/": ("gpu/",)}

CSS = """
    .tscroll { overflow-x: auto; -webkit-overflow-scrolling: touch; max-width: 100%; }
    .tscroll table.sticky1 th:first-child, .tscroll table.sticky1 td:first-child { position: sticky; left: 0; background: #fff; z-index: 1; box-shadow: 1px 0 0 #ddd; }
    .tscroll table.sticky1 th:first-child { background: #f3f3f3; }
    @media (max-width: 640px) {
      .rates-cards table, .rates-cards tbody, .rates-cards tr, .rates-cards td { display: block; width: 100%; }
      .rates-cards thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
      .rates-cards tr { border: 1px solid #ddd; border-radius: 8px; margin: 0 0 .75rem; padding: .25rem .5rem; background: #fff; }
      .rates-cards tr[hidden] { display: none; }
      .howto .rates-cards td { border: 0; border-bottom: 1px solid #eee; padding: .3rem 0; overflow-wrap: anywhere; }
      .rates-cards td:last-child { border-bottom: 0; }
      .rates-cards td::before { content: attr(data-label); display: block; font-size: .75rem; color: #555; font-weight: 600; }
    }
    .sitenav { display: flex; flex-wrap: wrap; gap: .25rem .9rem; font-size: .9rem; padding: .5rem 0 .75rem; border-bottom: 1px solid #ddd; margin-bottom: 1rem; }
    .sitenav a { margin: 0; }
    .sitenav a[aria-current] { font-weight: 700; color: #111; text-decoration: none; }
    .skip { position: absolute; left: -999px; } .skip:focus { left: 1rem; top: 1rem; background: #fff; padding: .4rem; z-index: 9; }
    #filters { background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: .75rem 1rem; margin: 1rem 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .5rem .9rem; align-items: end; }
    #filters label { display: flex; flex-direction: column; font-size: .85rem; gap: .2rem; }
    #filters label.check { flex-direction: row; align-items: center; gap: .4rem; }
    #filters input[type=search], #filters select, #filters input[type=number] { font: inherit; padding: .3rem .4rem; }
    #filters .wide { grid-column: 1 / -1; }
    .cmp-pick { font-size: .85rem; margin-left: .5rem; }
    #cmp-tray { position: sticky; bottom: 0; background: #111; color: #eee; padding: .6rem 1rem; border-radius: 8px 8px 0 0; display: flex; gap: .75rem; align-items: center; flex-wrap: wrap; }
    #cmp-tray button { font: inherit; }
    #cmp-view table { width: 100%; border-collapse: collapse; background: #fff; font-size: .9rem; }
    #cmp-view th, #cmp-view td { border: 1px solid #ddd; padding: .4rem .5rem; text-align: left; vertical-align: top; }
    #cmp-view th[scope=row] { background: #f3f3f3; width: 9rem; }
    [hidden] { display: none !important; }
    .visually-hidden { position: absolute !important; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
"""


def nav_html(base: str, canonical: str = "") -> str:
    links = []
    for path, label in NAV_ITEMS:
        href = f"{base}/{path}"
        rel = canonical[len(base) + 1:] if canonical.startswith(base + "/") else None
        if rel is not None and rel.rstrip("/") == path.rstrip("/"):
            cur = ' aria-current="page"'
        elif rel and path and any(rel.startswith(pre) for pre in SECTIONS.get(path, ())):
            cur = ' aria-current="true"'
        else:
            cur = ""
        links.append(f'<a href="{href}"{cur}>{escape(label)}</a>')
    return ('  <a class="skip" href="#content">Skip to content</a>\n'
            f'  <nav class="sitenav" aria-label="Site">{"".join(links)}</nav>\n')


OFFER_LABELS = {
    "verified_discount": "Vendor discount",
    "free_tier": "Free tier",
    "listed_discount": "Listed discount (unverified)",
    "trial": "Trial",
    "standard_referral": "Standard signup",
    "credit_only_referral": "Signup credit",
}


def filter_form_html(categories: list[str], offer_types: list[str]) -> str:
    cats = "".join(f'<option value="{escape(c)}">{escape(c)}</option>' for c in categories)
    offers = "".join(f'<option value="{escape(o)}">{escape(OFFER_LABELS.get(o, o))}</option>' for o in offer_types)
    return f"""  <form id="filters" role="search" aria-label="Search and filter deals" hidden onsubmit="return false">
    <label class="wide">Search deals <input id="f-q" type="search" placeholder="e.g. proxies, H100, email API" autocomplete="off"></label>
    <label>Category <select id="f-cat"><option value="">All</option>{cats}</select></label>
    <label>Offer type <select id="f-offer"><option value="">All</option>{offers}</select></label>
    <label>Max price (USD) <input id="f-max" type="number" min="0" step="any" inputmode="decimal" placeholder="any"></label>
    <label class="check"><input id="f-free" type="checkbox"> Free tier only</label>
    <label class="check"><input id="f-ver" type="checkbox"> Verified only</label>
    <p class="wide" style="margin:0"><span id="f-count" aria-live="polite"></span> · <a id="f-link" href="./">Link to these results</a></p>
  </form>
  <noscript><p class="meta">Search, filters and side-by-side compare need JavaScript. All deals are listed below by category, and the <a href="/ai-agent-tool-deals/">comparison pages</a> work without it.</p></noscript>
  <section id="cmp-view" hidden aria-labelledby="cmp-h" tabindex="-1"><h2 id="cmp-h">Side-by-side comparison</h2><div id="cmp-table" style="overflow-x:auto"></div></section>
  <div id="cmp-tray" hidden role="region" aria-label="Compare selection"><span id="cmp-n"></span><button type="button" id="cmp-go">Compare side by side</button><button type="button" id="cmp-clear">Clear</button></div>
"""


HOME_JS = r"""  <script>
(()=>{
  const $=id=>document.getElementById(id), cards=[...document.querySelectorAll("article.deal")], form=$("filters");
  if(!form||!cards.length) return;
  form.hidden=false;
  const q=new URLSearchParams(location.search), map={q:"f-q",cat:"f-cat",offer:"f-offer",max:"f-max"};
  for(const [k,id] of Object.entries(map)) if(q.get(k)) $(id).value=q.get(k);
  if(q.get("free")==="1") $("f-free").checked=true; if(q.get("verified")==="1") $("f-ver").checked=true;
  const txt=new Map(cards.map(c=>[c,c.textContent.toLowerCase()]));
  function apply(){
    const s=$("f-q").value.trim().toLowerCase(), cat=$("f-cat").value, off=$("f-offer").value, max=parseFloat($("f-max").value), fr=$("f-free").checked, ve=$("f-ver").checked;
    let n=0;
    for(const c of cards){
      const d=c.dataset, p=d.price===""?NaN:+d.price;
      const ok=(!s||s.split(/\s+/).every(w=>txt.get(c).includes(w)))&&(!cat||d.category===cat)&&(!off||d.offer===off)
        &&(isNaN(max)||(!isNaN(p)&&p<=max))&&(!fr||d.free==="1")&&(!ve||d.verified==="1");
      c.hidden=!ok; if(ok) n++;
    }
    for(const sec of document.querySelectorAll("main section")) sec.hidden=![...sec.querySelectorAll("article.deal")].some(a=>!a.hidden);
    $("f-count").textContent=`${n} of ${cards.length} deals shown`;
    const p=new URLSearchParams();
    for(const [k,id] of Object.entries(map)) if($(id).value) p.set(k,$(id).value);
    if(fr)p.set("free","1"); if(ve)p.set("verified","1");
    $("f-link").href=p.toString()?"?"+p:"./";
  }
  let t; form.addEventListener("input",()=>{ apply(); clearTimeout(t); t=setTimeout(()=>{ if($("f-q").value.trim()) document.dispatchEvent(new CustomEvent("lw:search",{detail:{active:true}})); },1200); }); apply();
  // compare up to 3
  const picked=[];
  for(const c of cards){
    const l=document.createElement("label"); l.className="cmp-pick";
    l.innerHTML=`<input type="checkbox"> Compare<span class="visually-hidden"> ${c.querySelector("h2 a").textContent}</span>`;
    const box=l.firstChild;
    box.addEventListener("change",()=>{
      if(box.checked){ if(picked.length>=3){box.checked=false; $("cmp-n").textContent="You can compare up to 3 deals."; return;} picked.push(c); }
      else picked.splice(picked.indexOf(c),1);
      $("cmp-tray").hidden=!picked.length; $("cmp-n").textContent=`${picked.length} selected (max 3)`; $("cmp-go").disabled=picked.length<2;
    });
    c.querySelector(".meta").append(l);
  }
  const esc=s=>String(s??"").replace(/[&<>"]/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch]));
  $("cmp-clear").onclick=()=>{for(const c of picked) c.querySelector(".cmp-pick input").checked=false; picked.length=0; $("cmp-tray").hidden=true; $("cmp-view").hidden=true;};
  $("cmp-go").onclick=()=>{
    const rows=[["Deal",c=>`<a href="${esc(c.querySelector("h2 a").href)}">${esc(c.querySelector("h2 a").textContent)}</a>`],
      ["Vendor",c=>esc(c.dataset.advertiser)],["Category",c=>esc(c.dataset.category)],["Offer",c=>esc(c.dataset.offerLabel)],
      ["Price",c=>c.dataset.price===""?esc(c.dataset.priceLabel||"Pricing on vendor site"):"$"+esc(c.dataset.price)+(c.dataset.unit?" / "+esc(c.dataset.unit):"")],
      ["Free tier",c=>c.dataset.free==="1"?"Yes":"Not listed"],["Verified",c=>c.dataset.verifiedAt?esc(c.dataset.verifiedAt.slice(0,10)):"<em>unverified</em>"],
      ["Link type",c=>c.dataset.affiliate==="true"?"affiliate (rel=sponsored)":"public"],["Details",c=>esc(c.querySelector(".instructions")?.textContent||"")]];
    $("cmp-table").innerHTML=`<table><thead><tr><td></td>${picked.map(c=>`<th scope="col">${esc(c.dataset.advertiser)}</th>`).join("")}</tr></thead><tbody>${rows.map(([h,f])=>`<tr><th scope="row">${h}</th>${picked.map(c=>`<td>${f(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    document.dispatchEvent(new CustomEvent("lw:event",{detail:"compare"}));
    $("cmp-view").hidden=false; $("cmp-view").focus(); $("cmp-view").scrollIntoView({block:"start"});
  };
})();
  </script>
"""


# Privacy-safe usage counts through the existing Cloudflare Web Analytics beacon, which has no custom events
# but counts SPA route changes as page views (history.pushState / popstate). Each event becomes one aggregate
# page view of a virtual path: /e/out/<deal-id>/, /e/search/, /e/calculator/, /e/compare/. No cookies,
# storage, identifiers or query values are sent; search terms are never recorded. Emitted only with the beacon.
TRACK_JS = r"""  <script>
(()=>{
  const seen=new Set();
  // push a virtual route (counted once), then step back so history and the address bar are unchanged
  function lwTrack(name, then){
    if(seen.has(name)){ if(then) then(); return; } seen.add(name);
    let done=false; const fin=()=>{ if(done) return; done=true; removeEventListener("popstate",fin); if(then) then(); };
    try{ history.pushState(history.state,"","/e/"+name+"/"); addEventListener("popstate",fin); history.back(); setTimeout(fin,400); }
    catch(e){ fin(); }
  }
  window.lwTrack=lwTrack;
  let bypass=false;
  document.addEventListener("click",ev=>{
    const a=ev.target.closest&&ev.target.closest("a[data-deal]"); if(!a||bypass) return;
    const id="out/"+a.dataset.deal.replace(/[^a-z0-9-]/gi,"");
    const sameTab=ev.button===0&&!ev.metaKey&&!ev.ctrlKey&&!ev.shiftKey&&!ev.altKey&&a.target!=="_blank";
    if(!sameTab){ lwTrack(id); return; }
    ev.preventDefault();
    lwTrack(id,()=>{ bypass=true; a.click(); bypass=false; });  // native navigation keeps rel/referrer behaviour
  },true);
  document.addEventListener("lw:search",ev=>{ if(ev.detail&&ev.detail.active) lwTrack("search"); });
  document.addEventListener("lw:event",ev=>lwTrack(String(ev.detail).replace(/[^a-z0-9-]/gi,"")));
})();
  </script>
"""
