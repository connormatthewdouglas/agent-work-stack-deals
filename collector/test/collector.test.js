import test from "node:test";
import assert from "node:assert/strict";
import worker, { validate, allow } from "../src/index.js";

const today = new Date().toISOString().slice(0, 10);
const ok = { events: [{ t: "search_deals", v: "0.3.3", d: today, n: 3 }] };

function fakeDB() {
  const rows = new Map();
  return {
    rows,
    prepare(sql) {
      const all = async () => ({ results: [...rows.entries()].map(([k, n]) => { const [day, tool, version] = k.split("|"); return { day, tool, version, n }; }) });
      return { bind: (...a) => ({ sql, a, all }), all };
    },
    async batch(stmts) { for (const { a: [d, t, v, n] } of stmts) { const k = `${d}|${t}|${v}`; rows.set(k, (rows.get(k) || 0) + n); } },
  };
}
const req = (body, ip = "203.0.113.9") => new Request("https://x/v1/events", {
  method: "POST", body: typeof body === "string" ? body : JSON.stringify(body), headers: { "cf-connecting-ip": ip } });

test("validate accepts minimal payload", () => assert.equal(validate(ok), null));
test("validate rejects extra fields, ids, bad tools/versions/days/counts", () => {
  assert.ok(validate({ events: ok.events, install_id: "x" }));
  assert.ok(validate({ events: [{ ...ok.events[0], ip: "1.2.3.4" }] }));
  assert.ok(validate({ events: [{ ...ok.events[0], t: "rm_rf" }] }));
  assert.ok(validate({ events: [{ ...ok.events[0], v: "latest" }] }));
  assert.ok(validate({ events: [{ ...ok.events[0], d: "2001-01-01" }] }));
  assert.ok(validate({ events: [{ ...ok.events[0], n: 0 }] }));
  assert.ok(validate({ events: [{ ...ok.events[0], n: 1.5 }] }));
  assert.ok(validate({ events: Array(51).fill(ok.events[0]) }));
  assert.ok(validate({ events: [] }));
});
test("POST aggregates counts; stores no IP", async () => {
  const env = { DB: fakeDB() };
  assert.equal((await worker.fetch(req(ok), env)).status, 204);
  assert.equal((await worker.fetch(req(ok), env)).status, 204);
  assert.deepEqual([...env.DB.rows], [[`${today}|search_deals|0.3.3`, 6]]);
  assert.ok(![...env.DB.rows.keys()].join().includes("203.0.113.9"));
});
test("rejects bad json, oversize, wrong method", async () => {
  const env = { DB: fakeDB() };
  assert.equal((await worker.fetch(req("{nope", "198.51.100.1"), env)).status, 400);
  assert.equal((await worker.fetch(req("x".repeat(5000), "198.51.100.2"), env)).status, 413);
  assert.equal((await worker.fetch(new Request("https://x/v1/events"), env)).status, 405);
});
test("rate limit (in-memory fallback)", () => {
  let last = true;
  for (let i = 0; i < 31; i++) last = allow("k-test", 1000);
  assert.equal(last, false);
});
test("rate limit binding honored", async () => {
  const env = { DB: fakeDB(), RATE_LIMITER: { limit: async () => ({ success: false }) } };
  assert.equal((await worker.fetch(req(ok), env)).status, 429);
});
test("stats endpoint is read-only aggregate", async () => {
  const env = { DB: fakeDB() };
  await worker.fetch(req(ok, "192.0.2.5"), env);
  const r = await (await worker.fetch(new Request("https://x/v1/stats?days=7"), env)).json();
  assert.equal(r.total_calls, 3);
  assert.deepEqual(Object.keys(r.rows[0]).sort(), ["day", "n", "tool", "version"]);
});
