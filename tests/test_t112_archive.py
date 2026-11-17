"""T112 7d window must survive an out/ wipe when the P42 probe archive (or scout-data history/probes) is present."""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scout"))
import t112_build  # noqa: E402


def _snap(collected_at, vendor="Vast.ai", gpu="H100 SXM", vram=80, tier="on-demand", in_stock=True, **extra):
    row = {"vendor": vendor, "gpu_model": gpu, "vram_gb": vram, "tier": tier, "region": "all",
           "in_stock": in_stock, "collected_at": collected_at}
    return {"ok": True, "collected_at": collected_at, "rows": [row], **extra}


def _write_json(path: Path, collected_at: str, **extra):
    source = path.name
    path.write_text(json.dumps(_snap(collected_at, source_file=source, **extra)) + "\n", encoding="utf-8")
    return source


def _write_archive(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _stamp(h: int, name=None):
    """2026-11-16 12:00Z minus h hours as collected_at and a matching availability_v2 filename."""
    t = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    from datetime import timedelta
    at = (t - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    token = (t - timedelta(hours=h)).strftime("%Y%m%dT%H%M%SZ")
    fname = name or f"availability_v2_{token}.json"
    return at, fname


def test_wiping_out_does_not_zero_the_window(tmp_path, monkeypatch):
    """The Nov 15 reseed left only the latest out/ JSON; the 7d window must still come from the archive."""
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-16T12:00:00Z")
    out = tmp_path / "out"
    out.mkdir()
    # Three recent out/ checks, also archived, plus four older archive-only checks (all inside 7d).
    hours = [0, 4, 8, 12, 16, 24, 36]
    recs = []
    for h in hours:
        at, fname = _stamp(h)
        recs.append(_snap(at, source_file=fname))
        if h <= 8:  # only the newest three live in out/
            _write_json(out / fname, at)
    _write_archive(out / "probe_archive" / "2026-11-16.jsonl.gz", recs)

    full = t112_build.build(src=str(out))
    assert full["snapshots_used"] == 7
    assert full["generated_at"] == "2026-11-16T12:00:00Z"
    assert full["version"] == "3.2"
    assert all(r["checks_7d"] == 7 for r in full["rows"])

    # Wipe out/ JSON the way the Nov 15 reseed did; leave the P42 archive.
    for f in out.glob("availability_v2_*.json"):
        f.unlink()
    assert not list(out.glob("availability_v2_*.json"))

    wiped = t112_build.build(src=str(out))
    assert wiped["snapshots_used"] == 7, "archive-only build must not zero the 7d window"
    assert wiped["snapshots_used"] == full["snapshots_used"]
    assert wiped["rows"] == full["rows"]


def test_out_and_archive_copies_dedupe_by_source_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-16T12:00:00Z")
    out = tmp_path / "out"
    out.mkdir()
    at, fname = _stamp(1)
    _write_json(out / fname, at)
    _write_archive(out / "probe_archive" / "2026-11-16.jsonl.gz", [_snap(at, source_file=fname)])
    doc = t112_build.build(src=str(out))
    assert doc["snapshots_used"] == 1
    assert doc["rows"][0]["checks_7d"] == 1


def test_scout_data_history_probes_are_read(tmp_path, monkeypatch):
    """scout-data publishes the same jsonl.gz layout at history/probes/."""
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-16T12:00:00Z")
    src = tmp_path / "latest"
    src.mkdir()
    at, fname = _stamp(6)
    probes = tmp_path / "history" / "probes"
    _write_archive(probes / "2026-11-16.jsonl.gz", [_snap(at, source_file=fname)])
    doc = t112_build.build(src=str(src))
    assert doc["snapshots_used"] == 1


def test_missing_timestamp_or_failed_snapshot_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-16T12:00:00Z")
    out = tmp_path / "out"
    out.mkdir()
    at, fname = _stamp(2)
    recs = [
        _snap(at, source_file=fname),
        {"ok": True, "rows": [_snap(at)["rows"][0]]},  # no collected_at
        {"ok": False, "collected_at": "2026-11-16T01:00:00Z", "source_file": "availability_v2_20261116T010000Z.json",
         "rows": [_snap("2026-11-16T01:00:00Z")["rows"][0]]},
        {"ok": True, "collected_at": "not-a-time", "source_file": "availability_v2_bad.json",
         "rows": [_snap(at)["rows"][0]]},
    ]
    _write_archive(out / "probe_archive" / "2026-11-16.jsonl.gz", recs)
    doc = t112_build.build(src=str(out))
    assert doc["snapshots_used"] == 1


def test_window_uses_lw_avail_now(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    inside, fname_in = _stamp(24)          # 2026-11-15T12:00Z
    outside, fname_out = _stamp(24 * 8)    # 8 days earlier
    recs = [_snap(inside, source_file=fname_in), _snap(outside, source_file=fname_out)]
    _write_archive(out / "probe_archive" / "mix.jsonl.gz", recs)
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-16T12:00:00Z")
    doc = t112_build.build(src=str(out))
    assert doc["snapshots_used"] == 1
    assert doc["generated_at"] == "2026-11-16T12:00:00Z"
    assert doc["rows"][0]["first_check_at"] == inside
