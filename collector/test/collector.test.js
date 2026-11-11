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

test("/go/ redirects only to the feed's stored redeem_url and counts the click", async () => {
  const { dealMap, clickParams } = await import("../src/index.js");
  const feed = { deals: [{ id: "deal-x", advertiser: "X", redeem_url: "https://x.example/r?a=1" }] };
  const realFetch = globalThis.fetch; globalThis.fetch = async () => new Response(JSON.stringify(feed));
  const m = await dealMap(fetch, Date.now());
  assert.equal(m.get("deal-x").url, "https://x.example/r?a=1");
  const calls = [];
  const env = { DB: { prepare: (sql) => ({ bind: (...a) => ({ run: async () => calls.push(a) }) }) } };
  const r = await worker.fetch(new Request("https://w/go/deal-x?src=feed-test&ref=qa&to=https://evil.example"), env);
  assert.equal(r.status, 302);
  assert.equal(r.headers.get("location"), "https://x.example/r?a=1");
  assert.deepEqual(calls[0].slice(1, 5), ["deal-x", "X", "feed-test", "qa"]);
  assert.equal((await worker.fetch(new Request("https://w/go/nope"), env)).status, 404);
  assert.deepEqual(clickParams(new URL("https://w/go/a?src=EVIL")), { src: "other", ref: "none" });
  globalThis.fetch = realFetch;
});

test("T135: uaClass splits browsers from bots, scripts and prefetch; UA never stored", async () => {
  const { uaClass } = await import("../src/index.js");
  const chrome = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
  assert.equal(uaClass(chrome), "browser");
  assert.equal(uaClass("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"), "bot");
  assert.equal(uaClass("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2)"), "bot");
  assert.equal(uaClass("facebookexternalhit/1.1"), "bot");
  assert.equal(uaClass("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/120.0 Safari/537.36"), "bot");
  assert.equal(uaClass("curl/8.5.0"), "script");
  assert.equal(uaClass("python-requests/2.32"), "script");
  assert.equal(uaClass(""), "script");
  assert.equal(uaClass(chrome, new Headers({ "sec-purpose": "prefetch;prerender" })), "prefetch");
  assert.equal(uaClass("SomeApp/1.0"), "other");
});

test("T135: /go/ records ua_class in go_clicks, falls back to legacy clicks, /v1/clicks merges both", async () => {
  const feed = { deals: [{ id: "deal-y", advertiser: "Y", redeem_url: "https://y.example/r" }] };
  const realFetch = globalThis.fetch; globalThis.fetch = async () => new Response(JSON.stringify(feed));
  const { dealMap } = await import("../src/index.js");
  await dealMap(fetch, Date.now() + 10 * 60_000);  // refresh the cache with deal-y
  const calls = [];
  const env = { DB: { prepare: (sql) => ({ bind: (...a) => ({ run: async () => calls.push([sql, a]), all: async () => ({
    results: sql.includes("go_clicks") ? [{ day: today, deal_id: "deal-y", provider: "Y", src: "mcp", ref: "none", ua_class: "browser", n: 1 }]
      : [{ day: today, deal_id: "deal-y", provider: "Y", src: "feed", ref: "none", n: 2 }] }) }) }) } };
  // Mart's post-deploy verification click, marked as house traffic (src *-test, ref house-*), sent with a browser UA
  const r = await worker.fetch(new Request("https://w/go/deal-y?src=mcp-test&ref=house-t135", {
    headers: { "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36" } }), env);
  assert.equal(r.status, 302);
  assert.match(calls[0][0], /INSERT INTO go_clicks/);
  assert.deepEqual(calls[0][1].slice(1), ["deal-y", "Y", "mcp-test", "house-t135", "browser"]);
  assert.ok(!JSON.stringify(calls).includes("Chrome/130"));  // the UA itself is never stored
  const legacy = [];
  const env2 = { DB: { prepare: (sql) => ({ bind: (...a) => ({ run: async () => { if (sql.includes("go_clicks")) throw new Error("no such table"); legacy.push(a); } }) }) } };
  assert.equal((await worker.fetch(new Request("https://w/go/deal-y?src=site"), env2)).status, 302);
  assert.equal(legacy.length, 1);
  const out = await (await worker.fetch(new Request("https://w/v1/clicks?days=7"), env)).json();
  assert.deepEqual(out.rows.map((x) => x.ua_class).sort(), ["browser", "unclassified"]);
  globalThis.fetch = realFetch;
});
