"""Anonymous opt-in install id: off by default, one local UUID, collector validation, stats rollup."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from mcp_server import telemetry  # noqa: E402
import site_stats as S  # noqa: E402

ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ID2 = "11111111-2222-4333-8444-555555555555"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("LANTERN_TELEMETRY", raising=False)
    monkeypatch.delenv("LANTERN_TELEMETRY_URL", raising=False)
    monkeypatch.delenv("LANTERN_REF", raising=False)


def test_off_by_default_no_file_nothing_sent(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        telemetry.urllib.request, "urlopen",
        lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("network")),
    )
    for v in (None, "0", "true", "yes", ""):
        if v is not None:
            monkeypatch.setenv("LANTERN_TELEMETRY", v)
        assert not telemetry.enabled()
        telemetry.record("search_deals", "0.3.3")
    assert calls == []
    assert not telemetry._install_id_path().exists()
    assert not telemetry._state_path().exists()
    assert not list(tmp_path.rglob("*"))


def test_on_creates_id_once_reuses_and_payload_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("LANTERN_TELEMETRY", "1")
    monkeypatch.setenv("LANTERN_TELEMETRY_URL", "")
    monkeypatch.setenv("LANTERN_REF", "pypi")
    telemetry.record("search_deals", "0.3.3")
    path = telemetry._install_id_path()
    assert path.is_file()
    uid = path.read_text(encoding="utf-8").strip()
    assert telemetry.INSTALL_ID_RE.fullmatch(uid)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    telemetry.record("get_deal", "0.3.3")
    assert path.read_text(encoding="utf-8").strip() == uid
    payload = telemetry.build_payload(
        {"2026-11-19": {"search_deals|0.3.3": 2}}, telemetry._get_or_create_install_id(), telemetry._ref()
    )
    assert set(payload) == {"events", "install_id", "ref"}
    assert payload["install_id"] == uid
    assert payload["ref"] == "pypi"
    assert payload["events"] == [{"t": "search_deals", "v": "0.3.3", "d": "2026-11-19", "n": 2}]
    assert set(payload["events"][0]) == {"t", "v", "d", "n"}
    for bad in ("127.0.0.1", os.path.expanduser("~")):
        assert bad not in payload["install_id"]


def test_invalid_lantern_ref_is_other_or_none(monkeypatch):
    monkeypatch.setenv("LANTERN_REF", "Nope!")
    assert telemetry._ref() == "other"
    monkeypatch.delenv("LANTERN_REF", raising=False)
    assert telemetry._ref() == "none"
    monkeypatch.setenv("LANTERN_REF", "readme")
    assert telemetry._ref() == "readme"


def _js(expr: str, argv: list[str]) -> str:
    return subprocess.check_output(
        ["node", "--input-type=module", "-e", expr, *argv],
        cwd=ROOT / "collector", text=True,
    )


def test_server_validation_uuid_only_and_ignores_bad_id():
    expr = r"""
import { validate, installMeta } from './src/index.js';
const body = JSON.parse(process.argv[1]);
const now = new Date('2026-11-20T12:00:00Z');
const err = validate(body, now);
const meta = err ? null : installMeta(body);
process.stdout.write(JSON.stringify({ err, meta }));
"""
    ev = [{"t": "search_deals", "v": "0.3.3", "d": "2026-11-19", "n": 1}]
    ok = json.loads(_js(expr, [json.dumps({"events": ev, "install_id": ID, "ref": "pypi"})]))
    assert ok["err"] is None and ok["meta"] == {"id": ID, "ref": "pypi"}
    bad = json.loads(_js(expr, [json.dumps({"events": ev, "install_id": "not-a-uuid", "ref": "pypi"})]))
    assert bad["err"] is None and bad["meta"]["id"] is None and bad["meta"]["ref"] == "pypi"
    long_id = ID + "a"
    long = json.loads(_js(expr, [json.dumps({"events": ev, "install_id": long_id})]))
    assert long["meta"]["id"] is None
    extra = json.loads(_js(expr, [json.dumps({"events": ev, "ip": "1.2.3.4"})]))
    assert extra["err"]
    ev_extra = json.loads(_js(expr, [json.dumps({"events": [{**ev[0], "install_id": ID}]})]))
    assert ev_extra["err"]  # event fields stay exactly t, v, d, n


def test_stats_aggregation_installs_by_ref_distinct_returning():
    from datetime import datetime, timezone
    telemetry = {
        "rows": [{"day": "2026-11-02", "tool": "search_deals", "version": "0.3.3", "n": 2}],
        "installs": {
            "distinct": 2,
            "returning": 1,
            "by_ref": {"pypi": 1, "readme": 1},
            "by_week": [
                {"week": "2026-W45", "distinct": 2, "returning": 1, "by_ref": {"pypi": 1, "readme": 1}},
            ],
        },
    }
    now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    wk = S.build({"rows": [{"day": "2026-11-02", "ref": "x", "n": 1}]}, telemetry, None, 12, now)["weeks"][0]
    assert wk["week"] == "2026-W45"
    assert wk["installs_by_ref"] == {"pypi": 1, "readme": 1}
    assert wk["distinct_installs"] == 2
    assert wk["returning_installs"] == 1
    assert wk["installs_null_reason"] is None
    # returning = install id seen on 2+ distinct UTC days in the stats window
    missing = S.build({"rows": [{"day": "2026-11-02", "ref": "x", "n": 1}]},
                      {"rows": [{"day": "2026-11-02", "version": "0.3.3", "n": 1}]}, None, 12, now)["weeks"][0]
    assert missing["installs_by_ref"] is None and "install id" in missing["installs_null_reason"]


def test_collector_aggregate_returning_definition():
    expr = r"""
import { aggregateInstalls, isoWeek } from './src/index.js';
const rows = JSON.parse(process.argv[1]);
process.stdout.write(JSON.stringify({ week: isoWeek('2026-11-02'), out: aggregateInstalls(rows) }));
"""
    rows = [
        {"day": "2026-11-02", "install_id": ID, "ref": "pypi", "version": "0.3.3"},
        {"day": "2026-11-03", "install_id": ID, "ref": "pypi", "version": "0.3.3"},
        {"day": "2026-11-03", "install_id": ID2, "ref": "readme", "version": "0.3.3"},
        {"day": "2026-11-03", "install_id": "ci", "ref": "ci", "version": "0.0.0"},
    ]
    data = json.loads(_js(expr, [json.dumps(rows)]))
    assert data["week"] == "2026-W45"
    out = data["out"]
    assert out["distinct"] == 2 and out["returning"] == 1
    assert out["by_ref"] == {"pypi": 1, "readme": 1}
    w = out["by_week"][0]
    assert w["week"] == "2026-W45" and w["distinct"] == 2 and w["returning"] == 1
    blob = json.dumps(out)
    assert ID not in blob and ID2 not in blob
