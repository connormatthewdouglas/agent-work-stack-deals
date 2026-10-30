"""T45 (Brain #131): refresh failures are visible when cached data is served; current prices have a max stale age."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import deals as D  # noqa: E402

GOOD = {"rates": [{"advertiser": "X", "gpu": "H100 SXM", "hourly_usd": 2.0, "checked_at": "2026-10-30T10:00:00Z"}]}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def _loader(tmp_path, cls=D.GpuPricesLoader):
    f = tmp_path / "feed.json"
    f.write_text(json.dumps(GOOD))
    c = Clock()
    return cls(file=str(f), ttl=0, clock=c), f, c


def test_ok_then_outage_serves_cache_visibly_degraded(tmp_path):
    ld, f, c = _loader(tmp_path)
    first = ld.load()
    assert ld.status()["retrieval"] == "ok" and ld.status()["stale_cache"] is False
    f.unlink()  # outage
    c.t += 60
    assert ld.load() is first  # same data, but no longer silent:
    st = ld.status()
    assert st["retrieval"] == "degraded" and st["stale_cache"] is True
    assert st["last_refresh_outcome"].startswith("failed: ") and st["cache_age_s"] == 60
    assert st["last_successful_retrieval_at"] != st["last_refresh_attempt_at"]
    # price verification time stays separate (row checked_at untouched)
    assert first["rates"][0]["checked_at"] == "2026-10-30T10:00:00Z"


def test_partial_refresh_is_degraded(tmp_path):
    ld, f, c = _loader(tmp_path)
    ld.load()
    f.write_text(json.dumps({"rates": "truncated"}))
    c.t += 30
    ld.load()
    assert ld.status()["retrieval"] == "degraded" and ld.status()["last_refresh_outcome"].startswith("invalid: ")


def test_clock_advance_past_policy_refuses_current_prices(tmp_path):
    ld, f, c = _loader(tmp_path)
    ld.load()
    f.unlink()
    c.t += D.STALE_CURRENT_MAX_S + 1
    with pytest.raises(D.DealError) as e:
        ld.load()
    assert e.value.code == "feed_unavailable" and "limit for current prices" in e.value.message


def test_history_remains_readable_after_policy_age(tmp_path):
    f = tmp_path / "h.json"
    f.write_text(json.dumps({"series": []}))
    c = Clock()
    ld = D.GpuHistoryLoader(file=str(f), ttl=0, clock=c)
    ld.load()
    f.unlink()
    c.t += 10 * D.STALE_CURRENT_MAX_S
    assert ld.load() == {"series": []} and ld.status()["retrieval"] == "degraded"


def test_recovery_clears_degraded(tmp_path):
    ld, f, c = _loader(tmp_path)
    ld.load()
    f.unlink()
    c.t += 60
    ld.load()
    f.write_text(json.dumps(GOOD))
    c.t += 60
    ld.load()
    st = ld.status()
    assert st["retrieval"] == "ok" and st["stale_cache"] is False and st["last_refresh_outcome"] == "ok" and st["cache_age_s"] == 0


def test_tool_result_reports_retrieval(tmp_path, monkeypatch):
    from mcp_server import server as s
    ld, f, c = _loader(tmp_path)
    data = json.loads((Path(__file__).resolve().parents[1] / "api/v1/gpu-prices.json").read_text())
    f.write_text(json.dumps(data))
    monkeypatch.setattr(s, "gpu_loader", ld)
    out = s.compare_gpu_prices(gpu="H100")
    assert out["ok"] and out["retrieval"]["status"] == "ok"
    f.unlink()
    c.t += 120
    out = s.compare_gpu_prices(gpu="H100")
    assert out["ok"] and out["retrieval"]["status"] == "degraded"
    g = [x for x in out["retrieval"]["feeds"] if x["feed"] == "GPU prices"][0]
    assert g["stale_cache"] and g["cache_age_s"] == 120
    c.t += D.STALE_CURRENT_MAX_S
    out = s.compare_gpu_prices(gpu="H100")
    assert out["ok"] is False and out["error"]["code"] == "feed_unavailable"
