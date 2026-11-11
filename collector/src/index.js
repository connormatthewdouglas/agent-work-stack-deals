// Lantern Works MCP telemetry collector (Cloudflare Worker, free plan, D1).
// Stores ONLY aggregate counts per (day, tool, version). Never stores IPs, headers or IDs.
// POST /v1/events  {"events":[{"t":tool,"v":version,"d":"YYYY-MM-DD","n":count}, ...]}
// GET  /v1/stats?days=30  -> read-only aggregates
// GET  /go/<deal-id>?src=site|mcp|feed|readme[-test]&ref=<tag>  -> 302 to that deal's stored redeem_url (looked up in the
//      served feed; never a caller-supplied URL, so not an open redirect). Counts one click per (day, deal, provider, src, ref).
// GET  /v1/clicks?days=30 -> read-only click aggregates
// T135: each click also gets a coarse ua_class (browser|bot|script|prefetch|other) worked out from the User-Agent and
// prefetch headers at request time; the User-Agent itself is never stored. Rows recorded before this have ua_class
// "unclassified" (legacy clicks table).
export const TOOLS = new Set(["search_deals", "compare_deals", "get_deal", "compare_gpu_prices", "optimize_stack", "optimize_agent_stack"]);
export const MAX_BODY = 4096, MAX_EVENTS = 50, MAX_N = 10000, MAX_AGE_DAYS = 8;
const VERSION_RE = /^\d{1,3}\.\d{1,3}\.\d{1,3}$/;
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

// Best-effort per-isolate limiter (in memory, never persisted). Key is a short hash, not the IP.
const buckets = new Map();
export function allow(key, now = Date.now(), limit = 30, windowMs = 60_000) {
  const b = buckets.get(key);
  if (!b || now - b.start > windowMs) { buckets.set(key, { start: now, count: 1 }); if (buckets.size > 10000) buckets.clear(); return true; }
  b.count += 1;
  return b.count <= limit;
}

async function rateKey(request) {
  const ip = request.headers.get("cf-connecting-ip") || "";
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ip));
  return [...new Uint8Array(h).slice(0, 6)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

function dayDiff(day, now) {
  const t = Date.parse(day + "T00:00:00Z");
  return Number.isNaN(t) ? Infinity : Math.round((Date.parse(now.toISOString().slice(0, 10) + "T00:00:00Z") - t) / 86400000);
}

export function validate(body, now = new Date()) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return "body must be an object";
  const keys = Object.keys(body);
  if (keys.length !== 1 || keys[0] !== "events") return "only 'events' allowed";
  const ev = body.events;
  if (!Array.isArray(ev) || ev.length === 0 || ev.length > MAX_EVENTS) return `events must be 1-${MAX_EVENTS} items`;
  for (const e of ev) {
    if (!e || typeof e !== "object" || Array.isArray(e)) return "event must be an object";
    const k = Object.keys(e).sort().join(",");
    if (k !== "d,n,t,v") return "event fields must be exactly t, v, d, n";
    if (!TOOLS.has(e.t)) return "unknown tool";
    if (typeof e.v !== "string" || !VERSION_RE.test(e.v)) return "bad version";
    if (typeof e.d !== "string" || !DAY_RE.test(e.d)) return "bad day";
    const age = dayDiff(e.d, now);
    if (age < -1 || age > MAX_AGE_DAYS) return "day out of range";
    if (!Number.isInteger(e.n) || e.n < 1 || e.n > MAX_N) return "bad count";
  }
  return null;
}

export const FEED_URL = "https://thelanternworks.com/api/v1/deals.json";
export const SRCS = new Set(["site", "mcp", "feed", "readme"].flatMap((x) => [x, x + "-test"]));
const ID_RE = /^[a-z0-9][a-z0-9-]{0,79}$/;
const REF_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;
let feedCache = { at: 0, byId: null };

// Known crawlers, link-preview fetchers, monitors and headless browsers (never a person clicking).
const BOT_RE = /bot\b|bot\/|crawl|spider|slurp|preview|facebookexternalhit|embedly|whatsapp|telegram|discord|skype|monitor|uptime|pingdom|scan|archiver|validator|lighthouse|headless|phantomjs|puppeteer|playwright|bingpreview|ahrefs|semrush|mj12|yandex|baidu|petal|bytespider|gptbot|claudebot|perplexity|ccbot|amazonbot|applebot|duckduck|feedfetcher|feedly|inoreader|rss/i;
// HTTP libraries and CLIs: a script fetching the link, not a click.
const SCRIPT_RE = /^(curl|wget|python|httpx|aiohttp|go-http-client|node|undici|axios|okhttp|java|libwww|ruby|php|guzzle|postman|insomnia|deno|bun|rust|reqwest)|python-requests|node-fetch|got \(/i;
const BROWSER_RE = /mozilla\/5\.0 .*(chrome|firefox|safari|edg)\//i;

export function uaClass(ua, headers) {
  const h = headers || new Headers();
  const purpose = (h.get("sec-purpose") || h.get("purpose") || h.get("x-moz") || "").toLowerCase();
  if (purpose.includes("prefetch") || purpose.includes("prerender")) return "prefetch";
  ua = (ua || "").trim();
  if (!ua) return "script";
  if (BOT_RE.test(ua)) return "bot";
  if (SCRIPT_RE.test(ua)) return "script";
  if (BROWSER_RE.test(ua)) return "browser";
  return "other";
}

export async function dealMap(fetchFn = fetch, now = Date.now()) {
  if (feedCache.byId && now - feedCache.at < 300_000) return feedCache.byId;
  const r = await fetchFn(FEED_URL, { cf: { cacheTtl: 300 } });
  if (!r.ok) { if (feedCache.byId) return feedCache.byId; throw new Error("feed " + r.status); }
  const byId = new Map();
  for (const d of (await r.json()).deals || []) {
    if (d && d.id && !d.example && /^https:\/\//.test(d.redeem_url || "")) byId.set(d.id, { url: d.redeem_url, provider: d.advertiser || "" });
  }
  feedCache = { at: now, byId };
  return byId;
}

export function clickParams(url) {
  const src = (url.searchParams.get("src") || "").toLowerCase();
  const ref = (url.searchParams.get("ref") || "").toLowerCase();
  return { src: SRCS.has(src) ? src : (src ? "other" : "none"), ref: REF_RE.test(ref) ? ref : (ref ? "other" : "none") };
}

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { "content-type": "application/json", "access-control-allow-origin": "*", "cache-control": "no-store" } });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/v1/events") {
      if (request.method !== "POST") return json({ error: "method not allowed" }, 405);
      const key = await rateKey(request);
      if (env.RATE_LIMITER) {
        const { success } = await env.RATE_LIMITER.limit({ key });
        if (!success) return json({ error: "rate limited" }, 429);
      } else if (!allow(key)) return json({ error: "rate limited" }, 429);
      const text = await request.text();
      if (text.length > MAX_BODY) return json({ error: "too large" }, 413);
      let body;
      try { body = JSON.parse(text); } catch { return json({ error: "invalid json" }, 400); }
      const err = validate(body);
      if (err) return json({ error: err }, 400);
      const stmt = env.DB.prepare(
        "INSERT INTO counts (day, tool, version, n) VALUES (?1, ?2, ?3, ?4) ON CONFLICT(day, tool, version) DO UPDATE SET n = n + excluded.n");
      await env.DB.batch(body.events.map((e) => stmt.bind(e.d, e.t, e.v, e.n)));
      return new Response(null, { status: 204 });
    }
    if (url.pathname === "/v1/stats" && request.method === "GET") {
      const days = Math.min(Math.max(parseInt(url.searchParams.get("days") || "30", 10) || 30, 1), 365);
      const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
      const { results } = await env.DB.prepare(
        "SELECT day, tool, version, n FROM counts WHERE day >= ?1 ORDER BY day, tool, version").bind(since).all();
      const total = results.reduce((s, r) => s + r.n, 0);
      return json({ since, total_calls: total, rows: results,
        note: "Opt-in (LANTERN_TELEMETRY=1) aggregate tool-call counts. No IPs or IDs are stored." });
    }
    if (url.pathname.startsWith("/go/") && (request.method === "GET" || request.method === "HEAD")) {
      const id = url.pathname.slice(4).replace(/\/$/, "").toLowerCase();
      if (!ID_RE.test(id)) return json({ error: "bad deal id" }, 400);
      let byId;
      try { byId = await dealMap(); } catch { return json({ error: "feed unavailable" }, 503); }
      const deal = byId.get(id);
      if (!deal) return json({ error: "unknown deal id" }, 404);
      const { src, ref } = clickParams(url);
      let target = deal.url;
      if (src.startsWith("site")) {  // keep the site's existing T51 utm_source tag
        try { const t = new URL(target); if (!t.searchParams.has("utm_source")) t.searchParams.set("utm_source", "lanternworks"); target = t.href; } catch {}
      }
      const day = new Date().toISOString().slice(0, 10);
      const uac = uaClass(request.headers.get("user-agent"), request.headers);
      if (request.method === "GET") try {
        await env.DB.prepare("INSERT INTO go_clicks (day, deal_id, provider, src, ref, ua_class, n) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 1) " +
          "ON CONFLICT(day, deal_id, provider, src, ref, ua_class) DO UPDATE SET n = n + 1").bind(day, id, deal.provider, src, ref, uac).run();
      } catch {
        try {  // go_clicks not created yet (schema not applied): keep counting in the legacy table
          await env.DB.prepare("INSERT INTO clicks (day, deal_id, provider, src, ref, n) VALUES (?1, ?2, ?3, ?4, ?5, 1) " +
            "ON CONFLICT(day, deal_id, provider, src, ref) DO UPDATE SET n = n + 1").bind(day, id, deal.provider, src, ref).run();
        } catch {}  // never block the redirect on a counter failure
      }
      return new Response(null, { status: 302, headers: { location: target, "cache-control": "no-store", "referrer-policy": "no-referrer-when-downgrade" } });
    }
    if (url.pathname === "/v1/clicks" && request.method === "GET") {
      const days = Math.min(Math.max(parseInt(url.searchParams.get("days") || "30", 10) || 30, 1), 365);
      const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
      const rows = [];
      try {
        const { results } = await env.DB.prepare(
          "SELECT day, deal_id, provider, src, ref, n FROM clicks WHERE day >= ?1 ORDER BY day, provider, src").bind(since).all();
        for (const r of results || []) rows.push({ ...r, ua_class: "unclassified" });
      } catch {}
      try {
        const { results } = await env.DB.prepare(
          "SELECT day, deal_id, provider, src, ref, ua_class, n FROM go_clicks WHERE day >= ?1 ORDER BY day, provider, src").bind(since).all();
        rows.push(...(results || []));
      } catch {}
      return json({ since, rows, note: "Aggregate /go/ redirect clicks per UTC day x deal x provider x src x ref x ua_class. No IPs, " +
        "user agents, cookies or IDs. src ending -test is our own test traffic. ua_class: browser|other = counted; bot|script|prefetch " +
        "= automated fetches; unclassified = recorded before the UA filter." });
    }
    if (url.pathname === "/") return json({ service: "lantern-works-mcp-telemetry", endpoints: ["POST /v1/events", "GET /v1/stats?days=30", "GET /go/<deal-id>?src=", "GET /v1/clicks?days=30"] });
    return json({ error: "not found" }, 404);
  },
};
