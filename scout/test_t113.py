"""T113: availability_reason is additive and never changes stock claims."""
import os; os.environ["LANTERN_VENDOR_OVERRIDES"] = "off"  # pre-override logic; overrides covered by test_cloudrift_overrides.py
import json, glob, copy
import enrich_feed_v2 as e, importlib.machinery
ORIG = importlib.machinery.SourceFileLoader("orig_enrich", "backup_orig/enrich_feed_v2.py").load_module()
SNAP = json.load(open("out/availability_v2_latest.json"))
FILES = [json.load(open(f)) for f in sorted(glob.glob(e.SRC + "/data/gpu_pricing/*.json"))]
NEW = ("availability_reason", "availability_reason_detail", "availability_status")
def test_additive_only():
    a, sa = e.enrich(FILES, copy.deepcopy(SNAP), None); b, sb = ORIG.enrich(FILES, copy.deepcopy(SNAP), None)
    assert len(a) == len(b) and sa == sb
    for x, y in zip(a, b):
        assert {k: v for k, v in x.items() if k not in NEW} == y
        assert x["availability_reason"] in e.REASONS
def test_unknown_never_stock_reason():
    for r in e.enrich(FILES, copy.deepcopy(SNAP), None)[0]:
        assert r["availability_status"] == {True: "in_stock", False: "out_of_stock", None: "unknown"}[r["in_stock"]]
        if r["in_stock"] is None: assert r["availability_reason"] not in ("in_stock", "out_of_stock")
        else: assert r["availability_reason"] in ("in_stock", "out_of_stock", "stale")
def test_error_paths():
    s = copy.deepcopy(SNAP); s.setdefault("meta", {})["nonfatal_errors"] = {"Thunder Compute": "URLError: <urlopen error [SSL: UNEXPECTED_EOF]>", "Hyperstack": "RuntimeError: backoff: skipped (0 more)"}
    s["errors"] = {"lambda": "_KeyedHTTPError: Lambda HTTP 403"}
    row = {"in_stock": None}
    assert e.availability_reason(row, "Thunder Compute", s) == ("check_failed_http", "ssl_error")
    assert e.availability_reason(row, "Hyperstack", s) == ("stale", "backoff")
    assert e.availability_reason(row, "Lambda", s) == ("check_failed_http", "http_403")
    assert e.availability_reason(row, "Jarvislabs", s) == ("no_source", "no_api")
    assert e.availability_reason(row, "Novita AI", {"meta": {}}, gate="price_gate_mismatch") == ("no_source", "price_gate_mismatch")
    assert e.availability_reason({"in_stock": True, "availability_expires_at": "2000-01-01T00:00:00Z"}, "RunPod", s) == ("stale", "claim_expired")
if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("ok", n)
