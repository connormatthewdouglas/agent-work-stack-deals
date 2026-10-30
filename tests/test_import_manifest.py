import hashlib, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_importer_refuses_sha256_mismatch(tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps({"version": "3.1", "generation_id": "x", "rows": []}))
    good = hashlib.sha256(feed.read_bytes()).hexdigest()
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": {"sha256": "0" * 64}}}))
    env = dict(os.environ, LW_SCOUT_MANIFESTS=str(bad))
    r = subprocess.run([sys.executable, "-c", "import runpy,sys;sys.argv=['x',sys.argv[1]];"
                        "import scripts.import_scout_availability as m;m.verify_manifests(open(sys.argv[1],'rb').read())", str(feed)],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "sha256 mismatch" in r.stderr
    bad.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": good}}))
    r = subprocess.run(r.args, cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_31_plus_requires_manifest(tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps({"version": "3.2", "rows": []}))
    env = {k: v for k, v in os.environ.items() if k != "LW_SCOUT_MANIFESTS"}
    r = subprocess.run([sys.executable, "scripts/import_scout_availability.py", str(feed)], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "no manifest" in r.stderr


def test_held_and_expired_rows_never_available():
    from datetime import datetime, timezone
    from core import gpu_availability as g
    now = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    held = g._scout("Vast.ai", {"in_stock": True, "availability_checked_at": "2026-10-30T14:50:00Z",
                                "availability_expires_at": "2026-10-30T18:50:00Z", "feed_status": "held_below_min_offers"})
    held = g.stale_guard(held, now)
    assert held["in_stock"] is None and held["feed_status"] == "held_below_min_offers" and held["availability_expires_at"]
    short = g._scout("Verda", {"in_stock": True, "availability_checked_at": "2026-10-30T14:40:00Z",
                               "availability_expires_at": "2026-10-30T14:55:00Z", "feed_status": None})
    assert short["availability_expires_at"] == "2026-10-30T14:55:00Z"
    out = g.stale_guard(short, now)
    assert out["in_stock"] is None and out["availability_expires_at"] == "2026-10-30T14:55:00Z"
    ok = g.stale_guard(short, datetime(2026, 10, 30, 14, 50, tzinfo=timezone.utc))
    assert ok["in_stock"] is True


def _run_import(feed, env_extra, tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("LW_SCOUT_MANIFESTS", "LW_SCOUT_AVAIL")}
    env.update(env_extra)
    return subprocess.run([sys.executable, "scripts/import_scout_availability.py", str(feed)], cwd=ROOT, env=env,
                          capture_output=True, text=True)


def test_n4_tampered_30_without_or_against_manifest_refused(tmp_path):
    feed = tmp_path / "feed_enriched_v2_latest.json"
    feed.write_text(json.dumps({"version": "3.0", "rows": [{"vendor": "X", "in_stock": True}]}))
    r = _run_import(feed, {}, tmp_path)  # no manifest at all
    assert r.returncode != 0 and "no manifest" in r.stderr
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": "f" * 64}}))
    r = _run_import(feed, {"LW_SCOUT_MANIFESTS": str(m)}, tmp_path)
    assert r.returncode != 0 and "sha256 mismatch" in r.stderr


def test_n1_derived_claim_unknown_once_regions_expire():
    from datetime import datetime, timezone
    from core import gpu_availability as g
    r = {"in_stock": True, "availability_checked_at": "2026-10-30T15:21:00Z", "availability_expires_at": "2026-10-30T23:21:00Z",
         "derived_from_regions": True, "available_regions": ["MON1"],
         "available_regions_detail": [{"region": "MON1", "availability_expires_at": "2026-10-30T16:21:00Z"}]}
    a = g._scout("Oblivus", r)
    assert g.stale_guard(a, datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc))["in_stock"] is True
    out = g.stale_guard(a, datetime(2026, 10, 30, 16, 22, tzinfo=timezone.utc))
    assert out["in_stock"] is None and not out.get("available_regions")
    os.environ["LW_BUILD_HORIZON_MIN"] = "25"  # re24: a claim expiring within the 25-min build cutoff is left out
    try:
        assert g.stale_guard(a, g.build_now(datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc)))["in_stock"] is None  # 21 min left
        assert g.stale_guard(a, g.build_now(datetime(2026, 10, 30, 15, 30, tzinfo=timezone.utc)))["in_stock"] is True  # 51 min left
    finally:
        del os.environ["LW_BUILD_HORIZON_MIN"]


def test_n2_runpod_overall_without_confirmed_region_unknown(tmp_path):
    from datetime import datetime, timezone, timedelta
    t = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z")
    row = {"vendor": "RunPod", "gpu": "H100 PCIe", "vram_gb": 80, "tier": "On-demand (Secure Cloud)", "in_live_feed": True,
           "in_stock": True, "stock_level": "Low", "availability_checked_at": t, "availability_expires_at": t,
           "available_regions": None}
    feed = tmp_path / "feed_enriched_v2_latest.json"
    feed.write_text(json.dumps({"version": "3.2", "rows": [row]}))
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": hashlib.sha256(feed.read_bytes()).hexdigest()}}))
    out = ROOT / "data/gpu_availability/latest.json"
    keep = out.read_bytes()
    try:
        r = _run_import(feed, {"LW_SCOUT_MANIFESTS": str(m)}, tmp_path)
        assert r.returncode == 0, r.stderr
        got = json.loads(out.read_text())["rows"][0]
        assert got["in_stock"] is None and got["stock_level"] is None and "no region" in got["availability_note"]
    finally:
        out.write_bytes(keep)


def test_re20_p3_lambda_verda_claims_last_one_hour_and_p4_derived_oos_region_expiry():
    from core import gpu_availability as g
    lam = g._scout("Lambda", {"in_stock": True, "availability_checked_at": "2026-10-30T15:21:14Z",
                              "availability_expires_at": "2026-10-30T23:21:14Z"})
    assert lam["availability_expires_at"] == "2026-10-30T16:21:14Z"
    ver = g._scout("Verda (formerly DataCrunch)", {"in_stock": False, "availability_checked_at": "2026-10-30T15:21:13Z",
                                                   "availability_expires_at": "2026-10-30T23:21:13Z", "derived_from_regions": True})
    assert ver["availability_expires_at"] == "2026-10-30T16:21:13Z" and ver["regions_expires_at"] == "2026-10-30T16:21:13Z"
    from datetime import datetime, timezone
    assert g.stale_guard(ver, datetime(2026, 10, 30, 16, 30, tzinfo=timezone.utc))["in_stock"] is None


def test_re20_p1_raw_availability_not_published():
    wf = (ROOT / ".github/workflows/validate-and-deploy.yml").read_text()
    assert "rm -rf _site/data/gpu_availability" in wf


import pytest  # noqa: E402


@pytest.mark.parametrize("live", ["none", "missing", "false"])
def test_only_in_live_feed_true_rows_import(tmp_path, live):
    """Scout merge_enriched rows with in_live_feed None/missing must never import (would be in stock for 8h)."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    iso = lambda d: d.isoformat(timespec="seconds").replace("+00:00", "Z")  # noqa: E731
    base = {"vendor": "Vast.ai", "gpu": "H100 SXM", "vram_gb": 80, "tier": "Marketplace on-demand", "in_stock": True,
            "stock_level": "High", "availability_checked_at": iso(now - timedelta(minutes=5)),
            "availability_expires_at": iso(now + timedelta(hours=8)), "available_regions": None}
    bad = dict(base, gpu="RTX 4090")
    if live == "none":
        bad["in_live_feed"] = None
    elif live == "false":
        bad["in_live_feed"] = False
    good = dict(base, in_live_feed=True)
    feed = tmp_path / "feed_enriched_v2_latest.json"
    feed.write_text(json.dumps({"version": "3.2", "rows": [good, bad]}))
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": hashlib.sha256(feed.read_bytes()).hexdigest()}}))
    out = ROOT / "data/gpu_availability/latest.json"
    keep = out.read_bytes()
    try:
        r = _run_import(feed, {"LW_SCOUT_MANIFESTS": str(m)}, tmp_path)
        assert r.returncode == 0, r.stderr
        rows = json.loads(out.read_text())["rows"]
        assert [x["gpu"] for x in rows] == ["H100 SXM"]
    finally:
        out.write_bytes(keep)
