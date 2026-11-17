"""Gauge NO-GO on #261 (B1, B2) and Bjorn 2026-11-17: warn >36h, hard fail >7d; empty or zero-row = fail."""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "release_gate"))
import check_scout_snapshot_rows as C  # noqa: E402
import t41_staleness as STL  # noqa: E402

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
LIM = timedelta(hours=8)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def rid(r):
    return f"{r['advertiser']}|{r['gpu']}"


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _stale_regex():
    sh = (ROOT / "scripts" / "check_latest_scout_import.sh").read_text(encoding="utf-8")
    return re.search(r"grep -Eq '(.+?)' \"\$T/import.log\"", sh).group(1)


# ---- B1: latest-scout-import ----

def test_b1_unparseable_age_is_not_merely_stale():
    pat = _stale_regex()
    assert re.search(pat, "Scout snapshot 2026-11-16T18:47:50Z is 11.8h old (> 8h); refusing to import")
    assert not re.search(pat, "Scout snapshot (no checked_at) is ?h old (> 8h); refusing to import")
    assert not re.search(pat, "Scout snapshot x is ?.?h old (> 8h); refusing to import")


def test_b1_empty_rows_with_matching_manifest_fails(tmp_path):
    snap = tmp_path / "feed_enriched_v2_latest.json"
    raw = json.dumps({"version": "2", "rows": []}).encode()
    snap.write_bytes(raw)
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": hashlib.sha256(raw).hexdigest()}}))
    env = {**os.environ, "LW_SCOUT_MANIFESTS": str(man), "LW_SCOUT_AVAIL": str(tmp_path / "none.json")}
    p = subprocess.run([sys.executable, "scripts/import_scout_availability.py", str(snap)], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    out = p.stdout + p.stderr
    assert p.returncode != 0
    assert not re.search(_stale_regex(), out, re.M)       # the gate does not treat it as merely stale
    assert C.problems({"version": "2", "rows": []}, None) # and the pre-check fails it first
    assert C.main([str(snap)]) == 1


def test_b1_zero_rows_per_source_and_no_checked_at_fail():
    good = {"rows": [{"vendor": "Civo", "availability_checked_at": "2026-11-17T10:00:00Z"},
                     {"vendor": "RunPod", "availability_checked_at": "2026-11-17T10:00:00Z"}]}
    main = {"rows": [{"vendor": "Civo"}, {"vendor": "RunPod"}, {"vendor": "Lambda"}]}
    assert C.problems(good, {"rows": [{"vendor": "Civo"}]}) == []
    gone = C.problems(good, main)
    assert len(gone) == 1 and "Lambda" in gone[0]
    assert C.problems(good, main, held=lambda v: v == "Lambda") == []   # held vendors are dropped by the importer
    bad = {"rows": [{"vendor": "Civo", "availability_checked_at": "not a time"}, {"vendor": "RunPod"}]}
    assert any("no parseable availability_checked_at" in p for p in C.problems(bad, None))


# ---- B2: T41-12 / T41-24 / T41-26 ----

def test_t41_12_feed_age_warn_40h_fail_200h_778h():
    assert STL.FEED_WARN_H == 36 and STL.STALE_FAIL_H == 168
    assert STL.feed_age(NOW - timedelta(hours=20), NOW) == ([], [])
    f, w = STL.feed_age(NOW - timedelta(hours=40), NOW)
    assert f == [] and len(w) == 1 and "40.0h" in w[0]
    for h in (200, 778):
        f, w = STL.feed_age(NOW - timedelta(hours=h), NOW)
        assert len(f) == 1 and f"{h}.0h" in f[0] and "hard cap" in f[0] and w == []


def _claim(late_h, **extra):
    chk = NOW - LIM - timedelta(hours=late_h)
    a = {"in_stock": True, "checked_at": _iso(chk), "availability_expires_at": _iso(chk + LIM)}
    a.update(extra)
    return {"advertiser": "Civo", "gpu": "H100", "availability": a}


def test_t41_24_expired_claim_warn_40h_fail_200h_778h():
    assert STL.claims_t41_24("gpu-prices.json", [_claim(-1)], NOW, LIM, ts, rid)[:2] == ([], [])
    f, w, n = STL.claims_t41_24("gpu-prices.json", [_claim(40)], NOW, LIM, ts, rid)
    assert f == [] and len(w) == 1 and n == 1
    for h in (200, 778):
        f, w, _ = STL.claims_t41_24("gpu-prices.json", [_claim(h)], NOW, LIM, ts, rid)
        assert len(f) == 1 and "hard cap" in f[0] and w == []


def test_t41_24_zero_rows_and_missing_fields_fail():
    f, _, _ = STL.claims_t41_24("gpu/h100.json", [], NOW, LIM, ts, rid)
    assert f and "zero rows" in f[0]
    r = _claim(-1)
    del r["availability"]["checked_at"]
    assert any("no checked_at" in x for x in STL.claims_t41_24("x", [r], NOW, LIM, ts, rid)[0])
    r = _claim(-1)
    del r["availability"]["availability_expires_at"]
    assert any("without availability_expires_at" in x for x in STL.claims_t41_24("x", [r], NOW, LIM, ts, rid)[0])


def test_t41_26_expired_claim_warn_40h_fail_200h_778h():
    assert STL.claims_t41_26([_claim(-1)], NOW, ts, rid)[:2] == ([], [])
    f, w, _ = STL.claims_t41_26([_claim(40)], NOW, ts, rid)
    assert f == [] and len(w) == 1
    for h in (200, 778):
        f, w, _ = STL.claims_t41_26([_claim(h)], NOW, ts, rid)
        assert len(f) == 1 and "hard cap" in f[0] and w == []


def test_t41_26_zero_rows_missing_regions_and_rule_breaks_fail():
    assert "zero rows" in STL.claims_t41_26([], NOW, ts, rid)[0][0]
    r = _claim(-1, derived_from_regions=True)
    assert any("without regions_expires_at" in x for x in STL.claims_t41_26([r], NOW, ts, rid)[0])
    rp = _claim(-1, origin="scout")
    rp["advertiser"] = "RunPod"
    assert any("no confirmed region" in x for x in STL.claims_t41_26([rp], NOW, ts, rid)[0])  # rule, not staleness


def test_run_t41_carries_bjorns_note():
    src = (ROOT / "tests" / "release_gate" / "run_t41.py").read_text(encoding="utf-8")
    assert src.count("Bjorn 2026-11-17: warn >36h, hard fail >7d; empty or zero-row = fail") >= 3
    assert "STL.feed_age" in src and "STL.claims_t41_24" in src and "STL.claims_t41_26" in src
