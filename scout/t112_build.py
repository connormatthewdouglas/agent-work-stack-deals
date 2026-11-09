"""T112 (Scout side): per vendor/model/tier observed in-stock share over trailing 7d of Scout snapshots. Read-only on history."""
import json,glob,collections,sys
from datetime import datetime,timezone,timedelta
def build(src=None, days=7, now=None):
    import os; src=src or os.path.join(os.environ.get("SCOUT_DIR") or os.path.dirname(os.path.abspath(__file__)),"out")
    now=now or datetime.now(timezone.utc); cut=now-timedelta(days=days)
    agg=collections.defaultdict(lambda:{"checks":0,"in_stock":0,"out_of_stock":0,"unknown":0,"first":None,"last":None,"last_known":None}); n=0
    for f in sorted(glob.glob(src+"/availability_v2_2026*.json")):
        if "FAILED" in f or "BROKEN" in f: continue
        try: d=json.load(open(f)); t=datetime.strptime(d["collected_at"],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception: continue
        if t<cut: continue
        n+=1
        for r in d["rows"]:
            if r.get("region")!="all": continue
            a=agg[(r["vendor"],r["gpu_model"],r["vram_gb"],r["tier"])]; a["checks"]+=1; s=r.get("in_stock")
            a["in_stock" if s is True else "out_of_stock" if s is False else "unknown"]+=1
            ts=r.get("collected_at") or d["collected_at"]; a["first"]=a["first"] or ts; a["last"]=ts
            if s is not None: a["last_known"]=ts
    rows=[]
    for k,a in sorted(agg.items(),key=lambda x:tuple(str(v) for v in x[0])):
        known=a["in_stock"]+a["out_of_stock"]
        rows.append(dict(zip(("vendor","gpu_model","vram_gb","tier"),k),checks_7d=a["checks"],known_checks_7d=known,in_stock_checks_7d=a["in_stock"],
            availability_rate_7d=round(a["in_stock"]/known,3) if known else None,known_share_7d=round(known/a["checks"],3),
            first_check_at=a["first"],last_check_at=a["last"],last_known_at=a["last_known"],sufficient_sample=known>=12))
    return {"version":"3.2","kind":"t112_availability_rate_inputs","generated_at":now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window":f"trailing {days}d of Scout snapshots (overall region='all' rows; 4h cycles + multi refreshes; unknown checks excluded from the rate)",
        "snapshots_used":n,"join_key":"vendor, gpu_model, vram_gb, tier (snapshot keys; feed join via enrich_feed_v2.key())","rows":rows}
if __name__=="__main__":
    doc=build(); json.dump(doc,open(sys.argv[1] if len(sys.argv)>1 else "out/t112_availability_rate_7d.json","w"),indent=1)
    rs=doc["rows"]; print(doc["snapshots_used"],len(rs),sum(r["availability_rate_7d"] is not None for r in rs),sum(r["sufficient_sample"] for r in rs))
