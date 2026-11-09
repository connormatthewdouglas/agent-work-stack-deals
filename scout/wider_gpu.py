"""Lantern Scout wider-GPU price batch, rev 4 (STAGED, schema stays 3.2). Additive rows file: out/wider_gpu_prices_latest.json,
registered in out/latest_manifest.json (scout_io.register_optional). Not called by the hourly refresh; run_cycle.sh calls it after enrich.
One read-only pass per source: RunPod gpuTypes, Vast bundles (one query), Clore marketplace, Oblivus availability page, Verda
/instance-types (authenticated GET), Lambda /instance-types (authenticated GET; all mapped Lambda rows are live-feed duplicates and
are dropped by DROP_LIVE_DUPES, so the Lambda read is skipped unless that setting is off).
Rules: unknown stays null; in_stock null on every row; source_url = public pricing page, API/query detail in source_detail;
verified_at UTC; Vast groups with < MIN_MARKET_OFFERS distinct machine_id are held and their price is blanked."""
import json, os, sys, time, statistics, urllib.request, urllib.parse, base64
from collections import defaultdict
from datetime import datetime, timezone
import collect_v2 as c

# ---- Mart's decisions (rev 4) as single switches ----
VRAM_MODE = "official"     # "official": vram_gb = official spec, vendor figure in vram_note | "vendor": vram_gb = vendor's figure
NAME_MODE = "bare"         # "bare": gpu_model has no VRAM (live-feed convention, e.g. "B200", "H100 SXM") | "with_vram": "<MODEL> [<FORM>] <VRAM>GB"
DROP_LIVE_DUPES = True     # drop rows the live feed already publishes (vendor, gpu, vram_gb, tier) -> LIVE_DUPES
LIVE_DUPES = {("Lambda", "GH200", 96, "On-demand instance (1x GPU)"), ("Lambda", "A10", 24, "On-demand instance (1x GPU)"),
              ("Lambda", "Quadro RTX 6000", 24, "On-demand instance (1x GPU)"), ("Lambda", "V100", 16, "On-demand instance (8x GPU)"),
              ("Lambda", "B200", 192, "On-demand instance (1x GPU)"), ("Lambda", "B200", 192, "On-demand instance (8x GPU)"),
              ("Lambda", "B200", 180, "On-demand instance (1x GPU)"), ("Lambda", "B200", 180, "On-demand instance (8x GPU)")}
OFFICIAL_VRAM = {"B200": 180,  # Mart option A (rev 5): B200 = 180GB as vendors expose it, the ONE exception to the official-spec rule; set 192 to revert
                 "B300": 288, "A40": 48, "L4": 24, "RTX A4000": 16, "RTX PRO 6000": 96, "T4": 16, "GB300": 288, "RTX PRO 5000": 48, "RTX PRO 4500": 32, "RTX PRO 4000": 24, "RTX 5090": 32}
PAGES = {"RunPod": "https://www.runpod.io/pricing", "Vast.ai": "https://vast.ai/pricing", "Clore.ai": "https://clore.ai/marketplace",
         "Oblivus": "https://oblivus.com/availability/", "Verda": "https://verda.com/pricing", "Lambda": "https://lambda.ai/pricing"}
FAMILY_SCOPE = ("B200", "B300", "GH200", "MI300X", "A40", "L4", "T4", "V100", "A10", "RTX 6000 Ada", "RTX PRO 6000", "RTX A4000", "GB300", "Quadro RTX 6000", "RTX PRO 5000", "RTX PRO 4500", "RTX PRO 4000", "RTX 5090", "H100")

VRAM_EXCEPTIONS = {"B200": "B200 is the one exception to the official-spec rule: 180GB (as vendors expose it) is used, not NVIDIA's 192GB"} if OFFICIAL_VRAM["B200"] == 180 else {}
def spec_label(family): return "listed as" if family in VRAM_EXCEPTIONS else "official spec"
_SEQ = [0]
def stamp():
    """unique set-aside suffix: UTC time + PID + per-process counter"""
    _SEQ[0] += 1; return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}-{_SEQ[0]}"

def canon(family, form, vendor_vram):
    """-> (gpu_model, vram_gb, vram_note). family keys OFFICIAL_VRAM; form e.g. 'Server' or None."""
    off = OFFICIAL_VRAM.get(family)
    vram = vendor_vram if (VRAM_MODE == "vendor" or off is None) else off
    if vram is None: vram = off
    note = None if vendor_vram == vram or vendor_vram is None else f"vendor reports {vendor_vram}GB; {spec_label(family)} {vram}GB"
    if family in VRAM_EXCEPTIONS and VRAM_MODE == "official": note = "; ".join(x for x in (note, VRAM_EXCEPTIONS[family]) if x)
    name = family + (f" {form}" if form else "")
    if NAME_MODE == "with_vram" and vram: name += f" {vram}GB"
    return name, vram, note

def row(vendor, fam, form, vendor_vram, tier, price, basis, detail, ts, src="public no-auth API", note=None, **kw):
    model, vram, vn = canon(fam, form, vendor_vram)
    if "vram_note" in kw: vn = "; ".join(x for x in (vn, kw.pop("vram_note")) if x)
    r = dict(vendor=vendor, gpu_model=model, vram_gb=vram, tier=tier, region="all", in_stock=None, offer_count=None, unrented_servers=None,
             stock_level=None, price_usd_hr=None if price is None else round(float(price), 4), price_basis=basis if price is not None else None,
             source_url=PAGES[vendor], source_detail=detail, collected_at=ts, verified_at=ts, checked_at=ts, price_refresh="daily", availability_refresh=None,
             vram_note=vn, availability_note=note or "in_stock not asserted: no two-read region confirmation in this batch",
             source=src, observation=None, feed_status=None, batch="wider-gpu")
    r.update(kw); return r

# ---- RunPod ----
RP_NEW = {"AMD Instinct MI300X OAM": ("MI300X", None, 192), "NVIDIA B200": ("B200", None, 180), "NVIDIA B300 SXM6 AC": ("B300", None, 288),
          "NVIDIA A40": ("A40", None, 48), "NVIDIA L4": ("L4", None, 24), "NVIDIA RTX 6000 Ada Generation": ("RTX 6000 Ada", None, 48),
          "NVIDIA RTX A4000": ("RTX A4000", None, 16), "NVIDIA RTX PRO 6000 Blackwell Server Edition": ("RTX PRO 6000", "Server", 96),
          "NVIDIA RTX PRO 6000 Blackwell Workstation Edition": ("RTX PRO 6000", "Workstation", 96),
          "NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition": ("RTX PRO 6000", "Max-Q", 96),
          "NVIDIA RTX PRO 5000 Blackwell": ("RTX PRO 5000", None, 48), "NVIDIA RTX PRO 4000 Blackwell": ("RTX PRO 4000", None, 24),  # T69
          "NVIDIA RTX PRO 4500 Blackwell": ("RTX PRO 4500", None, 32), "NVIDIA RTX PRO 4500 Blackwell Server Edition": ("RTX PRO 4500", "Server", 32),  # T69
          "Tesla V100-SXM2-16GB": ("V100", "SXM2", 16), "Tesla V100-PCIE-16GB": ("V100", "PCIe", 16)}
def runpod():
    q = "{ gpuTypes { id memoryInGb secureCloud communityCloud securePrice communityPrice } }"
    d = c.get(c.RPURL, json.dumps({"query": q}).encode())["data"]["gpuTypes"]; ts = c.NOW(); rows = []
    for g in d:
        if g["id"] not in RP_NEW: continue
        fam, form, expect = RP_NEW[g["id"]]
        if g.get("memoryInGb") != expect: continue  # vendor VRAM changed from what the alias asserts: skip, never coerce
        for cloud, flag, pk in (("Secure", "secureCloud", "securePrice"), ("Community", "communityCloud", "communityPrice")):
            p = g.get(pk)
            if not g.get(flag) or not p: continue
            rows.append(row("RunPod", fam, form, g["memoryInGb"], f"On-demand ({cloud} Cloud)", p, f"gpuTypes.{pk} (list price, 1 GPU)",
                            f"{c.RPURL} gpuTypes.{pk} id={g['id']}", ts))
    return rows

# ---- Vast: one query; hold = distinct machine_id < MIN_MARKET_OFFERS; held rows carry no price ----
VAST_NEW = {"B200": ("B200", None), "B300": ("B300", None), "RTX 6000Ada": ("RTX 6000 Ada", None), "RTX PRO 6000 S": ("RTX PRO 6000", "Server"),
            "RTX PRO 6000 WS": ("RTX PRO 6000", "Workstation"), "RTX PRO 6000 Max-Q": ("RTX PRO 6000", "Max-Q"), "A40": ("A40", None),
            "L4": ("L4", None), "Tesla T4": ("T4", None), "Tesla V100": ("V100", None), "A10": ("A10", None), "RTX A4000": ("RTX A4000", None),
            "GH200": ("GH200", None), "MI300X": ("MI300X", None), "Q RTX 6000": ("Quadro RTX 6000", None),
            "RTX 5090": ("RTX 5090", None), "H100 SXM": ("H100", "SXM"), "H100 PCIE": ("H100", "PCIe")}  # T65: focus cells never queried (same min-machines hold applies)
def vast(min_machines=None):
    q = {"gpu_name": {"in": sorted(VAST_NEW)}, "rentable": {"eq": True}, "rented": {"eq": False}, "verified": {"eq": True}, "type": "on-demand", "limit": 1000}
    url = "https://console.vast.ai/api/v0/bundles/?q=" + urllib.parse.quote(json.dumps(q, separators=(",", ":")))
    offers = c.get(url).get("offers", []); ts = c.NOW()
    grp = defaultdict(lambda: {"p": [], "m": set(), "raw": defaultdict(int), "nomid": 0})
    for o in offers:
        if o.get("gpu_name") not in VAST_NEW or not o.get("num_gpus") or not o.get("gpu_ram"): continue
        fam, form = VAST_NEW[o["gpu_name"]]; vr = round(o["gpu_ram"] / 1024)
        model, vram, _ = canon(fam, form, vr)
        g = grp[(fam, form, vram)]; g["p"].append(o["dph_total"] / o["num_gpus"]); g["raw"][vr] += 1
        if o.get("machine_id") is not None: g["m"].add(o["machine_id"])
        else: g["nomid"] += 1
    rows = []
    for (fam, form, vram), g in sorted(grp.items(), key=lambda kv: str(kv[0])):
        n, m = len(g["p"]), len(g["m"])
        held = bool(min_machines) and m < min_machines
        figs = dict(g["raw"]); off = vram
        vn = None if set(figs) == {off} else "vendor reports " + ", ".join(f"{k}GB ({v} offers)" for k, v in sorted(figs.items())) + f"; {spec_label(fam)} {off}GB"
        cnt = f"{n} offers on {m} distinct machine_id" + (f" ({g['nomid']} offers without machine_id, not counted)" if g["nomid"] else "")
        med = statistics.median(g["p"])
        r = row("Vast.ai", fam, form, vram, "Marketplace on-demand (verified)", None if held else med,
                "median per-GPU dph_total, same snapshot as offer_count", url, ts, offer_count=n, distinct_machines=m, price_refresh="4h",
                feed_status="held_below_min_offers" if held else None,
                availability_note=f"{cnt}; " + (f"held: fewer than {min_machines} distinct machines, price withheld" if held else "in_stock not asserted (single read)"))
        r["vram_note"] = "; ".join(x for x in (vn, VRAM_EXCEPTIONS.get(fam) if VRAM_MODE == "official" else None) if x) or None
        if held: r["feed_min_offers"] = min_machines
        rows.append(r)
    return rows

# ---- Vast per-allocation rows (Bjorn 1108; collect() uses this instead of the pooled vast()) ----
# One row per (GPU, num_gpus): gpu_count = min_gpus = the offers' own num_gpus, price = median dph_total of those offers / num_gpus.
# Publishes only when BOTH reads (>= VAST_READ_GAP_S apart) have >= max(VAST_ALLOC_MIN_MACHINES = 7, feed floor) distinct machine_id at that size and the two
# per-GPU medians are within VAST_STABLE_PCT. Anything else emits no row; the reason goes to meta (never to a published row).
# Pooled mixed-allocation rows are not emitted (no verifiable allocation). Offers with a missing/non-integer num_gpus never count.
VAST_ALLOC_MIN_MACHINES = 7  # Bjorn 1108: raised from 5; required in BOTH reads
VAST_READ_GAP_S = 180  # Bjorn 1108: widened from 60 s; run_cycle.sh.vastalloc_staged raises the wider-step timeout to 300 s
VAST_STABLE_PCT = 0.05
VAST_ALLOC_META = {}  # last vast_alloc() run: read times, per-size counts/medians and hold reasons (copied into doc["meta"])
_sleep, _mono = time.sleep, time.monotonic

def _vast_alloc_groups(offers):
    """{(fam, form, vram, num_gpus): {"t": [dph_total...], "m": {machine_id}, "raw": {vendor GB: offers}, "nomid": n}}"""
    agrp = defaultdict(lambda: {"t": [], "m": set(), "raw": defaultdict(int), "nomid": 0})
    for o in offers:
        ng, tot = o.get("num_gpus"), o.get("dph_total")
        if o.get("gpu_name") not in VAST_NEW or not o.get("gpu_ram"): continue
        if not (isinstance(ng, int) and not isinstance(ng, bool) and ng >= 1): continue  # never infer an allocation
        if not (isinstance(tot, (int, float)) and not isinstance(tot, bool) and tot > 0): continue
        fam, form = VAST_NEW[o["gpu_name"]]; vr = round(o["gpu_ram"] / 1024)
        _, vram, _ = canon(fam, form, vr)
        a = agrp[(fam, form, vram, ng)]; a["t"].append(tot); a["raw"][vr] += 1
        if o.get("machine_id") is not None: a["m"].add(o["machine_id"])
        else: a["nomid"] += 1
    return agrp

def vast_alloc(min_machines=None):
    q = {"gpu_name": {"in": sorted(VAST_NEW)}, "rentable": {"eq": True}, "rented": {"eq": False}, "verified": {"eq": True}, "type": "on-demand", "limit": 1000}
    url = "https://console.vast.ai/api/v0/bundles/?q=" + urllib.parse.quote(json.dumps(q, separators=(",", ":")))  # same query as vast()
    th = max(VAST_ALLOC_MIN_MACHINES, min_machines or 0)
    VAST_ALLOC_META.clear(); VAST_ALLOC_META.update(min_machines=th, read_gap_s=VAST_READ_GAP_S, stable_pct=VAST_STABLE_PCT)
    g1 = _vast_alloc_groups(c.get(url).get("offers", [])); ts1 = c.NOW(); t1 = _mono()  # read 1 failure raises -> Vast source error (as today)
    VAST_ALLOC_META["read1_at"] = ts1
    wait = VAST_READ_GAP_S - (_mono() - t1)
    if wait > 0: _sleep(wait)
    try:
        if _mono() - t1 < VAST_READ_GAP_S: raise RuntimeError("second read earlier than the minimum gap")
        g2 = _vast_alloc_groups(c.get(url).get("offers", [])); ts2 = c.NOW()
    except Exception as ex:  # read 2 failed: every size holds, no row and no fresh timestamp
        VAST_ALLOC_META.update(read2_at=None, read2_error=type(ex).__name__ + ": " + str(ex)[:120], sizes=[
            dict(gpu=canon(k[0], k[1], k[2])[0], vram_gb=k[2], gpu_count=k[3], offers1=len(a["t"]), machines1=len(a["m"]), status="held: second read failed")
            for k, a in sorted(g1.items(), key=lambda kv: (str(kv[0][:3]), kv[0][3]))])
        return []
    VAST_ALLOC_META["read2_at"] = ts2
    rows, sizes = [], []
    for k in sorted(set(g1) | set(g2), key=lambda k: (str(k[:3]), k[3])):
        fam, form, vram, ng = k; a1, a2 = g1.get(k), g2.get(k)
        m1, m2 = (len(a1["m"]) if a1 else 0), (len(a2["m"]) if a2 else 0)
        p1 = round(round(statistics.median(a1["t"]), 4) / ng, 4) if a1 else None
        p2 = round(round(statistics.median(a2["t"]), 4) / ng, 4) if a2 else None
        info = dict(gpu=canon(fam, form, vram)[0], vram_gb=vram, gpu_count=ng, offers1=len(a1["t"]) if a1 else 0, machines1=m1, median1=p1,
                    offers2=len(a2["t"]) if a2 else 0, machines2=m2, median2=p2)
        if m1 < th or m2 < th:
            info["status"] = f"held: fewer than {th} distinct machines in {'both reads' if m1 < th and m2 < th else 'read 1' if m1 < th else 'read 2'}"
        elif abs(p2 - p1) > VAST_STABLE_PCT * p1:
            info["status"] = f"held: medians differ by {abs(p2 - p1) / p1:.1%} (> {VAST_STABLE_PCT:.0%})"
        else:
            info["status"] = "published (read 2)"
            tot = round(statistics.median(a2["t"]), 4); n = len(a2["t"])
            figs = dict(a2["raw"])
            vn = None if set(figs) == {vram} else "vendor reports " + ", ".join(f"{x}GB ({v} offers)" for x, v in sorted(figs.items())) + f"; {spec_label(fam)} {vram}GB"
            cnt = f"{n} offers on {m2} distinct machine_id" + (f" ({a2['nomid']} offers without machine_id, not counted)" if a2["nomid"] else "")
            r = row("Vast.ai", fam, form, vram, f"Marketplace on-demand (verified, {ng}x GPU)", p2,
                    f"median per-GPU dph_total of num_gpus={ng} offers only, same snapshot as offer_count", url, ts2, offer_count=n, distinct_machines=m2,
                    price_refresh="4h", gpu_count=ng, min_gpus=ng, server_price_usd_hr=tot, allocation_source=f"offers[].num_gpus == {ng}",
                    stability_check=f"read 1 {ts1}: {p1} on {m1} machines; read 2 {ts2}: {p2} on {m2} machines (<= {VAST_STABLE_PCT:.0%} apart)",
                    availability_note=f"{cnt} at num_gpus={ng} (read 2); in_stock not asserted")
            r["vram_note"] = "; ".join(x for x in (vn, VRAM_EXCEPTIONS.get(fam) if VRAM_MODE == "official" else None) if x) or None
            rows.append(r)
        sizes.append(info)
    VAST_ALLOC_META["sizes"] = sizes
    return rows

# ---- Clore: stock count only ----
CLORE_NEW = {"NVIDIA L4": ("L4", None, 23), "Tesla T4": ("T4", None, 15), "NVIDIA RTX A4000": ("RTX A4000", None, 16),
             "Tesla V100SXM216GB": ("V100", "SXM2", 16), "Tesla V100SXM232GB": ("V100", "SXM2", 32),
             "NVIDIA RTX PRO 6000 Blackwell Workstation": ("RTX PRO 6000", "Workstation", 96), "Quadro RTX 6000": ("Quadro RTX 6000", None, 24)}
def clore():
    servers = c.get(c.CLORE)["servers"]; ts = c.NOW(); n = defaultdict(int); seen = set()
    for s in servers:
        sp = s.get("specs") or {}; g = sp.get("gpu") or ""
        if "x " not in g: continue
        name = g.split("x ", 1)[1].strip()
        if name not in CLORE_NEW or sp.get("gpuram") != CLORE_NEW[name][2]: continue
        seen.add(name)
        if s.get("rented") is False: n[name] += 1
    rows = []
    for name in sorted(seen):
        fam, form, vend = CLORE_NEW[name]
        rows.append(row("Clore.ai", fam, form, vend, "Marketplace on-demand", None, None, c.CLORE + " (servers[].rented == false)", ts,
                        unrented_servers=n[name], availability_note=c.CLORE_NOTE + "; in_stock not asserted (single read)", price_refresh="4h",
                        observation="stock-only: Clore price.on_demand is documented per-day per server; unit of price.usd not confirmed"))
    return rows

# ---- Oblivus: stock only ----
OBL_NEW = {"B200 SXM": ("B200", None, "vendor page lists no VRAM"),
           "RTX PRO6000 SE": ("RTX PRO 6000", "Server", "vendor page lists no VRAM; 96GB is the official spec")}
def oblivus():
    import re, html as H
    page = c._get_text(c.OBL_URL); ts = c.NOW()
    seg = page[page.find("GPU Availability"):]; tbl = seg[seg.find("<table"):seg.find("</table>")]
    cells = [[H.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)] for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S)]
    if not cells or cells[0][0].upper() != "GPU": raise ValueError("Oblivus availability table not found")
    rows = []
    for r in cells[1:]:
        if r and r[0] in OBL_NEW:
            fam, form, vn = OBL_NEW[r[0]]; nums = [int(v) for v in r[1:] if v.isdigit()]
            rows.append(row("Oblivus", fam, form, None, "On-demand", None, None, c.OBL_URL + " (GPU Availability table)", ts, src="public vendor web page",
                            vram_note=vn, available_gpus=sum(nums) if nums else None, observation="stock-only row (Mart): no price"))
    return rows

OBL_PRICING_URL = "https://oblivus.com/pricing/"
OBL_PRICED = {"RTX 4090": ("RTX 4090", None, 24), "H200 141GB SXM5": ("H200", "SXM", 141)}
def parse_obl_pricing(page):
    import re, html as H
    L = [x.strip() for x in H.unescape(re.sub(r"<[^>]+>", "\n", page)).split("\n") if x.strip()]
    out = {}
    for i, x in enumerate(L[:-2]):
        if x in OBL_PRICED and x not in out:
            m = re.fullmatch(r"On-Demand: \$(\d+(?:\.\d+)?)/hr", L[i + 2])
            if m: out[x] = (float(m.group(1)), L[i + 2])
    return out
def parse_obl_configs(page):
    """{card name: [(config code, 'Nx GPU - ...' line, N), ...]} from the pricing page's Configurations lists; only the vendor's own text."""
    import re, html as H
    L = [x.strip() for x in H.unescape(re.sub(r"<[^>]+>", "\n", page)).split("\n") if x.strip()]
    out = {}
    for i, x in enumerate(L[:-1]):
        for name in OBL_PRICED:
            m = re.fullmatch(re.escape(name.replace(" ", "_")) + r"_x(\d+)", x)
            g = m and re.fullmatch(r"(\d+)x GPU - .+", L[i + 1])
            if g and g.group(1) == m.group(1): out.setdefault(name, []).append((x, L[i + 1], int(g.group(1))))
    return out
def obl_availability():
    """{gpu name: [(location, count), ...]} from the availability table; raises if unreadable."""
    import re, html as H
    page = c._get_text(c.OBL_URL); seg = page[page.find("GPU Availability"):]; tbl = seg[seg.find("<table"):seg.find("</table>")]
    cells = [[H.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)] for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S)]
    if not cells or cells[0][0].upper() != "GPU": raise ValueError("Oblivus availability table not found")
    locs = cells[0][1:]
    return {r[0]: [(l, int(v)) for l, v in zip(locs, r[1:]) if v.isdigit()] for r in cells[1:] if r}
def obl_status(counts):
    if not counts: return "unknown", "unknown", "availability page could not be read (or GPU row/counts missing)"
    per = ", ".join(f"{l}: {n}" for l, n in counts)
    if any(n > 0 for _, n in counts): return "in_stock", "in_stock", f"{sum(n for _, n in counts)} GPUs available on availability page ({per})"
    return "out_of_stock", "out_of_stock", f"0 GPUs available on availability page ({per})"
def oblivus_listed(avail=None, ts=None):
    """T65 (Mart GO): listed on-demand price rows; written whenever the price text is on the pricing page. Stock comes from the
    availability page and never gates the row."""
    ts = ts or c.NOW()
    page = c._get_text(OBL_PRICING_URL); prices = parse_obl_pricing(page); configs = parse_obl_configs(page)
    if avail is None:
        try: avail = obl_availability()
        except Exception: avail = {}
    rows = []
    for name, (fam, form, vv) in OBL_PRICED.items():
        if name not in prices: continue  # price gone -> skip row
        p, quote = prices[name]; counts = avail.get(name)
        st, rs, det = obl_status(counts)
        r = row("Oblivus", fam, form, vv, "On-demand", p, "per GPU-hour (listed on-demand)", OBL_PRICING_URL, ts, src="public vendor web page",
                observation="listed price, not a stock claim (Mart GO T65)")
        r.update(source_url=OBL_PRICING_URL, price_quote=f"{name} ... {quote}", in_stock={"in_stock": True, "out_of_stock": False}.get(st),
                 available_gpus=sum(n for _, n in counts) if counts else None, availability_status=st, availability_reason=rs,
                 availability_reason_detail=det + f" [{c.OBL_URL}]")
        one = [cf for cf in configs.get(name, []) if cf[2] == 1]
        if one:  # allocation only when the vendor lists a 1x GPU configuration for this card; otherwise left unset (unknown)
            r.update(gpu_count=1, min_gpus=1, allocation_quote=f"{one[0][0]}: {one[0][1]}")
        rows.append(r)
    return rows

# ---- Verda: 1x types, on-demand + spot; CC excluded ----
VERDA_NEW = (("GB300", "GB300", None), ("B300", "B300", None), ("B200", "B200", None), ("RTX PRO 6000", "RTX PRO 6000", None),
             ("RTX 6000 Ada", "RTX 6000 Ada", None), ("V100", "V100", None))
def verda(secrets="secrets/verda.env"):
    e = c._verda_env(secrets)
    tok = c.get(c.VBASE + "/oauth2/token", json.dumps({"grant_type": "client_credentials", "client_id": e["VERDA_CLIENT_ID"], "client_secret": e["VERDA_CLIENT_SECRET"]}).encode())["access_token"]
    req = urllib.request.Request(c.VBASE + "/instance-types", headers={"User-Agent": c.UA, "Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=40) as r: types = json.load(r)
    ts = c.NOW(); rows = []
    for t in types:
        g = t.get("gpu") or {}; n = g.get("number_of_gpus") or 0; desc = g.get("description") or ""; it = t.get("instance_type") or ""
        if n != 1 or "CC" in it.upper() or "confidential" in desc.lower(): continue
        hit = next((fam for key, fam, _ in VERDA_NEW if key in desc and not (key == "B300" and "GB300" in desc)), None)
        if not hit: continue
        vram = round(t["gpu_memory"]["size_in_gigabytes"] / n)
        if f"{vram}GB" not in desc.replace(" GB", "GB"): continue
        extra = ("form factor not stated by Verda" if hit == "V100" else
                 "Verda does not state the edition (Server / Workstation / Max-Q)" if hit == "RTX PRO 6000" else None)
        for tier, k, b in (("On-demand instance (1x GPU)", "price_per_hour", "instance-types price_per_hour (1 GPU)"), ("Spot instance (1x GPU)", "spot_price", "instance-types spot_price (1 GPU)")):
            p = t.get(k)
            if p in (None, "", 0): continue
            rows.append(row("Verda", hit, None, vram, tier, p, b, f"{c.VBASE}/instance-types ({it})", ts, src="authenticated vendor API (not publicly reproducible)",
                            price_refresh="4h" if "Spot" in tier else "daily", **({"vram_note": extra} if extra else {})))
    return rows

# ---- Lambda (every mapped row is a live-feed duplicate today; kept behind DROP_LIVE_DUPES) ----
LAMBDA_NEW = {"gpu_1x_gh200": ("GH200", None, 96, 1, "96 GB"), "gpu_1x_a10": ("A10", None, 24, 1, "24 GB PCIe"),
              "gpu_1x_b200_sxm6": ("B200", None, 180, 1, "180 GB SXM6"), "gpu_8x_b200_sxm6": ("B200", None, 180, 8, "180 GB SXM6"),
              "gpu_1x_rtx6000": ("Quadro RTX 6000", None, 24, 1, "RTX 6000 (24 GB)"), "gpu_8x_v100": ("V100", None, 16, 8, "16 GB")}
def lambda_(secrets="secrets/lambda.env"):
    key = c._verda_env(secrets)["LAMBDA_API_KEY"]
    req = urllib.request.Request(c.LBASE, headers={"User-Agent": c.UA, "Authorization": "Basic " + base64.b64encode((key + ":").encode()).decode()})
    with urllib.request.urlopen(req, timeout=40) as r: data = json.load(r)["data"]
    ts = c.NOW(); rows = []
    for it, (fam, form, vend, n, must) in LAMBDA_NEW.items():
        v = data.get(it)
        if not v or must not in (v["instance_type"].get("gpu_description") or ""): continue
        t = v["instance_type"]
        rows.append(row("Lambda", fam, form, vend, f"On-demand instance ({n}x GPU)", t["price_cents_per_hour"] / 100 / n, "price_cents_per_hour / GPUs",
                        c.LBASE + f" ({it})", ts, src="authenticated vendor API (not publicly reproducible)"))
    return rows

def is_live_dupe(r): return (r["vendor"], r["gpu_model"], r["vram_gb"], r["tier"]) in LIVE_DUPES
def counts(rows):
    pub = [r for r in rows if r["price_usd_hr"] is not None and not r.get("feed_status")]
    return {"total_rows": len(rows), "publishable_rows": len(pub), "stock_only_rows": sum(1 for r in rows if r["price_usd_hr"] is None and not r.get("feed_status")),
            "held_rows": sum(1 for r in rows if r.get("feed_status"))}

def collect(secrets_dir="secrets"):
    rows, errs, t0 = [], {}, time.time()
    mmo = c.feed_min_market_offers()
    srcs = [("RunPod", runpod), ("Vast.ai", lambda: vast_alloc(mmo)), ("Clore.ai", clore), ("Oblivus", oblivus), ("Oblivus listed", oblivus_listed),
            ("Verda", lambda: verda(os.path.join(secrets_dir, "verda.env")))]
    if not DROP_LIVE_DUPES: srcs.append(("Lambda", lambda: lambda_(os.path.join(secrets_dir, "lambda.env"))))
    for name, fn in srcs:
        try: rows += fn()
        except Exception as ex: errs[name] = type(ex).__name__ + ": " + str(ex)[:160]
    dropped = [r for r in rows if DROP_LIVE_DUPES and is_live_dupe(r)]
    rows = [r for r in rows if r not in dropped]
    for r in rows:
        if not r.get("source_url", "").startswith("https://") or "?" in r["source_url"] or not r.get("verified_at"): raise AssertionError(r)
    return {"version": "3.2", "batch": "wider-gpu", "collected_at": c.NOW(), "errors": errs, "family_scope": list(FAMILY_SCOPE),
            "settings": {"VRAM_MODE": VRAM_MODE, "NAME_MODE": NAME_MODE, "DROP_LIVE_DUPES": DROP_LIVE_DUPES},
            "meta": {"feed_min_market_offers": mmo, "vast_hold_counts": "distinct machine_id", "run_seconds": round(time.time() - t0, 1),
                     "dropped_live_dupes": len(dropped), "counts": counts(rows),
                     "vast_allocation": json.loads(json.dumps(VAST_ALLOC_META))}, "rows": rows}

LATEST = "wider_gpu_prices_latest.json"
def move_aside(out, why):
    """Failed run or failed register: the latest file must not be pushed -> rename it aside (never deleted)."""
    p = os.path.join(out, LATEST)
    if os.path.exists(p):
        dst = os.path.join(out, f"wider_gpu_prices_REJECTED_{stamp()}.json")
        os.replace(p, dst); print(f"wider-gpu: {why}; moved {LATEST} aside -> {os.path.basename(dst)}", file=sys.stderr)

def keep_or_move_aside(out, why):
    """Gauge vast-alloc #4: after a failed or killed run, keep the PREVIOUS good latest file only if it is still the one registered in
    the manifest (sha256 match, same rule as scout_io._carry_optional), so it is reused with its own old timestamps and the push /
    screen_optional 6 h age limits still apply. Anything else (unregistered, changed, or a new file that was never registered) is moved
    aside as before. Never writes or re-stamps the file."""
    import scout_io
    p = os.path.join(out, LATEST)
    if not os.path.exists(p): return "absent"
    if LATEST in scout_io._carry_optional(out):
        print(f"wider-gpu: {why}; kept previous registered {LATEST} (not re-stamped)", file=sys.stderr); return "kept"
    move_aside(out, why); return "moved"

def main(out="out", secrets=None):
    try: doc = collect(secrets or os.environ.get("WGPU_SECRETS_DIR", "secrets"))
    except Exception as ex: keep_or_move_aside(out, f"run failed ({type(ex).__name__})"); return 1
    os.makedirs(out, exist_ok=True)
    stamp = doc["collected_at"].replace("-", "").replace(":", "")
    json.dump(doc, open(f"{out}/wider_gpu_prices_{stamp}{'_FAILED' if doc['errors'] else ''}.json", "w"), indent=1)
    if doc["errors"]:
        keep_or_move_aside(out, f"run failed {sorted(doc['errors'])}"); return 1
    tmp = f"{out}/.{LATEST}.tmp"; json.dump(doc, open(tmp, "w"), indent=1); os.replace(tmp, f"{out}/{LATEST}")
    try:
        import scout_io
        scout_io.register_optional(LATEST, out)
    except Exception as ex:
        move_aside(out, f"register failed ({type(ex).__name__})"); return 1
    print(len(doc["rows"]), "rows", doc["meta"]["counts"], "in", doc["meta"]["run_seconds"], "s")
    return 0

if __name__ == "__main__": sys.exit(main())
