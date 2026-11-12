"""P41 (marxsignal): keep failed / out-of-stock probes with a fixed reason enum. Additive; never guessed; ranking unchanged."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import contract
from core import deals as core
from core import probe_reason as P
from core.gpu_availability import stale_guard

ROOT = Path(__file__).resolve().parents[1]
CHECK = "2026-11-11T12:00:00Z"
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def _claim(in_stock, **extra):
    a = {"status": "out of stock when checked" if in_stock is False else "available when checked" if in_stock is True else "unknown",
         "in_stock": in_stock, "checked_at": CHECK, "origin": "scout",
         "availability_expires_at": "2026-11-11T13:00:00Z", "max_age_hours": 1.0}
    a.update(extra)
    return a


def _finalize(av, in_stock, mode="full"):
    row = {"rank": 1, "rate_id": "r_000000000001", "advertiser": "A", "gpu": "H100", "hourly_usd": 2.0,
           "source_url": "https://a.example", "availability": av, "in_stock": in_stock}
    if av.get("availability_reason") is not None:
        row["availability_reason"] = av["availability_reason"]
    if av.get("availability_reason_detail") is not None:
        row["availability_reason_detail"] = av["availability_reason_detail"]
    return contract.finalize("compare_gpu_prices", {"gpu": "H100", "summary": "", "count": 1, "results": [row]}, mode)


def test_classify_sold_out_current_and_lapsed():
    assert P.classify(_claim(False)) == {"failure_reason": "sold_out", "failure_reason_detail": None}
    lapsed = stale_guard(_claim(False), T0 + timedelta(hours=2))
    assert lapsed["in_stock"] is None and lapsed["last_known_in_stock"] is False
    assert P.classify(lapsed)["failure_reason"] == "sold_out"  # kept, not dropped
    assert P.classify(_claim(True))["failure_reason"] is None
    assert P.classify(stale_guard(_claim(True), T0 + timedelta(hours=2)))["failure_reason"] is None
    assert P.classify({"status": "unknown", "in_stock": None}) == {"failure_reason": None, "failure_reason_detail": None}


def test_never_guess_region_or_quota():
    # derived_from_regions and "no confirmed region" are not a source-stated region reason
    a = _claim(False, derived_from_regions=True, note="unknown: no confirmed region claim at overall_recomputed_at")
    assert P.classify(a)["failure_reason"] == "sold_out"
    b = _claim(None, availability_reason="no_source", availability_reason_detail="unconfirmed_two_reads")
    assert P.classify(b) == {"failure_reason": None, "failure_reason_detail": None}  # no_source is not a classified no
    c = _claim(None, availability_reason="no_source", availability_reason_detail="api_null_signal")
    assert P.classify(c)["failure_reason"] is None
    # explicit source statements only
    r = _claim(False, availability_reason="region", availability_reason_detail="region_unavailable")
    assert P.classify(r) == {"failure_reason": "region", "failure_reason_detail": "region_unavailable"}
    q = _claim(False, availability_reason_detail="quota_exceeded", note="vendor said quota exceeded")
    assert P.classify(q)["failure_reason"] == "quota" and q["availability_reason_detail"] in P.classify(q)["failure_reason_detail"]
    f = _claim(None, availability_reason="check_failed_http", availability_reason_detail="http_403")
    assert P.classify(f) == {"failure_reason": "other", "failure_reason_detail": "http_403"}
    # our stale-claim note is not source detail
    lapsed = stale_guard(_claim(False), T0 + timedelta(hours=2))
    assert P.classify(lapsed)["failure_reason_detail"] is None


def test_mcp_keeps_reason_on_lapsed_claim_brief_and_full():
    lapsed = stale_guard(_claim(False), T0 + timedelta(hours=2))
    full = _finalize(lapsed, None, "full")["results"][0]
    av = full["availability"]
    assert av["in_stock"] is None and av["last_known_in_stock"] is False
    assert av["failure_reason"] == "sold_out" and av["failure_reason_detail"] is None
    assert full["failure_reason"] == "sold_out"
    brief = _finalize(lapsed, None, "brief")["results"][0]
    assert brief["failure_reason"] == "sold_out" and "failure_reason_detail" not in brief  # null detail omitted
    unknown = _finalize({"status": "unknown", "in_stock": None}, None, "brief")["results"][0]
    assert "failure_reason" not in unknown and "failure_reason_detail" not in unknown


def test_ranking_unchanged_on_the_committed_feed():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    for gpu in ("H100", "A100", "RTX 4090"):
        a = [x["rate_id"] for x in core.compare_gpu_prices(copy.deepcopy(feed), gpu, limit=25, now=T0)["results"]]
        # strip any reason fields if a generator later writes them; ranking must ignore them
        stripped = copy.deepcopy(feed)
        for r in stripped["rates"]:
            for k in P.KEYS:
                r.pop(k, None)
                if isinstance(r.get("availability"), dict):
                    r["availability"].pop(k, None)
        b = [x["rate_id"] for x in core.compare_gpu_prices(stripped, gpu, limit=25, now=T0)["results"]]
        assert a == b, gpu


def test_live_feed_lapsed_no_is_sold_out_and_no_source_is_null():
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    out = contract.finalize("compare_gpu_prices", core.compare_gpu_prices(copy.deepcopy(feed), "H100", limit=25, now=T0), "full")
    sold = [r for r in out["results"] if (r.get("availability") or {}).get("last_known_in_stock") is False]
    assert sold and all(r["failure_reason"] == "sold_out" for r in sold)
    nosrc = [r for r in out["results"] if r.get("availability_reason") == "no_source" or (r.get("availability") or {}).get("availability_reason") == "no_source"]
    assert all(r.get("failure_reason") is None for r in nosrc)


def test_schema_and_manifest_lockstep():
    s = contract.output_schema("compare_gpu_prices")["properties"]["results"]["items"]["properties"]
    assert s["failure_reason"]["enum"] == ["sold_out", "region", "quota", "other", None]
    assert s["failure_reason_detail"]["type"] == ["string", "null"]
    av = s["availability"]["properties"]
    assert av["failure_reason"] == s["failure_reason"]
    assert {"failure_reason", "failure_reason_detail"} <= set(contract.SPEC["compare_gpu_prices"][4])
    assert {"failure_reason", "failure_reason_detail"} <= set(contract.SPEC["estimate_job_cost"][4])
    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    tool = next(t for t in plugin["tools"] if t["name"] == "compare_gpu_prices")
    p = tool["outputSchema"]["properties"]["results"]["items"]["properties"]
    assert p["failure_reason"] == s["failure_reason"] and p["failure_reason_detail"] == s["failure_reason_detail"]
    assert "`failure_reason`" in (ROOT / "docs/GPU-PRICES-FIELDS.md").read_text()
