"""T49: alerts recover after failure and congestion. >40 deliveries with failing early recipients still reach later
recipients; 429/5xx/network retry with bounded backoff and expiry; other 4xx are rejected once; acked never resent;
persistence failure is reported; the push script fails on failed deliveries; a 201-event history is consumed losslessly
with a durable checkpoint."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "hosted" / "src")]

import test_hosted_watch as T  # noqa: E402
import watch as W  # noqa: E402
import watch_store as S  # noqa: E402
from core import deals as D, gpu_history as H  # noqa: E402

GOOD = [f"https://ok{i}.example.com/h" for i in range(3)]
BAD = ["https://aaa-down.example.com/h", "https://aab-down.example.com/h"]


class MultiPoster(T.Poster):
    def __init__(self, status_by_host, headers=None):
        super().__init__()
        self.sb, self.hdr = status_by_host, headers or {}

    async def __call__(self, url, method, headers, body=None, redirect=None):
        if url.startswith(W.DOH_URL):
            return await super().__call__(url, method, headers, body, redirect)
        self.calls.append((url, headers, body))
        host = url.split("/")[2]
        st = self.sb.get(host, 200)
        if st == "exc":
            raise ConnectionError("boom")
        h = self.hdr.get(host, {})
        return types.SimpleNamespace(status=st, headers=types.SimpleNamespace(get=lambda k, h=h: h.get(k)))


def _setup(urls, per_key=10):
    e = T.env()
    f1 = T.feeds_for([T.snap("2026-11-01", T.DAY1)], T.prices_doc(T.DAY1))
    for u in urls:
        api = T.signup(e, u)["api_key"]
        for _ in range(per_key):
            assert T.run(S.call("watch_price", {"gpu": "H100", "max_hourly_usd": 2.0, "api_key": api}, e, None, f1))["ok"]
    f2 = T.feeds_for([T.snap("2026-11-01", T.DAY1), T.snap("2026-11-02", T.DAY2)], T.prices_doc(T.DAY2))
    return e, f2


def _acked(e):
    return T.run(S._all(e.WATCH_DB, "SELECT COUNT(*) AS n FROM watch_deliveries"))[0]["n"]


def test_failing_early_recipients_do_not_starve_later_ones():
    e, f2 = _setup(BAD + GOOD)  # 50 deliveries > 40 per run; the failing hosts sort first by name
    p = MultiPoster({BAD[0].split("/")[2]: 500, BAD[1].split("/")[2]: "exc"})
    t0 = int(time.time())
    r1 = T.run(S.run_cron(e, f2, p, now=t0))
    assert r1["sent"] == 30 and r1["outcomes"]["retry"] == 2  # one attempt per failing host, then deferred
    bad_posts = [c for c in p.calls if "down" in c[0]]
    assert len(bad_posts) == 2
    assert r1["backlog"] >= 18
    for k in range(1, 12):  # 3 days of hourly re-pushes: bounded attempts, then expiry
        T.run(S.run_cron(e, f2, p, now=t0 + k * 7 * 3600))
    st = T.run(S.delivery_status(e.WATCH_DB))
    assert _acked(e) == 30
    rows = T.run(S._all(e.WATCH_DB, "SELECT attempts, last_outcome, done FROM watch_attempts"))
    assert rows and all(r["attempts"] <= W.MAX_ATTEMPTS for r in rows)
    assert st["last_push_at"] and st["last_result"] is not None and "at-least-once" in st["semantics"]


def test_429_retry_after_honoured_and_4xx_rejected_once():
    e, f2 = _setup([GOOD[0], GOOD[1]], per_key=1)
    h0, h1 = GOOD[0].split("/")[2], GOOD[1].split("/")[2]
    p = MultiPoster({h0: 429, h1: 404}, headers={h0: {"retry-after": "7200"}})
    t0 = int(time.time())
    r = T.run(S.run_cron(e, f2, p, now=t0))
    assert r["outcomes"]["retry"] == 1 and r["outcomes"]["rejected"] == 1
    p.sb = {h0: 200, h1: 200}
    assert T.run(S.run_cron(e, f2, p, now=t0 + 3600))["sent"] == 0  # Retry-After 2 h not yet passed; 404 never retried
    assert T.run(S.run_cron(e, f2, p, now=t0 + 7300))["sent"] == 1
    assert T.run(S.run_cron(e, f2, p, now=t0 + 99999))["sent"] == 0  # acked: never resent


def test_classify_and_backoff():
    assert [W.classify(s) for s in (200, 204, 301, 400, 404, 408, 429, 500, 503)] == \
        ["acked", "acked", "rejected", "rejected", "rejected", "retry", "retry", "retry", "retry"]
    assert W.classify(None, True) == "retry"
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert W.next_attempt(1, "2026-11-01T00:00:00Z", now) == "2026-11-01T00:15:00Z"
    assert W.next_attempt(W.MAX_ATTEMPTS, "2026-11-01T00:00:00Z", now) is None
    assert W.next_attempt(2, "2026-10-28T00:00:00Z", now) is None  # past the 72 h expiry


def test_restart_and_missed_refresh_resume_from_db():
    e, f2 = _setup([GOOD[0]], per_key=1)
    h = GOOD[0].split("/")[2]
    t0 = int(time.time())
    T.run(S.run_cron(e, f2, MultiPoster({h: 503}), now=t0))
    # "restart": a fresh worker reads the same D1; a missed day just means the next push, inside the lookback window
    assert T.run(S.run_cron(e, f2, MultiPoster({}), now=t0 + 2 * 86400 - 3600))["sent"] == 1


def test_persistence_failure_is_reported():
    e, f2 = _setup([GOOD[0]], per_key=1)
    real = e.WATCH_DB.prepare

    def prepare(sql):
        if sql.startswith("INSERT OR IGNORE INTO watch_deliveries"):
            raise RuntimeError("D1 down")
        return real(sql)
    e.WATCH_DB.prepare = prepare
    r = T.run(S.run_cron(e, f2, MultiPoster({})))
    assert r["persist_error"] == "RuntimeError" and r["sent"] == 1
    assert T.run(S.delivery_status(e.WATCH_DB))["last_success_at"] is None


def test_push_script_fails_on_failed_deliveries(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("pwe", ROOT / "scripts" / "push_watch_events.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setenv("WATCH_PUSH_SECRET", "x")
    monkeypatch.setattr(sys, "argv", ["push"])
    monkeypatch.setattr(m, "batches", lambda: [{"events": [], "regions": {}, "facts": {}}])

    class R:
        def __init__(self, body):
            self.b = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.b).encode()
    for body, want in (({"ok": True, "sent": 1, "failed": 0}, 0), ({"ok": True, "sent": 0, "failed": 2}, 1),
                       ({"ok": False, "error": "x"}, 1), ({"ok": True, "sent": 1, "failed": 0, "persist_error": "E"}, 1)):
        monkeypatch.setattr(m.urllib.request, "urlopen", lambda req, timeout=30, b=body: R(b))
        assert m.main() == want, body


def test_local_watcher_consumes_201_events_with_checkpoint(tmp_path):
    snaps = [T.snap(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", {"Acme": 2.0 + (i % 2) * 0.1}) for i in range(202)]
    hist = H.build_history(snaps)
    spec = importlib.util.spec_from_file_location("wp", ROOT / "examples" / "gpu-price-watcher" / "watch_prices.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    seen, crash = [], {"n": 0}

    async def call(name, args):
        crash["n"] += 1
        if crash["n"] == 3:
            raise RuntimeError("client crashed mid-run")
        return D.price_changes(None, hist, cursor=args["cursor"], limit=args["limit"], gpu=args.get("gpu"))
    st = str(tmp_path / "state.json")
    try:
        asyncio.run(m.catch_up(call, st, lambda c: seen.append(c["event_id"]), limit=50))
    except RuntimeError:
        pass
    asyncio.run(m.catch_up(call, st, lambda c: seen.append(c["event_id"]), limit=50))
    assert len(set(seen)) == 201 and len(seen) == 201  # crash after a saved page: nothing lost, nothing repeated
    assert asyncio.run(m.catch_up(call, st, lambda c: seen.append(c["event_id"]), limit=50)) == 0
