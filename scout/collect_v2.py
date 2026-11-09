"""Lantern Scout collectors v2 (v3.0: Oblivus public availability page; Vast H100 + Oblivus two reads; v2.9: region rows expire 1h, confirmed = both reads in stock, confirmation field; v2.7: claim checked_at/source/availability_expires_at; RunPod per-DC retry+log). Public no-auth endpoints. Unknown -> null."""
import json, csv, os, sys, time, statistics, urllib.request, urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
UA = "LanternWorks-Scout/0.2 (+https://thelanternworks.com)"
def NOW(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
FIELDS = ["vendor","gpu_model","vram_gb","tier","region","in_stock","offer_count","unrented_servers","stock_level","price_usd_hr","price_basis","source_url","collected_at","price_refresh","availability_refresh","vram_note","availability_note","source","observation","checked_at","availability_expires_at","stock_level_scope","confirmation","confirmed","second_read_stock_level","second_read_at","available_gpus","second_read_offer_count","second_read_available_gpus","second_read_in_stock","second_read_gap_s","generation_id","feed_status","derived_from_regions","overall_recomputed_at"]
def get(url, data=None):  # GET unless data is given
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r: return json.load(r)

QUERIED = {}
VAST = {"H100 SXM": "H100 SXM", "H100 PCIe": "H100 PCIE", "A100 SXM": "A100 SXM4", "A100 PCIe": "A100 PCIE", "RTX 4090": "RTX 4090"}
def vast():
    rows = []
    for model, name in VAST.items():
        q = {"gpu_name": {"eq": name}, "rentable": {"eq": True}, "rented": {"eq": False}, "verified": {"eq": True}, "type": "on-demand", "limit": 1000}
        url = "https://console.vast.ai/api/v0/bundles/?q=" + urllib.parse.quote(json.dumps(q, separators=(",", ":")))
        offers = get(url).get("offers", []); FIRST_READ["Vast.ai|" + model] = time.time(); ts = NOW()
        by = defaultdict(list)
        for o in offers:
            if not o.get("num_gpus") or not o.get("gpu_ram"): continue
            vram = round(o["gpu_ram"] / 1024)  # MB -> GB
            reg = (o.get("geolocation") or "").split(",")[-1].strip() or None
            p = o["dph_total"] / o["num_gpus"]
            by[(vram, "all")].append(p)  # country-less offers still count here
            if reg is not None: by[(vram, reg)].append(p)  # no per-region row for null region
        for (vram, reg), ps in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1] != "all", str(kv[0][1]))):
            rows.append(dict(vendor="Vast.ai", gpu_model=model, vram_gb=vram, tier="Marketplace on-demand (verified)", region=reg,
                in_stock=True, offer_count=len(ps), stock_level=None, price_usd_hr=round(statistics.median(ps), 4),
                price_basis="median per-GPU dph_total, same snapshot as offer_count", source_url=url, collected_at=ts, price_refresh="4h", availability_refresh="4h", vram_note=None, availability_note=None))
        QUERIED["Vast.ai|" + model] = {"source_url": url, "queried_at": ts}
        if not offers:  # model queried, zero rentable offers -> real 0, region all
            rows.append(dict(vendor="Vast.ai", gpu_model=model, vram_gb=None, tier="Marketplace on-demand (verified)", region="all", in_stock=False,
                offer_count=0, stock_level=None, price_usd_hr=None, price_basis=None, source_url=url, collected_at=ts, price_refresh="4h", availability_refresh="4h", vram_note="0 verified rentable offers in this snapshot; VRAM not readable from API and no feed row to verify it, so left null", availability_note=None))
        time.sleep(2)
    return rows

RP = {"NVIDIA H100 80GB HBM3": ("H100 SXM", 80), "NVIDIA H100 PCIe": ("H100 PCIe", 80), "NVIDIA A100-SXM4-80GB": ("A100 SXM", 80),
      "NVIDIA A100 80GB PCIe": ("A100 PCIe", 80), "NVIDIA GeForce RTX 4090": ("RTX 4090", 24),
      "NVIDIA H100 NVL": ("H100 NVL", 94)}  # T73: feed has RunPod H100 NVL Secure+Community rows; same per-DC two-read rules
IN = {"High": True, "Medium": True, "Low": True}  # null/absent -> None (unknown)
# v3.5 (Gauge 5): RunPod stockStatus values that mean "out of stock". RunPod's public API (introspection disabled) has only ever
# returned High/Medium/Low or null: 4857 null vs High 9/Medium 9/Low 725 in out/, and a live dataCenters read 17:5x ET returned
# null with available=false for every unavailable GPU. No named out-of-stock level exists, so this set is empty and no RunPod
# region is confirmed out from a level (unknown instead). Add a value here only once the API is seen returning it.
RUNPOD_OUT_LEVELS = frozenset()
RPURL = "https://api.runpod.io/graphql"
RP_TRIES, RP_BACKOFF, RP_LOG = 3, 2.0, []
def RP_SLEEP(sec): time.sleep(sec)
def runpod():
    rows, observed = [], set()
    for cloud, secure in (("Secure", "true"), ("Community", "false")):  # separate query per cloud type
        q = "{ gpuTypes { id lowestPrice(input:{gpuCount:1, secureCloud:%s}){ stockStatus uninterruptablePrice } } }" % secure
        d = get(RPURL, json.dumps({"query": q}).encode())["data"]; ts = NOW()
        for g in d["gpuTypes"]:
            if g["id"] not in RP: continue
            lp = g["lowestPrice"] or {}; s = lp.get("stockStatus"); observed.add(s)
            price = lp.get("uninterruptablePrice")
            rows.append(dict(vendor="RunPod", gpu_model=RP[g["id"]][0], vram_gb=RP[g["id"]][1], tier=f"On-demand ({cloud} Cloud)", region="all",
                in_stock=IN.get(s), offer_count=None, stock_level=s, price_usd_hr=price,
                price_basis="lowestPrice.uninterruptablePrice, 1 GPU" if price is not None else None,
                source_url=f"{RPURL} gpuTypes.lowestPrice(secureCloud:{secure})", collected_at=ts, price_refresh="4h", availability_refresh="4h", vram_note=None,
                availability_note=("unknown: RunPod's public API returned no stock status or price for this cloud type at check time" if s is None else None)))
        time.sleep(2)
    # v2.6: per data center AND cloud type. lowestPrice(input:{dataCenterId, secureCloud}) returns stock for that DC+cloud, so
    # region rows carry a real cloud tier and join to the matching Secure/Community feed row via available_regions.
    d = get(RPURL, json.dumps({"query": "{ dataCenters { id location gpuAvailability { gpuTypeId stockStatus } } }"}).encode())["data"]; ts = NOW()
    dcs = [dc for dc in d["dataCenters"] if dc.get("id")]
    typed = set(); pending = []; RP_GAPS.clear()
    def emit(dc, cloud, secure, gl, ts2, second, second_at, gap):
        for g in gl:
            if g["id"] not in RP: continue
            lp = g.get("lowestPrice") or {}; s = lp.get("stockStatus")
            if s is None: continue  # no signal for this GPU in this DC+cloud: emit nothing (never invent)
            observed.add(s); typed.add((dc["id"], g["id"])); price = lp.get("uninterruptablePrice")
            rows.append(dict(vendor="RunPod", gpu_model=RP[g["id"]][0], vram_gb=RP[g["id"]][1], tier=f"On-demand ({cloud} Cloud)",
                region=f'{dc["id"]} ({dc.get("location")})', in_stock=IN.get(s), offer_count=None, stock_level=s, price_usd_hr=price,
                price_basis="lowestPrice.uninterruptablePrice, 1 GPU, this data center" if price is not None else None,
                source_url=f"{RPURL} gpuTypes.lowestPrice(secureCloud:{secure}, dataCenterId:{dc['id']})", collected_at=ts2,
                price_refresh="4h", availability_refresh="4h", vram_note=None, availability_note=None,
                second_read_stock_level=None if second is None else second.get(g["id"]), second_read_at=second_at, second_read_gap_s=gap,
                confirmation="single_read" if second is None else "two_reads",
                confirmed=None if second is None else (IN.get(s) is True and IN.get(second.get(g["id"])) is True)))  # v2.9: both reads in stock
    for cloud, secure in (("Secure", "true"), ("Community", "false")):
        for dc in dcs:  # one query per DC+cloud (a single aliased batch query returned HTTP 500)
            q = '{ gpuTypes { id lowestPrice(input:{gpuCount:1, secureCloud:%s, dataCenterId:%s}){ stockStatus uninterruptablePrice } } }' % (secure, json.dumps(dc["id"]))
            listed = {x["gpuTypeId"] for x in dc.get("gpuAvailability") or [] if x["gpuTypeId"] in RP}
            gl, attempts, errors = None, 0, []
            for attempt in range(RP_TRIES):  # v2.7: retry on HTTP/network error, or null for a GPU the DC lists (RunPod flickers)
                attempts = attempt + 1
                try:
                    gl = get(RPURL, json.dumps({"query": q}).encode())["data"]["gpuTypes"] or []
                except Exception as e:
                    errors.append(type(e).__name__ + ": " + str(e)[:120]); gl = None
                ts2 = NOW()
                null = None if gl is None else sorted(g["id"] for g in gl if g["id"] in listed and not (g.get("lowestPrice") or {}).get("stockStatus"))
                if gl is not None and not null: break
                if attempt + 1 < RP_TRIES: RP_SLEEP(RP_BACKOFF * 2 ** attempt)
            time.sleep(0.5)
            if errors or gl is None or null or not gl or attempts > 1:
                RP_LOG.append({"data_center": dc["id"], "cloud": cloud, "attempts": attempts, "errors": errors or None,
                               "result": "error" if gl is None else "empty" if not gl else "null_for_listed_gpu" if null else "recovered_after_retry",
                               "null_gpus": null, "final_at": ts2})
            if gl is None: continue
            # v3.1: second reads are deferred until all first reads are done, then each is taken >= RP_SECOND_GAP after its own first read
            if any(g["id"] in RP and (g.get("lowestPrice") or {}).get("stockStatus") for g in gl):
                pending.append(dict(dc=dc, cloud=cloud, secure=secure, q=q, gl=gl, ts2=ts2, t1=RP_CLOCK()))
            else:
                emit(dc, cloud, secure, gl, ts2, None, None, None)
        time.sleep(2)
    for p in pending:
        w = RP_SECOND_GAP - (RP_CLOCK() - p["t1"])
        if w > 0: RP_SLEEP(w)
        try:
            gl2 = get(RPURL, json.dumps({"query": p["q"]}).encode())["data"]["gpuTypes"] or []
            second = {g["id"]: (g.get("lowestPrice") or {}).get("stockStatus") for g in gl2}
        except Exception as e:
            RP_LOG.append({"data_center": p["dc"]["id"], "cloud": p["cloud"], "attempts": 1, "errors": [type(e).__name__ + ": " + str(e)[:120]],
                           "result": "second_read_error", "null_gpus": None, "final_at": NOW()}); second = None
        gap = round(RP_CLOCK() - p["t1"], 1); RP_GAPS.append(gap)
        emit(p["dc"], p["cloud"], p["secure"], p["gl"], p["ts2"], second, NOW(), gap); time.sleep(0.5)
    # Fallback: GPU listed in a DC's gpuAvailability but no cloud-typed signal -> keep untyped row (never joined to feed rows).
    for dc in dcs:
        for a in dc.get("gpuAvailability") or []:
            if a["gpuTypeId"] not in RP or (dc["id"], a["gpuTypeId"]) in typed: continue
            s = a.get("stockStatus"); observed.add(s)
            rows.append(dict(vendor="RunPod", gpu_model=RP[a["gpuTypeId"]][0], vram_gb=RP[a["gpuTypeId"]][1], tier="Data center (cloud type not stated by API)",
                region=f'{dc["id"]} ({dc.get("location")})', in_stock=IN.get(s), offer_count=None, stock_level=s, price_usd_hr=None, price_basis=None,
                source_url=f"{RPURL} dataCenters.gpuAvailability", collected_at=ts, price_refresh="4h", availability_refresh="4h", vram_note=None,
                availability_note=("unknown: RunPod's public API returned no stock status for this GPU in this data center at check time" if s is None else None)))
    return rows, sorted(observed, key=str)

VBASE = "https://api.datacrunch.io/v1"
def _verda_env(path="secrets/verda.env"):
    env = {}
    for line in open(path):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.strip().split("=", 1); env[k] = v.strip().strip('"').strip("'")
    return env
_VERDA = {}
def verda():
    e = _verda_env()
    tok = get(VBASE + "/oauth2/token", json.dumps({"grant_type": "client_credentials", "client_id": e["VERDA_CLIENT_ID"],
              "client_secret": e["VERDA_CLIENT_SECRET"]}).encode())["access_token"]
    def aget(path):
        req = urllib.request.Request(VBASE + path, headers={"User-Agent": UA, "Authorization": "Bearer " + tok})
        with urllib.request.urlopen(req, timeout=40) as r: return json.load(r)
    types = aget("/instance-types"); ts_t = NOW()
    want = {}
    for t in types:
        n = (t.get("gpu") or {}).get("number_of_gpus") or 0; desc = (t.get("gpu") or {}).get("description") or ""
        model = "H100 SXM" if "H100 SXM" in desc else "A100 SXM" if "A100 SXM" in desc else "RTX 4090" if "4090" in desc else None
        if not model or n != 1: continue  # 1-GPU types: matches feed rows "(1x GPU)"
        want[t["instance_type"]] = (model, round(t["gpu_memory"]["size_in_gigabytes"] / n), t.get("price_per_hour"), t.get("spot_price"))
    rows = []
    _VERDA.clear(); _VERDA.update(aget=aget, its={})  # v3.0: kept for the second read pass (same token, read-only GET)
    for tier, spot, pkey in (("On-demand instance (1x GPU)", "false", 2), ("Spot instance (1x GPU)", "true", 3)):
        av = aget(f"/instance-availability?is_spot={spot}"); FIRST_READ["Verda|" + spot] = time.time(); ts = NOW()
        loc_has = {a["location_code"]: set(a.get("availabilities") or []) for a in av}
        groups = defaultdict(list)
        for it, w in want.items(): groups[(w[0], w[1])].append(it)
        for (model, vram), its in sorted(groups.items()):
            prices = [float(want[i][pkey]) for i in its if want[i][pkey]]
            price = min(prices) if prices else None
            in_locs = sorted(l for l, has in loc_has.items() if has & set(its))
            _VERDA["its"][(model, vram)] = list(its)
            base = dict(vendor="Verda", source="authenticated vendor API (not publicly reproducible)",
                        gpu_model=model, vram_gb=vram, tier=tier, offer_count=None, stock_level=None,
                        price_usd_hr=price, price_basis=("instance-types %s (1 GPU)" % ("spot_price" if spot == "true" else "price_per_hour")) if price else None,
                        source_url=f"{VBASE}/instance-availability?is_spot={spot} + /instance-types", collected_at=ts,
                        price_refresh="4h" if spot == "true" else "daily", availability_refresh="4h", vram_note=None,
                        availability_note="offer_count not exposed by Verda API; in_stock=false means no listed location reports this type available")
            obs = None if in_locs else "authenticated observation: sold out - no Verda location listed this type as available at check time"
            rows.append({**base, "region": "all", "in_stock": bool(in_locs), "observation": obs, "derived_from_regions": True})
            for loc in sorted(loc_has):
                rows.append({**base, "region": loc, "in_stock": loc in in_locs,
                             "observation": None if loc in in_locs else "authenticated observation: not listed as available in this location"})
    return rows

CLORE = "https://api.clore.ai/v1/marketplace"  # public, no auth
CLORE_GPU = {"NVIDIA A100SXM440GB": ("A100 SXM", 40), "NVIDIA GeForce RTX 4090": ("RTX 4090", 24), "NVIDIA H100 NVL": ("H100 NVL", 94)}
CLORE_NOTE = "unrented servers (one server may hold several GPUs), any currency"
def clore():
    """Clore.ai public marketplace. v2.5: emits unrented_servers (NOT offer_count: the feed's Clore offer_count counts USD-listed offers). Exact GPU names only (4090 D / Laptop excluded);
    VRAM must equal the model's VRAM (e.g. hosts reporting 23 or 48 GB for a 4090 are skipped, not coerced)."""
    servers = get(CLORE)["servers"]; FIRST_READ["Clore.ai"] = time.time(); ts = NOW()
    by = _clore_count(servers); seen = by.pop("_seen")
    rows = []
    for (model, vram) in sorted(set(CLORE_GPU.values())):
        regs = sorted(r for (k, r) in by if k == (model, vram) and r != "all")
        n = by.get(((model, vram), "all"), 0)
        base = dict(vendor="Clore.ai", gpu_model=model, vram_gb=vram, tier="Marketplace on-demand", stock_level=None, price_usd_hr=None, price_basis=None,
                    source_url=CLORE + " (servers[].rented == false)", collected_at=ts, price_refresh="4h", availability_refresh="4h", vram_note=None,
                    availability_note=CLORE_NOTE, observation=None if n else ("0 unrented servers in this snapshot" + ("" if (model, vram) in seen else "; model not listed at all")))
        # v3.5c (Gauge QA 20261030T222314Z): overall never in_stock=True on its own; it becomes True only when a per-host region
        # (servers[].specs.net.cc, the host's own country code) is confirmed in stock on two reads (see second_reads/finalize_clore).
        rows.append({**base, "region": "all", "in_stock": None if n > 0 else False, "unrented_servers": n})
        for r in regs: rows.append({**base, "region": r, "in_stock": True, "unrented_servers": by[((model, vram), r)], "observation": None,
                                    "confirmation": "single_read", "confirmed": None})
    return rows
def _clore_count(servers):
    """Unrented servers per ((model, vram), region); region "all" = every unrented server, cc = host's specs.net.cc (never invented)."""
    by = defaultdict(int); seen = set()
    for v in servers:
        sp = v.get("specs") or {}; g = sp.get("gpu") or ""
        if "x " not in g: continue
        name = g.split("x ", 1)[1].strip()
        if name not in CLORE_GPU or sp.get("gpuram") != CLORE_GPU[name][1]: continue
        k = CLORE_GPU[name]; seen.add(k)
        if v.get("rented") is not False: continue
        by[(k, "all")] += 1
        cc = (sp.get("net") or {}).get("cc")
        if cc: by[(k, cc)] += 1
    by["_seen"] = seen
    return by
def finalize_clore(rows):
    """v3.5c: no Clore row says in_stock=True without a two-read confirmed region. Unconfirmed region rows -> in_stock null;
    overall row -> True only if >= 1 confirmed region, else null (False kept only for an observed zero)."""
    grp = lambda r: (r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))
    conf = {grp(r) for r in rows if r.get("vendor") == "Clore.ai" and r.get("region") not in (None, "all") and r.get("in_stock") is True and r.get("confirmed") is True}
    for r in rows:
        if r.get("vendor") != "Clore.ai": continue
        if r.get("region") not in (None, "all"):
            if r.get("in_stock") is True and r.get("confirmed") is not True:
                r["in_stock"] = None; r["observation"] = "listed unrented on one read only; not confirmed on a second read"
        elif r.get("in_stock") is not False:
            r["in_stock"] = True if grp(r) in conf else None
            if r["in_stock"] is None and r.get("unrented_servers"): r["observation"] = "no host region confirmed in stock on two reads; in_stock unknown"
    return rows

LBASE = "https://cloud.lambda.ai/api/v1/instance-types"  # read-only GET; never launch/mutate
LAMBDA = {"gpu_1x_h100_sxm5": ("H100 SXM", 80, 1), "gpu_1x_h100_pcie": ("H100 PCIe", 80, 1), "gpu_1x_a100_sxm4": ("A100 SXM", 40, 1),
          "gpu_1x_a100": ("A100 PCIe", 40, 1), "gpu_8x_h100_sxm5": ("H100 SXM", 80, 8), "gpu_8x_a100_80gb_sxm4": ("A100 SXM", 80, 8)}
def lambda_(path="secrets/lambda.env"):
    import base64
    key = _verda_env(path)["LAMBDA_API_KEY"]
    req = urllib.request.Request(LBASE, headers={"User-Agent": UA, "Authorization": "Basic " + base64.b64encode((key + ":").encode()).decode()})
    with urllib.request.urlopen(req, timeout=40) as r: data = json.load(r)["data"]
    ts = NOW(); rows = []
    for it, (model, vram, n) in LAMBDA.items():
        v = data.get(it)
        if not v: continue  # type not listed -> no row (unknown)
        t = v["instance_type"]; desc = t.get("gpu_description") or ""
        assert f"{vram} GB" in desc, (it, desc)  # VRAM read from API, not assumed
        regs = sorted(r["name"] for r in v.get("regions_with_capacity_available") or [])
        base = dict(vendor="Lambda", source="authenticated vendor API (not publicly reproducible)", gpu_model=model, vram_gb=vram,
                    tier=f"On-demand instance ({n}x GPU)", offer_count=None, stock_level=None,
                    price_usd_hr=round(t["price_cents_per_hour"] / 100 / n, 4), price_basis="price_cents_per_hour / GPUs",
                    source_url=LBASE + " regions_with_capacity_available", collected_at=ts, price_refresh="daily", availability_refresh="4h", vram_note=None,
                    availability_note="offer_count not exposed by Lambda API; in_stock=false means no region listed capacity for this instance type")
        rows.append({**base, "region": "all", "in_stock": bool(regs),
                     "observation": None if regs else "authenticated observation: sold out - regions_with_capacity_available empty at check time", "derived_from_regions": True})  # v3.3
        for reg in regs: rows.append({**base, "region": reg, "in_stock": True, "observation": None})
    return rows

# ---- T73: CloudRift public instance-types API (no auth; POST is a read-only list query) ----
CR_URL = "https://api.cloudrift.ai/api/v1/instance-types/list"
CR_BODY = json.dumps({"version": "2025-02-10", "data": {"selector": {"ByServiceAndLocation": {"services": ["vm"]}}}}).encode()
CR_GPU = {("A100 SXM4", 80): ("A100 SXM", 80)}  # T73 (Gauge fix 2): A100 SXM 80GB only
CR_TIMEOUT = 20
CR_NOTE = "tier 'On-demand' is INFERRED by Scout (the CloudRift API has no tier label); the feed join attaches this claim only if cost_per_hour/100 equals the feed price and VRAM is 80 GB. available_gpus = CloudRift nodes with a free 1-GPU slot per data center (available_nodes_per_dc of the 1-GPU variant); nodes, not GPUs"
def _cr_get():
    req = urllib.request.Request(CR_URL, data=CR_BODY, headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=CR_TIMEOUT) as r: return json.load(r)
def _cr_count(doc):
    """{(gpu_model, vram): {"listed": bool, "dc": {dc: free nodes}}} from 1-GPU variants only. VRAM is read from the API
    (per-GPU bytes, rounded to GB; the 23-GB reading of a 24-GB 4090 is accepted, anything else is skipped, never coerced)."""
    out = {}
    for it in (doc.get("data") or {}).get("instance_types") or []:
        for v in it.get("variants") or []:
            if v.get("gpu_count") != 1 or not isinstance(v.get("vram"), int): continue
            if v.get("cpu_sharing_policy") != "Dedicated" or v.get("mig_profile") is not None: continue  # T73 (Gauge fix 2): Packed / MIG never counted
            gb = round(v["vram"] / 2**30)
            k = CR_GPU.get((it.get("brand_short"), gb))
            if not k: continue
            e_ = out.setdefault(k, {"listed": True, "dc": {}})
            for dc, n in (v.get("available_nodes_per_dc") or {}).items():
                if isinstance(n, int): e_["dc"][dc] = e_["dc"].get(dc, 0) + n
            e_.setdefault("total", 0); e_["total"] += v.get("available_nodes") or 0
            cph = v.get("cost_per_hour"); e_.setdefault("prices", set())
            if isinstance(cph, (int, float)): e_["prices"].add(round(cph / 100, 4))  # API cents/h -> USD/h
    return out
def cloudrift():
    """Rows only for models CloudRift lists. Overall in_stock False only when the API's own available_nodes is 0 (confirmed by a
    second read >= 60s later via zero_capacity_two_reads); region rows only for data centers with free nodes. Never invents."""
    data = _cr_count(_cr_get()); FIRST_READ["CloudRift"] = time.time(); ts = NOW(); rows = []
    for (model, vram), d in sorted(data.items()):
        pr = sorted(d.get("prices") or [])
        base = dict(vendor="CloudRift", gpu_model=model, vram_gb=vram, tier="On-demand", offer_count=None, stock_level=None,
                    price_usd_hr=pr[0] if len(pr) == 1 else None, price_basis="cost_per_hour / 100, 1-GPU Dedicated variant" if len(pr) == 1 else None, source_url=CR_URL + " (available_nodes_per_dc, 1-GPU variant)", collected_at=ts, price_refresh="daily",
                    availability_refresh="4h", vram_note=None, availability_note=CR_NOTE, source="public no-auth API", observation=None)
        tot = d.get("total", 0)
        rows.append({**base, "region": "all", "in_stock": True if tot > 0 else False, "available_gpus": None, "derived_from_regions": True,
                     "observation": None if tot else "public API: available_nodes 0 for the 1-GPU variant at check time"})
        for dc, n in sorted(d["dc"].items()):
            if n > 0: rows.append({**base, "region": dc, "in_stock": True, "available_gpus": None})
    import vendor_overrides as _vo; _ov = _vo.load_vendor_overrides()
    return [_vo.apply_vendor_overrides(r, _ov) for r in rows]  # CloudRift 2026-11-04: vendor_overrides.json (additive)

class _KeyedHTTPError(RuntimeError):
    """T73: HTTP error from a keyed API: keeps .code (for backoff) but never the request headers/key."""
    def __init__(self, vendor, code): super().__init__(f"{vendor} HTTP {code}"); self.code = code
# ---- T73: Hyperstack GET /v1/core/stocks (read-only, api_key header; key from env HYPERSTACK_API_KEY or HS_KEY_FILE, never logged) ----
HS_URL = "https://infrahub-api.nexgencloud.com/v1/core/stocks"
HS_DOCS = "https://docs.hyperstack.cloud/docs/api-reference/get-gpu-stock"  # source_url: public docs, never the key
HS_KEY_FILE = "/workspace/secrets/hyperstack_api_key.txt"
HS_TIMEOUT = 20
# Exact API model string -> (feed gpu, vram, feed tier). Anything not listed (incl. Reservation tiers) stays unknown.
HS_MODELS = {"H100-80G-SXM5": ("H100 SXM", 80, "On-demand"), "H100-80G-PCIe-NVLink": ("H100 NVLink", 80, "On-demand"),
             "H100-80G-PCIe": ("H100 PCIe", 80, "On-demand"), "A100-80G-SXM4": ("A100 SXM", 80, "On-demand"),
             "A100-80G-PCIe-NVLink": ("A100 NVLink", 80, "On-demand"), "A100-80G-PCIe": ("A100 PCIe", 80, "On-demand"),
             "H100-80G-PCIe-spot": ("H100 PCIe", 80, "Spot VM"), "A100-80G-PCIe-spot": ("A100 PCIe", 80, "Spot VM")}
HS_NOTE = "tier 'On-demand' for non-spot models is INFERRED by Scout (the stock API has no tier label; '-spot' models map to 'Spot VM'); the feed join attaches the claim only if the live pricebook price (GET /v1/pricebook, same exact model name) equals the feed price and VRAM matches. Hyperstack stock API 'available' per region (string, e.g. '10+' read as >= 10); model matched by exact API name incl. VRAM; Reservation prices have no stock signal and stay unknown"
def _hs_key():
    k = os.environ.get("HYPERSTACK_API_KEY")
    if not k:
        with open(HS_KEY_FILE) as f: k = f.read()
    k = k.strip()
    if not k: raise RuntimeError("Hyperstack key missing")
    return k
HS_PRICE_URL = "https://infrahub-api.nexgencloud.com/v1/pricebook"  # read-only GET, same key
def _hs_get(url=None):
    req = urllib.request.Request(url or HS_URL, headers={"User-Agent": UA, "accept": "application/json", "api_key": _hs_key()})
    try:
        with urllib.request.urlopen(req, timeout=HS_TIMEOUT) as r: return json.load(r)
    except urllib.error.HTTPError as ex: raise _KeyedHTTPError("Hyperstack", ex.code) from None  # message never carries headers/key
def _hs_count(doc):
    """{(gpu, vram, tier): {region: n}} for exact model names only. Unparseable 'available' -> region skipped (unknown)."""
    import re
    out = {}
    for st in (doc or {}).get("stocks") or []:
        if st.get("stock-type") != "GPU" or not st.get("region"): continue
        for m in st.get("models") or []:
            k = HS_MODELS.get(m.get("model"))
            a = m.get("available")
            if not k or not isinstance(a, str) or not re.fullmatch(r"\d+\+?", a.strip()): continue
            out.setdefault(k, {})[st["region"]] = int(a.strip().rstrip("+"))
    return out
def _hs_prices(book):
    """{exact model name: USD/h} from the pricebook; non-numeric values skipped (price stays null -> join gate fails -> unknown)."""
    out = {}
    for it in book if isinstance(book, list) else []:
        try: out[it["name"]] = round(float(it["value"]), 4)
        except (KeyError, TypeError, ValueError): pass
    return out
HS_PRICE_KEY = {v: k for k, v in HS_MODELS.items()}  # (gpu, vram, tier) -> exact API model name
def hyperstack():
    """Region rows for regions with available > 0; overall in_stock False only when every listed region reads 0 (confirmed by a
    second read >= 60s later). Models absent from the response emit no rows (unknown)."""
    data = _hs_count(_hs_get()); FIRST_READ["Hyperstack"] = time.time(); ts = NOW(); rows = []
    try: prices = _hs_prices(_hs_get(HS_PRICE_URL))
    except Exception: prices = {}  # no live price -> claims not attached at the join (never a guessed price)
    for (model, vram, tier), regs in sorted(data.items()):
        pr = prices.get(HS_PRICE_KEY[(model, vram, tier)])
        base = dict(vendor="Hyperstack", gpu_model=model, vram_gb=vram, tier=tier, offer_count=None, stock_level=None, price_usd_hr=pr,
                    price_basis="GET /v1/pricebook value for " + HS_PRICE_KEY[(model, vram, tier)] if pr is not None else None,
                    source_url=HS_DOCS, collected_at=ts, price_refresh="daily", availability_refresh="4h", vram_note=None, availability_note=HS_NOTE,
                    source="Hyperstack API (read-only key)", observation=None)
        tot = sum(regs.values())
        rows.append({**base, "region": "all", "in_stock": tot > 0, "available_gpus": None, "derived_from_regions": True,
                     "observation": None if tot else "Hyperstack stock API: available 0 in every listed region at check time"})
        for rg, n in sorted(regs.items()):
            if n > 0: rows.append({**base, "region": rg, "in_stock": True, "available_gpus": None})
    return rows

# ---- T73: Novita GPU products list (read-only GET, Bearer key from env NOVITA_API_KEY or NV_KEY_FILE, never logged; no deploys) ----
NV_URL = "https://api.novita.ai/gpu-instance/openapi/v1/products?gpuNum=1&billingMethod=onDemand"
NV_DOCS = "https://docs.novita.ai/api-reference/gpu-instance-list-products"
NV_KEY_FILE = "/workspace/secrets/novita_api_key.txt"
NV_TIMEOUT = 20
NV_MODELS = {"RTX 4090 24GB": ("RTX 4090", 24)}  # exact product name incl. VRAM; anything else ignored
NV_IN, NV_OUT = ("low", "normal", "high"), ("none",)
NV_NOTE = ("Novita products API (gpuNum=1, billingMethod=onDemand): in stock = availableDeploy true AND inventoryState low/normal/high; "
           "out of stock = availableDeploy false AND inventoryState none for every matching product; mixed/other -> unknown. "
           "Region rows only for a deployable product that lists exactly one cluster (multi-cluster lists don't say which cluster has stock)")
ONE_HOUR_VENDORS = ("Novita AI",)  # T73: overall rows expire after 1h, not 8h
def _nv_key():
    k = os.environ.get("NOVITA_API_KEY")
    if not k:
        with open(NV_KEY_FILE) as f: k = f.read()
    k = k.strip()
    if not k: raise RuntimeError("Novita key missing")
    return k
def _nv_get():
    req = urllib.request.Request(NV_URL, headers={"User-Agent": UA, "Content-Type": "application/json", "Authorization": "Bearer " + _nv_key()})
    try:
        with urllib.request.urlopen(req, timeout=NV_TIMEOUT) as r: return json.load(r)
    except urllib.error.HTTPError as ex: raise _KeyedHTTPError("Novita", ex.code) from None  # message never carries headers/key
def _nv_state(doc):
    """{(gpu, vram): {"in_stock": True/False/None, "regions": set of single-cluster deployable regions, "prices": set}}"""
    out = {}
    for p in (doc or {}).get("data") or []:
        k = NV_MODELS.get(p.get("name"))
        if not k or "onDemand" not in (p.get("billingMethods") or []): continue
        ad, inv = p.get("availableDeploy"), p.get("inventoryState")
        st = True if ad is True and inv in NV_IN else False if ad is False and inv in NV_OUT else None
        e_ = out.setdefault(k, {"states": [], "regions": set(), "prices": set()})
        e_["states"].append(st)
        regs = p.get("regions") or []
        if st is True and len(regs) == 1: e_["regions"].add(regs[0])
        try: e_["prices"].add(round(int(p.get("price")) / 100000, 4))  # API 1/100000 USD per hour
        except (TypeError, ValueError): pass
    for e_ in out.values():
        ss = e_.pop("states")
        e_["in_stock"] = True if True in ss else False if ss and all(x is False for x in ss) else None
    return out
def novita():
    data = _nv_state(_nv_get()); FIRST_READ["Novita AI"] = time.time(); ts = NOW(); rows = []
    for (model, vram), d in sorted(data.items()):
        if d["in_stock"] is None: continue  # unknown stays unknown
        pr = sorted(d["prices"])
        base = dict(vendor="Novita AI", gpu_model=model, vram_gb=vram, tier="On-demand", offer_count=None, stock_level=None,
                    price_usd_hr=pr[0] if len(pr) == 1 else None, price_basis="price / 100000 (onDemand, 1 GPU)" if len(pr) == 1 else None,
                    source_url=NV_DOCS, collected_at=ts, price_refresh="daily", availability_refresh="4h", vram_note=None, availability_note=NV_NOTE,
                    source="Novita API (read-only key)", observation=None, available_gpus=None)
        rows.append({**base, "region": "all", "in_stock": d["in_stock"],
                     "observation": None if d["in_stock"] else "Novita products API: every RTX 4090 24GB product availableDeploy false, inventoryState none"})
        for rg in sorted(d["regions"]): rows.append({**base, "region": rg, "in_stock": True})
    return rows

# ---- T73: Thunder Compute GET /v2/status + /v2/pricing (read-only, documented no-auth: no token is sent; no creates) ----
TC_BASE = "https://api.thundercompute.com:8443"
TC_DOCS = "https://www.thundercompute.com/docs/api-reference/utilities/get-gpu-availability"
TC_TIMEOUT = 20
TC_SPECS = {"h100_x1": ("H100 SXM", 80), "a100xl_x1": ("A100", 80)}  # 1-GPU spec keys (tnr CLI: a100xl = A100 80GB); no RTX 4090 offered
TC_OUT = ("unavailable", "sold_out", "out_of_stock")  # explicit only; any other status string -> unknown
TC_NOTE = ("Thunder /v2/status specs[<gpu>_x1]: 'available' -> in stock, unavailable/sold_out/out_of_stock -> out, anything else unknown; "
           "price from /v2/pricing[<gpu>_x1] (USD/h). The API has no region, so only an overall claim is made")
ONE_HOUR_VENDORS += ("Thunder Compute",)
def _tc_get(path):
    h = {"User-Agent": UA, "accept": "application/json"}  # T73 rev4: no Authorization header (endpoints are no-auth)
    try:
        with urllib.request.urlopen(urllib.request.Request(TC_BASE + path, headers=h), timeout=TC_TIMEOUT) as r: return json.load(r)
    except urllib.error.HTTPError as ex: raise _KeyedHTTPError("Thunder", ex.code) from None
def _tc_state(status, pricing):
    sp = (status or {}).get("specs") or {}; pm = (pricing or {}).get("pricing") or {}; out = {}
    for key, k in TC_SPECS.items():
        st = sp.get(key); pr = pm.get(key)
        ins = True if st == "available" else False if st in TC_OUT else None
        out[k] = {"in_stock": ins, "price": float(pr) if isinstance(pr, (int, float)) and not isinstance(pr, bool) else None}
    return out
def thunder():
    data = _tc_state(_tc_get("/v2/status"), _tc_get("/v2/pricing")); FIRST_READ["Thunder Compute"] = time.time(); ts = NOW(); rows = []
    for (model, vram), d in sorted(data.items()):
        if d["in_stock"] is None and d["price"] is None: continue  # nothing observed
        rows.append(dict(vendor="Thunder Compute", gpu_model=model, vram_gb=vram, tier="On-demand", region="all", in_stock=d["in_stock"], offer_count=None,
                         stock_level=None, available_gpus=None, price_usd_hr=d["price"], price_basis="/v2/pricing <gpu>_x1" if d["price"] is not None else None,
                         source_url=TC_DOCS, collected_at=ts, price_refresh="daily", availability_refresh="4h", vram_note=None, availability_note=TC_NOTE,
                         source="Thunder Compute API (read-only)", observation=None if d["in_stock"] is not False else "Thunder /v2/status: 1-GPU spec not available"))
    return rows

# ---- v3.0: Oblivus public availability page (per-location GPU counts) ----
OBL_URL = "https://oblivus.com/availability/"
OBL_GPU = {"H100 80GB SXM5": ("H100 SXM", 80), "H100 80GB NVLINK": ("H100 NVLink", 80), "H100 80GB PCIE": ("H100 PCIe", 80), "A100 80GB PCIE": ("A100 PCIe", 80)}
def parse_oblivus(page):
    """-> {(gpu_model, vram): {location: count}} from the 'GPU Availability' table; only cells that parse as ints."""
    import re, html as H
    i = page.find("GPU Availability"); seg = page[i:]
    tbl = seg[seg.find("<table"):seg.find("</table>")]
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S)
    cells = [[H.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)] for tr in trs]
    if not cells or cells[0][0].upper() != "GPU": raise ValueError("Oblivus availability table not found")
    locs = [c.split(" (")[0].strip() for c in cells[0][1:]]  # 'MON1 (CANADA, MONTREAL)' -> 'MON1'
    labels = {c.split(" (")[0].strip(): c for c in cells[0][1:]}
    out = {}
    for row in cells[1:]:
        if row and row[0] in OBL_GPU and len(row) == len(locs) + 1:
            out[OBL_GPU[row[0]]] = {l: int(v) for l, v in zip(locs, row[1:]) if v.isdigit()}
    return out, labels
def _get_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; LanternWorks-Scout/0.2)"})
    with urllib.request.urlopen(req, timeout=40) as r: return r.read().decode("utf-8", "replace")
FIRST_READ = {}  # source -> time.time() of its first read (v3.0: 60s gap measured per source)
def oblivus():
    data, labels = parse_oblivus(_get_text(OBL_URL)); FIRST_READ["Oblivus"] = time.time(); ts = NOW(); rows = []
    for (model, vram), per in sorted(data.items()):
        base = dict(vendor="Oblivus", gpu_model=model, vram_gb=vram, tier="On-demand", offer_count=None, stock_level=None, price_usd_hr=None, price_basis=None,
                    source_url=OBL_URL + " (GPU Availability table)", collected_at=ts, price_refresh="daily", availability_refresh="4h", vram_note=None,
                    availability_note="available_gpus = GPUs available per location on Oblivus' public availability page", source="public vendor web page", observation=None)
        rows.append({**base, "region": "all", "in_stock": sum(per.values()) > 0, "available_gpus": sum(per.values()), "derived_from_regions": True})
        for loc, n in sorted(per.items()):
            rows.append({**base, "region": labels[loc],
                         "in_stock": n > 0, "available_gpus": n, "_loc": loc})
    return rows

# ---- v3.0: second read pass for sources counted toward the H100 target (Vast H100, Oblivus) ----
SECOND_READ_GAPS = {}
RP_SECOND_GAP = 60  # v3.1: RunPod per-DC second read >= 60s after its first
RP_GAPS = []
RP_CLOCK = time.time
SECOND_READ_MIN_GAP = 60  # seconds between first and second read
VAST_CONFIRM = tuple(VAST)  # v3.5 (Gauge 2): every Vast model gets the second read (was H100 SXM/PCIe only)
def _vast_regions(url):
    have = defaultdict(int); offers = get(url).get("offers", [])
    have["_total"] = len(offers)  # v3.5: raw offer count (zero-offer check), not a region key
    for o in offers:
        if not o.get("num_gpus") or not o.get("gpu_ram"): continue
        reg = (o.get("geolocation") or "").split(",")[-1].strip() or None
        if reg: have[(round(o["gpu_ram"] / 1024), reg)] += 1
    return have
def second_reads(rows, first_read_at=None, sleep=time.sleep, clock=time.time, first=None):
    """Re-read Vast H100 bundles, Verda availability and the Oblivus page; confirmed = in stock on both reads (matched by location).
    v3.0: waits until >= SECOND_READ_MIN_GAP after THAT source's own first read, and logs the measured gap. Never invents."""
    first = FIRST_READ if first is None else first
    log, GAPS = [], {}
    def wait_for(key):
        t0 = first.get(key, first_read_at if first_read_at is not None else clock())
        w = SECOND_READ_MIN_GAP - (clock() - t0)
        if w > 0: sleep(w)
        return t0
    def gap(key, t0): GAPS[key] = round(clock() - t0, 1)
    vast_urls = {}
    for r in rows:
        if r["vendor"] == "Vast.ai" and r["gpu_model"] in VAST_CONFIRM and (r["region"] != "all" or r.get("offer_count") == 0): vast_urls[r["source_url"]] = r["gpu_model"]  # v3.5: zero-offer models re-read too
    jobs = [("Vast.ai|" + m, "vast", u) for u, m in vast_urls.items()]
    if _VERDA.get("aget") and any(r["vendor"] == "Verda" for r in rows): jobs += [("Verda|" + sp, "verda", sp) for sp in ("false", "true")]
    if any(r["vendor"] == "Oblivus" for r in rows): jobs.append(("Oblivus", "oblivus", None))
    if any(r["vendor"] == "Clore.ai" and r["region"] != "all" for r in rows): jobs.append(("Clore.ai", "clore", None))  # v3.5c
    if any(r["vendor"] == "CloudRift" for r in rows): jobs.append(("CloudRift", "cloudrift", None))  # T73
    if any(r["vendor"] == "Hyperstack" for r in rows): jobs.append(("Hyperstack", "hyperstack", None))  # T73
    if any(r["vendor"] == "Novita AI" for r in rows): jobs.append(("Novita AI", "novita", None))  # T73
    if any(r["vendor"] == "Thunder Compute" for r in rows): jobs.append(("Thunder Compute", "thunder", None))  # T73
    jobs.sort(key=lambda j: first.get(j[0], 0))  # earliest first read first -> least waiting
    for key, kind, arg in jobs:
        t0 = wait_for(key)
        try:
            if kind == "vast":
                have = _vast_regions(arg); ts = NOW(); gap(key, t0)
                for r in rows:
                    if r["vendor"] == "Vast.ai" and r["source_url"] == arg and r["region"] != "all":
                        n2 = have.get((r["vram_gb"], r["region"]), 0)
                        r.update(confirmation="two_reads", confirmed=bool(r["in_stock"]) and n2 > 0, second_read_offer_count=n2, second_read_at=ts)
                    elif r["vendor"] == "Vast.ai" and r["source_url"] == arg and r.get("offer_count") == 0:  # v3.5: zero offers on both reads
                        n2 = have["_total"]; r.update(confirmation="two_reads", second_read_offer_count=n2, second_read_at=ts, zero_capacity_two_reads=n2 == 0)
            elif kind == "verda":
                av = _VERDA["aget"](f"/instance-availability?is_spot={arg}"); ts = NOW(); gap(key, t0)
                loc_has = {a["location_code"]: set(a.get("availabilities") or []) for a in av}
                for r in rows:
                    if r["vendor"] != "Verda" or r["region"] == "all" or ("Spot" in r["tier"]) != (arg == "true"): continue
                    its = set(_VERDA["its"].get((r["gpu_model"], r["vram_gb"]), []))
                    in2 = bool(loc_has.get(r["region"], set()) & its) if r["region"] in loc_has else None
                    r.update(confirmation="two_reads", confirmed=bool(r["in_stock"]) and in2 is True, second_read_in_stock=in2, second_read_at=ts)
            elif kind == "clore":
                by2 = _clore_count(get(CLORE)["servers"]); ts = NOW(); gap(key, t0)
                for r in rows:
                    if r["vendor"] == "Clore.ai" and r["region"] != "all":
                        n2 = by2.get(((r["gpu_model"], r["vram_gb"]), r["region"]), 0)
                        r.update(confirmation="two_reads", confirmed=bool(r["in_stock"]) and n2 > 0, second_read_unrented_servers=n2, second_read_at=ts)
            elif kind == "cloudrift":  # T73
                d2 = _cr_count(_cr_get()); ts = NOW(); gap(key, t0)
                for r in rows:
                    if r["vendor"] != "CloudRift": continue
                    g2 = d2.get((r["gpu_model"], r["vram_gb"]))
                    if r["region"] != "all":
                        n2 = None if g2 is None else g2["dc"].get(r["region"], 0)
                        r.update(confirmation="two_reads", confirmed=bool(r["in_stock"]) and bool(n2), second_read_in_stock=None if n2 is None else n2 > 0, second_read_at=ts)
                    else:
                        r.update(confirmation="two_reads", second_read_at=ts, zero_capacity_two_reads=(r["in_stock"] is False and g2 is not None and g2.get("total", 0) == 0))
            elif kind == "hyperstack":  # T73
                d2 = _hs_count(_hs_get()); ts = NOW(); gap(key, t0)
                for r in rows:
                    if r["vendor"] != "Hyperstack": continue
                    g2 = d2.get((r["gpu_model"], r["vram_gb"], r["tier"]))
                    if r["region"] != "all":
                        n2 = None if g2 is None else g2.get(r["region"], 0)
                        r.update(confirmation="two_reads", confirmed=bool(r["in_stock"]) and bool(n2), second_read_in_stock=None if n2 is None else n2 > 0, second_read_at=ts)
                    else:
                        r.update(confirmation="two_reads", second_read_at=ts, zero_capacity_two_reads=(r["in_stock"] is False and g2 is not None and sum(g2.values()) == 0))
            elif kind == "thunder":  # T73: stock claim kept only if both reads agree; otherwise unknown
                d2 = _tc_state(_tc_get("/v2/status"), {}); ts = NOW(); gap(key, t0)
                for r in rows:
                    if r["vendor"] != "Thunder Compute": continue
                    s2 = (d2.get((r["gpu_model"], r["vram_gb"])) or {}).get("in_stock")
                    agree = r["in_stock"] is not None and s2 is r["in_stock"]
                    r.update(confirmation="two_reads", second_read_at=ts, second_read_in_stock=s2, confirmed=agree, zero_capacity_two_reads=(r["in_stock"] is False and agree))
                    if r["in_stock"] is not None and not agree: r.update(in_stock=None, observation="Thunder reads disagreed -> unknown")
            elif kind == "novita":  # T73: overall claim kept only if both reads agree; otherwise unknown
                d2 = _nv_state(_nv_get()); ts = NOW(); gap(key, t0)
                for r in rows:
                    if r["vendor"] != "Novita AI": continue
                    g2 = d2.get((r["gpu_model"], r["vram_gb"])) or {"in_stock": None, "regions": set()}
                    if r["region"] != "all":
                        r.update(confirmation="two_reads", confirmed=bool(r["in_stock"]) and r["region"] in g2["regions"], second_read_in_stock=r["region"] in g2["regions"], second_read_at=ts)
                    else:
                        agree = g2["in_stock"] is r["in_stock"]
                        r.update(confirmation="two_reads", second_read_at=ts, second_read_in_stock=g2["in_stock"], confirmed=agree,
                                 zero_capacity_two_reads=(r["in_stock"] is False and agree))
                        if not agree: r.update(in_stock=None, observation="Novita reads disagreed -> unknown")
            else:
                data, _ = parse_oblivus(_get_text(OBL_URL)); ts = NOW(); gap(key, t0)
                for r in rows:
                    if r["vendor"] == "Oblivus" and r["region"] != "all":
                        n2 = data.get((r["gpu_model"], r["vram_gb"]), {}).get(r["_loc"])
                        r.update(confirmation="two_reads", confirmed=bool(r["in_stock"]) and bool(n2), second_read_available_gpus=n2, second_read_at=ts)
        except Exception as ex:
            log.append({"source": key.split("|")[0], "key": key, "error": type(ex).__name__})
        time.sleep(1)
    SECOND_READ_GAPS.clear(); SECOND_READ_GAPS.update(GAPS)
    finalize_clore(rows)  # v3.5c: runs even if the Clore second read failed (then nothing is confirmed -> null)
    for r in rows: r.pop("_loc", None)
    return log

CLAIM_TTL, REGION_TTL, SPOT_REGION_TTL = timedelta(hours=8), timedelta(hours=1), timedelta(minutes=15)
DERIVED_VENDORS = ("Lambda", "Verda", "Oblivus", "RunPod", "Vast.ai", "Clore.ai", "CloudRift", "Hyperstack")  # T73: CloudRift, Hyperstack  # v3.5c: Clore overall capped 1h too; v3.3; v3.5 (Gauge a): Vast overall rows capped 1h + recomputed from regions
def feed_min_market_offers(path=None):
    """v3.2: the feed's own publish threshold (feed-src core/gpu.py MIN_MARKET_OFFERS); None if not readable (then nothing is marked)."""
    import re
    path = path or os.path.join(os.environ.get("SCOUT_DIR") or os.path.dirname(os.path.abspath(__file__)), "feed-src", "core", "gpu.py")
    try: m = re.search(r"^MIN_MARKET_OFFERS\s*=\s*(\d+)", open(path).read(), re.M)
    except OSError: return None
    return int(m.group(1)) if m else None
def mark_vast_held(rows, min_offers):
    """v3.2: Vast (model, vram) groups whose overall offer_count is below the feed's minimum are held from the feed; mark every row
    of the group feed_status='held_below_min_offers' (readings themselves are kept unchanged)."""
    if not min_offers: return rows
    held = {(r["gpu_model"], r["vram_gb"]) for r in rows if r["vendor"] == "Vast.ai" and r["region"] == "all" and r.get("offer_count") and r["offer_count"] < min_offers}
    for r in rows:
        if r["vendor"] == "Vast.ai" and (r["gpu_model"], r["vram_gb"]) in held:
            r["feed_status"] = "held_below_min_offers"; r["feed_min_offers"] = min_offers
    return rows
def add_claim_fields(rows):
    """v2.7: every row making a non-null claim (in_stock, stock_level or price) gets checked_at=collected_at, source, availability_expires_at=+8h."""
    finalize_clore(rows)  # v3.5c safety net (idempotent)
    for r in rows:
        if r.get("region") not in (None, "all"):  # v2.9: every region row says how it was confirmed
            r.setdefault("confirmation", "single_read"); r.setdefault("confirmed", None)
        r["stock_level_scope"] = None if r.get("stock_level") is None else "aggregate" if r.get("region") == "all" else "region"
        claim = any(r.get(k) is not None for k in ("in_stock", "stock_level", "price_usd_hr", "offer_count", "unrented_servers"))
        r.setdefault("source", "public no-auth API")
        if claim and r.get("collected_at"):
            r["checked_at"] = r["collected_at"]
            spot = r.get("vendor") == "Verda" and "Spot" in (r.get("tier") or "")
            ttl = SPOT_REGION_TTL if spot else REGION_TTL if r.get("vendor") in ONE_HOUR_VENDORS else CLAIM_TTL if r.get("region") == "all" else REGION_TTL  # T73: Novita 1h  # v3.2: Verda spot overall AND region rows 15m  # v2.9: per-region/data-center claims 1h, overall rows 8h
            r["availability_expires_at"] = (datetime.strptime(r["collected_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + ttl).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            r["checked_at"] = None; r["availability_expires_at"] = None
    # v3.3: overall rows of region-reporting vendors never outlive their regions: latest in-stock region expiry, or +1h when none
    # (sold out / no region signal); never past +1h (Verda spot keeps 15m).
    grp = lambda r: (r.get("vendor"), r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))
    for o in rows:
        if o.get("region") != "all" or o.get("vendor") not in DERIVED_VENDORS or not o.get("availability_expires_at"): continue
        o["derived_from_regions"] = True
        cap = datetime.strptime(o["collected_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + min(REGION_TTL, SPOT_REGION_TTL if "Spot" in (o.get("tier") or "") and o["vendor"] == "Verda" else REGION_TTL)
        cap = cap.strftime("%Y-%m-%dT%H:%M:%SZ")
        ins = [r["availability_expires_at"] for r in rows if r.get("region") not in (None, "all") and grp(r) == grp(o) and r.get("in_stock") is True and r.get("availability_expires_at")]
        o["availability_expires_at"] = min(max(ins), cap) if (ins and o.get("in_stock") is True) else cap
    return rows

def after_second_reads(rows, meta, log):
    """T73 (Gauge fix 1): gap meta is ALWAYS written; only the CloudRift drop is conditional on its second read failing."""
    meta["second_read_log"] = log
    meta["second_read_gap_s"] = dict(SECOND_READ_GAPS); meta["runpod_second_read_gap_s"] = {"min": min(RP_GAPS, default=None), "max": max(RP_GAPS, default=None), "n": len(RP_GAPS)}
    for v in ("CloudRift", "Hyperstack", "Novita AI", "Thunder Compute"):
        if any(x["source"] == v for x in log):  # unconfirmed claims are dropped, not kept
            rows = [r for r in rows if r["vendor"] != v]; meta["nonfatal_errors"] = dict(meta.get("nonfatal_errors") or {}, **{v: "second read failed"})
    return rows

# T73 advisory: per-source backoff. After an error a source is skipped for BACKOFF_CYCLES runs (BACKOFF_429 after HTTP 429/5xx).
BACKOFF_FILE, BACKOFF_CYCLES, BACKOFF_429 = os.environ.get("SCOUT_BACKOFF_FILE") or "out/.source_backoff.json", 1, 3
def with_backoff(name, fn, path=None):
    path = path or BACKOFF_FILE
    try: st = json.load(open(path))
    except (OSError, ValueError): st = {}
    if st.get(name, 0) > 0:
        st[name] -= 1; json.dump(st, open(path, "w")); raise RuntimeError(f"backoff: skipped ({st[name]} more runs after this)")
    try: out = fn()
    except Exception as ex:
        code = getattr(ex, "code", None)
        st[name] = BACKOFF_429 if code == 429 or (isinstance(code, int) and code >= 500) else BACKOFF_CYCLES
        json.dump(st, open(path, "w")); raise
    if name in st: st.pop(name); json.dump(st, open(path, "w"))
    return out

if __name__ == "__main__":
    rows, errs, meta = [], {}, {}
    t_first = time.time()
    try: r = vast(); rows += r; print("vast", len(r))
    except Exception as e: errs["vast"] = repr(e)
    try: r, obs = runpod(); rows += r; meta["runpod_stock_level_observed"] = obs; print("runpod", len(r), obs)
    except Exception as e: errs["runpod"] = repr(e)
    try: r = verda(); rows += r; print("verda", len(r))
    except Exception as e: errs["verda"] = type(e).__name__ + ": " + str(e)[:200]
    try: r = clore(); rows += r; print("clore", len(r))
    except Exception as e: errs["clore"] = repr(e)
    _lam = None
    try:  # T113 fix: the 4h cycle now takes Lambda's second read too (same code as refresh_multi); without it every Lambda
        # claim was nulled by scout_io.rederive_overall (regions unconfirmed, sold-out rows lack zero_capacity_two_reads)
        import refresh_multi as _rm; _lam = _rm; r = _rm.lambda_first(); rows += r; print("lambda", len(r))
    except Exception as e: errs["lambda"] = type(e).__name__ + ": " + str(e)[:200]
    try: r = oblivus(); rows += r; print("oblivus", len(r))
    except Exception as e: errs["oblivus"] = type(e).__name__ + ": " + str(e)[:200]
    try: r = with_backoff("CloudRift", cloudrift); rows += r; print("cloudrift", len(r))  # T73: non-fatal (never fails the cycle); 20s HTTP timeout
    except Exception as e: meta["nonfatal_errors"] = dict(meta.get("nonfatal_errors") or {}, CloudRift=type(e).__name__ + ": " + str(e)[:200])
    try: r = with_backoff("Hyperstack", hyperstack); rows += r; print("hyperstack", len(r))  # T73: non-fatal; 20s timeout
    except Exception as e: meta["nonfatal_errors"] = dict(meta.get("nonfatal_errors") or {}, Hyperstack=type(e).__name__ + ": " + str(e)[:200])
    try: r = with_backoff("Novita AI", novita); rows += r; print("novita", len(r))  # T73: non-fatal; 20s timeout
    except Exception as e: meta["nonfatal_errors"] = dict(meta.get("nonfatal_errors") or {}, **{"Novita AI": type(e).__name__ + ": " + str(e)[:200]})
    try: r = with_backoff("Thunder Compute", thunder); rows += r; print("thunder", len(r))  # T73: non-fatal; 20s timeout
    except Exception as e: meta["nonfatal_errors"] = dict(meta.get("nonfatal_errors") or {}, **{"Thunder Compute": type(e).__name__ + ": " + str(e)[:200]})
    rows = after_second_reads(rows, meta, second_reads(rows, t_first))
    if _lam is not None and "lambda" not in errs:
        try: meta["second_read_gap_s"]["Lambda"] = _lam.lambda_second(rows)
        except Exception as e:  # T113: unconfirmed Lambda claims are dropped (unknown), never kept; non-fatal
            rows = [r for r in rows if r["vendor"] != "Lambda"]; meta["nonfatal_errors"] = dict(meta.get("nonfatal_errors") or {}, Lambda="second read failed: " + type(e).__name__)
    for r in rows: r.setdefault("source", "public no-auth API"); r.setdefault("observation", None)
    meta["queried"] = QUERIED
    meta["runpod_dc_query_log"] = RP_LOG  # every per-DC query that errored, came back empty, or null for a listed GPU (after retries)
    mark_vast_held(rows, feed_min_market_offers()); meta["feed_min_market_offers"] = feed_min_market_offers()
    add_claim_fields(rows)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    doc = {"version": "3.2", "collected_at": NOW(), "errors": errs, "meta": meta, "rows": rows}
    json.dump(doc, open(f"out/availability_v2_{stamp}{'_FAILED' if errs else ''}.json", "w"), indent=1)
    if errs:  # keep last good *_latest; signal failure to cron
        print("ERRORS, latest files not overwritten:", errs, file=sys.stderr); sys.exit(1)
    try:
        json.dump(doc, open("out/.availability_v2_staged.json.tmp", "w"), indent=1)
    except BaseException:
        if os.path.exists("out/.availability_v2_staged.json.tmp"): os.remove("out/.availability_v2_staged.json.tmp")
        raise
    os.replace("out/.availability_v2_staged.json.tmp", "out/availability_v2_staged.json")  # v3.0: enrich promotes snapshot+enriched together
    print(errs or "no errors")
