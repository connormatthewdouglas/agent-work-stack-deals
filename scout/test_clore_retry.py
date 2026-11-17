#!/usr/bin/env python3
"""Clore GET: bounded retries; final failure is non-fatal (meta.nonfatal_errors), never errs. Schema 3.2 unchanged."""
import os, sys, ast, urllib.error
D = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, D)
import collect_v2 as c
def e401(): return urllib.error.HTTPError(c.CLORE, 401, "Unauthorized", {}, None)
SRV = {"servers": [{"specs": {"gpu": "1x NVIDIA GeForce RTX 4090", "gpuram": 24, "net": {"cc": "US"}}, "rented": False}]}
def run(fails):
    calls = [0]; waits = []
    def fake(url, data=None):
        calls[0] += 1
        if calls[0] <= fails: raise e401()
        return SRV
    c.get = fake
    return calls, waits
# 1: one 401 then success -> returns data, one wait
calls, waits = run(1); assert c.clore_get(sleep=waits.append) == SRV and calls[0] == 2 and waits == [2]
# 2: two 401s then success
calls, waits = run(2); assert c.clore_get(sleep=waits.append) == SRV and calls[0] == 3 and waits == [2, 5]
# 3: always 401 -> exactly CLORE_TRIES calls, last error raised
calls, waits = run(99)
try: c.clore_get(sleep=waits.append); raise SystemExit("expected failure")
except urllib.error.HTTPError as ex: assert ex.code == 401
assert calls[0] == c.CLORE_TRIES == 3 and len(waits) == 2
# 4: clore() retries internally on the first read and still emits rows
c.time.sleep = lambda s: None; calls, waits = run(1); rows = c.clore()
assert rows and calls[0] == 2 and all(r["vendor"] == "Clore.ai" for r in rows)
# 5: collector main: a Clore failure goes to meta.nonfatal_errors, never to errs (so the cycle does not exit 1)
t = ast.parse(open(os.path.join(D, "collect_v2.py")).read())
src = [n for n in ast.walk(t) if isinstance(n, ast.Try) and "clore()" in ast.unparse(n.body)]
assert len(src) == 1; h = ast.unparse(src[0].handlers[0])
assert "nonfatal_errors" in h and "Clore.ai" in h and 'errs[' not in h, h
print("ok: clore retry + nonfatal")
