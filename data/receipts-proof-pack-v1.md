# Receipts — proof pack v1 (T125)
Three representative cases with full evidence: one Works, one Works With
Caveats, one Broken. Assembled by Pax, 2026-11-06, from the canonical
Receipts records and transcripts (~/workspace/receipts/). Verdicts are
version- and date-stamped and are never edited; a retest appends a new
dated entry to a record's history.

Shared environment, all three cases: clean throwaway sandbox (fresh venv /
npx cache) on Pax's Linux VM, stdio transport, driven by the Receipts
probe harness (tools/probe.py), which records the raw JSON-RPC exchange.
No real credentials anywhere: credential-bearing tests use decoy values
created for the test. Transcripts below are excerpts; full transcripts are
the files named in each case. In this pack the decoy Redis password is
redacted as <decoy-password>; the original transcript retains the decoy
string so the leak can be counted.

Corrections and retest requests: open an issue on the Lantern Works repo
(github.com/connormatthewdouglas/agent-work-stack-deals) naming the record
id. Paid re-tests are accepted under the Receipts firewall: money can buy
being measured sooner, never a changed verdict.

---

## Case 1 — WORKS: mcp-server-time (Receipts #002)

- Package: mcp-server-time, version 2026.10.28 (PyPI), the MCP reference
  time server. Tested 2026-10-29.
- Reproduction: clean venv, `pip install mcp-server-time`, run over stdio
  via probe.py. Initialize answered in 1.00 s; two tools listed
  (get_current_time, convert_time), results carry structuredContent.
- Task: (a) current time in America/New_York; (b) convert 2026-10-29 09:00
  America/New_York to Europe/London.
- Expected (ground truth, system `date` with TZ conversions in the same
  session): (a) 2026-10-29T17:04:31-04:00, Thursday, DST on; (b) 13:00
  +00:00, a +4.0h difference — the asymmetric fall-back week (London left
  DST on Oct 25, the US not until Nov 1), where the gap is 4 hours, not
  the usual 5.
- Observed: both answers exact, including +4.0h and is_dst false for
  London. Transcript excerpt:

```json
== tools/call convert_time ==
"target": {"timezone": "Europe/London", "datetime": "2026-10-29T13:00:00+00:00",
           "day_of_week": "Thursday", "is_dst": false},
"time_difference": "+4.0h"
```

- Verdict: Works. No caveats recorded.
- Evidence refs: record 002 in the Receipts index; write-up
  tests/002-mcp-server-time.md; transcript tests/002-time-transcript.txt.

## Case 2 — WORKS WITH CAVEATS: @modelcontextprotocol/server-redis (#056)

- Package: @modelcontextprotocol/server-redis, version 2025.4.25 (npm),
  run exactly as its README instructs:
  `npx -y @modelcontextprotocol/server-redis <redis-url>`. Tested
  2026-10-31. No real Redis and no real credentials: decoy URL plus a
  sandboxed fake-RESP server as the positive control.
- Task: `set` then `get` the key "receipts-test".
- Expected (ground truth): the raw node-redis driver against the same
  decoy URLs, and the fake-RESP round-trip. The driver fails fast (0.03 s)
  on the unreachable host and its errors contain NO password.
- Observed: the round-trip itself works — initialize 1.80 s against the
  control, `set` returns "Successfully set key: receipts-test", `get`
  returns "hello", 0.10 s per call. BUT the server logs the full
  connection URL, password in clear text, to stderr on every connect,
  error, retry, and success — the decoy password appears 40+ times across
  one test session (19 times in the wrong-password run alone), including
  on the happy path:

```text
[Redis Connected] Successfully connected to redis://decoyuser:<decoy-password>@127.0.0.1:6399
```

  Further caveats: it connects before the MCP handshake, so an unreachable
  server means initialize is never answered (~35–60 s of retries, then
  exit); it logs "Successfully connected" on a bare TCP accept, before
  AUTH; a wrong password is retried identically 5 times over ~34 s.
- Verdict: Works With Caveats. The function works; the logging behavior is
  a credential spill with any real password, and it is caveat #1.
- Evidence refs: record 056; write-up tests/056-redis.md; transcript
  tests/056-redis-transcript.txt (sections A–C: no-arg, decoy URL,
  wrong-password control, driver ground truth).

## Case 3 — BROKEN: open-meteo-mcp (Receipts #009)

- Package: open-meteo-mcp, version 0.2.0 (PyPI), run as its README
  instructs: `python -m open_meteo_mcp`. Tested 2026-10-29, clean venvs.
- Task: current weather for New York City.
- Expected (ground truth): the Open-Meteo API fetched directly in the
  same minute (21:37–21:38 UTC), with tolerances set before grading:
  temperature ±1.5 °C, wind ±5 km/h, humidity ±5, pressure ±1.5 hPa,
  weather code exact.
- Observed: as installed per its README the server never answers
  initialize — it crashes at import:

```text
ImportError: cannot import name 'McpError' from 'mcp' … Did you mean: 'MCPError'?
```

  Pinning the SDK to the package's own declared floor (mcp==1.12.0) fails
  one import later inside FastMCP against today's pydantic; only TWO
  undocumented pins (mcp==1.12.0 AND pydantic==2.11.7) make it start.
  Cause: open-ended dependency ranges met two fatal upstream renames
  after 0.2.0 shipped. Even then, its "current" weather text reproduces
  the NEXT hour's forecast bucket digit-for-digit (gusts off by 7.6 km/h
  vs the API's actual current block, outside tolerance), and its two
  weather tools disagree with each other in the same minute.
- Verdict: Broken — a user installing this package today gets a
  traceback, not a weather server.
- Evidence refs: record 009; write-up tests/009-weather-server.md;
  transcripts tests/009-weather-transcript.txt (failed probe + both
  tracebacks) and tests/009-weather-transcript-pinned.txt.

---

## What this pack is for
Publication: Mart/Atrium can lift each case verbatim into a stable page
under thelanternworks.com/receipts (house label stays on the Receipts
index itself; these three are third-party servers). Machine-readable
refs for agents: receipts-proof-pack-2026-11-06.json (companion file,
same handoff) — record id, package, version, verdict, tested date,
ground-truth summary, and evidence file names per case. Receipts-intent
referrals from these pages should be tagged separately from GPU demand
per T125 (suggested ref: ref=receipts-proofpack).
