"""Scout fresh Clore.ai snapshot (Nov 1 2026). Same method as Gauge's 2026-10-29 manual snapshot (/workspace/gauge/clore.py):
price.on_demand['USD-Blockchain'] is a per-DAY whole-server price (Clore API docs); per GPU-hr = value/24/gpu_count.
Available = rented == false. Spot/bid excluded. Homogeneous servers only (every gpu_array entry matches, count matches).
Output is the snapshot format read by agent-work-stack-deals scripts/import_clore_snapshot.py (summary keyed RTX 4090/RTX 5090/A100/H100/L40S
with median, range_on_demand, lowest_available_on_demand_usd_gpu_hr, listings_available; plus per-listing rows). No bridge needed.
Work-box script reviewed 2026-11-09 (sha256 1610acc73a4da8077e20065c053f6512127a116bf558e7d282375c93afd64955); classification below is that script.
Usage: build_clore.py [raw.json] [--out clore_snapshot_latest.json] [--summary clore_summary_latest.json]
Offline rebuild reads checked_at from a YYYYMMDDTHHMMSS token in the raw path. With no raw path, GET the marketplace and
write clore_raw_<timestamp>.json in the working directory."""
import json, re, statistics, sys, urllib.request
from datetime import datetime, timezone

U = "https://api.clore.ai/v1/marketplace"
MIN_MACHINES = 5  # feed rule: fewer than 5 distinct machines -> price withheld
# (importer summary/listing key, name regex, vendor gpuram figure, require SXM)
# Keys match scripts/import_clore_snapshot.py MAP: record "A100 SXM" -> "A100" (40GB SXM only), "H100 NVL" -> "H100" (94GB NVL only).
# RTX 4090 and RTX 5090 both reject a following D or Laptop, so "RTX 5090 D" stays out of the RTX 5090 headline.
SPEC = [("RTX 4090", r"RTX 4090(?! ?D)(?! Laptop)", 24, False), ("RTX 5090", r"RTX 5090(?! ?D)(?! Laptop)", 32, False),
        ("A100", r"A100", 40, True), ("H100", r"H100 NVL", 94, False), ("L40S", r"L40S", 45, False)]


def build(servers, checked_at):
    summary = {}; listings = []
    for key, pat, gram, sxm in SPEC:
        av = []; ids = set(); tot = 0; avail = 0
        for s in servers:
            arr = s.get("gpu_array") or []
            if not arr or not all(re.search(pat, a) for a in arr): continue
            sp_ = s.get("specs") or {}
            if sp_.get("gpuram") != gram: continue
            m = re.match(r"(\d+)x", sp_.get("gpu") or ""); n = int(m.group(1)) if m else len(arr)
            if n != len(arr): continue
            if sxm and not all("SXM" in a for a in arr): continue
            tot += 1
            rented = bool(s.get("rented"))
            od = ((s.get("price") or {}).get("on_demand") or {}).get("USD-Blockchain")
            per = round(od / 24 / n, 4) if od is not None else None
            listings.append(dict(id=s.get("id"), gpu=key, gpu_string=sp_.get("gpu") or arr[0], gpu_count=n, vram_gb_per_gpu=gram,
                                 status="rented" if rented else "available", currency_usd_listed=od is not None,
                                 on_demand_usd_day=od, on_demand_usd_gpu_hr=per))
            if rented: continue
            avail += 1
            if per is not None: av.append(per); ids.add(s.get("id"))
        # every value below is computed from real available USD offers in this read; no offers -> null, never invented
        summary[key] = dict(vram_gb_per_gpu=gram, listings_total=tot, listings_available=avail, available_with_usd_price=len(av),
                            distinct_machines=len(ids),
                            median=round(statistics.median(av), 4) if av else None,
                            range_on_demand=[min(av), max(av)] if av else None,
                            lowest_available_on_demand_usd_gpu_hr=min(av) if av else None)
    return dict(checked_at=checked_at, source_url=U, method="price.on_demand['USD-Blockchain'] per-day whole server / 24 / gpu_count; "
                "available = rented false; spot/bid excluded; homogeneous servers only", servers_in_response=len(servers),
                summary=summary, listings=listings)


def _emit(path, obj, indent, trailing_newline):
    # Same writer as the work-box script: json.dump indent, summary file has no trailing newline, snapshot does.
    json.dump(obj, open(path, "w"), indent=indent)
    if trailing_newline:
        open(path, "a").write("\n")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out, summary_out, raw_path = "clore_snapshot_latest.json", "clore_summary_latest.json", None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--out":
            out = argv[i + 1]; i += 2
        elif a == "--summary":
            summary_out = argv[i + 1]; i += 2
        elif a.startswith("-"):
            raise SystemExit("usage: build_clore.py [raw.json] [--out snapshot.json] [--summary summary.json]")
        elif raw_path is None:
            raw_path = a; i += 1
        else:
            raise SystemExit("usage: build_clore.py [raw.json] [--out snapshot.json] [--summary summary.json]")
    if raw_path:  # offline rebuild from a saved raw read; T = that read's timestamp from the filename
        raw = open(raw_path, "rb").read()
        ts = re.search(r"(\d{8}T\d{6})", raw_path).group(1)
        T = datetime.strptime(ts, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    else:
        req = urllib.request.Request(U, headers={"User-Agent": "lantern-scout/3.2"})
        raw = urllib.request.urlopen(req, timeout=90).read()
        T = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        open("clore_raw_%s.json" % T[:19].replace(":", "").replace("-", ""), "wb").write(raw)
    TZ = T.replace("+00:00", "Z")
    servers = json.loads(raw)["servers"]
    snap = build(servers, TZ)
    _emit(out, snap, 2, True)
    _emit(summary_out, dict(checked_at=TZ, source_url=U, servers_in_response=len(servers), summary=snap["summary"]), 1, False)
    print(TZ, len(servers)); [print(k, v) for k, v in snap["summary"].items()]
    return 0


if __name__ == "__main__":
    sys.exit(main())
