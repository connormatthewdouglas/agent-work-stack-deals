// Lantern Works MCP telemetry collector (Cloudflare Worker, free plan, D1).
// Stores aggregate counts per (day, tool, version) and, when a valid UUID install_id is present,
// install rows per (day, install_id, ref, tool, version). Never stores IPs, headers, names or hostnames.
// Public /v1/stats returns aggregates only (no raw install ids).
// POST /v1/events  {"install_id":"<uuid>","ref":"<tag>","events":[{"t":tool,"v":version,"d":"YYYY-MM-DD","n":count}, ...]}
// GET  /v1/stats?days=30  -> read-only aggregates, including installs.distinct / returning / by_ref / by_week
// GET  /go/<deal-id>?src=site|mcp|feed|readme[-test]&ref=<tag>  -> 302 to that deal's stored redeem_url (looked up in the
//      served feed; never a caller-supplied URL, so not an open redirect). Counts one click per (day, deal, provider, src, ref).
// GET  /go/v/<vendor-slug>?src=... -> same, for a provider with no feed deal (T136; target from the served GPU feed only)
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

export const REF_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;
export const INSTALL_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const ALLOWED_BODY = new Set(["events", "install_id", "ref"]);

export function validate(body, now = new Date()) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return "body must be an object";
  const keys = Object.keys(body);
  if (!keys.includes("events") || keys.some((k) => !ALLOWED_BODY.has(k))) return "only events, install_id, ref allowed";
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

// Valid UUID install_id is kept (lowercased). Anything else is ignored, not rejected, so tool counts still land.
export function installMeta(body) {
  const rawId = typeof body.install_id === "string" ? body.install_id.trim() : "";
  const id = rawId.length <= 36 && INSTALL_ID_RE.test(rawId) ? rawId.toLowerCase() : null;
  const raw = typeof body.ref === "string" ? body.ref.trim().toLowerCase() : "";
  const ref = REF_RE.test(raw) ? raw : (raw ? "other" : "none");
  return { id, ref };
}

// ISO week YYYY-Www, matching Python date.isocalendar() (UTC day).
export function isoWeek(day) {
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const year = d.getUTCFullYear();
  const yearStart = new Date(Date.UTC(year, 0, 1));
  const week = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
  return `${year}-W${String(week).padStart(2, "0")}`;
}

// Public aggregates only: never include raw install_id. Returning = seen on 2+ distinct UTC days in the window.
// Test rows (version 0.0.0) are excluded. by_ref counts distinct ids per ref.
export function aggregateInstalls(rows) {
  const days = new Map(); // id -> Set(day)
  const refs = new Map(); // id -> Set(ref)
  for (const r of rows || []) {
    if (!r || r.version === "0.0.0" || !r.install_id || !r.day) continue;
    if (!days.has(r.install_id)) { days.set(r.install_id, new Set()); refs.set(r.install_id, new Set()); }
    days.get(r.install_id).add(r.day);
    refs.get(r.install_id).add(r.ref || "none");
  }
  const returningIds = new Set([...days.entries()].filter(([, s]) => s.size >= 2).map(([id]) => id));
  const byRef = {};
  for (const [id, rs] of refs) for (const ref of rs) byRef[ref] = (byRef[ref] || 0) + 1;
  const byWeekMap = new Map();
  for (const [id, ds] of days) {
    const weeks = new Set([...ds].map(isoWeek).filter(Boolean));
    for (const w of weeks) {
      if (!byWeekMap.has(w)) byWeekMap.set(w, { ids: new Set(), returning: new Set(), byRef: {} });
      const slot = byWeekMap.get(w);
      slot.ids.add(id);
      if (returningIds.has(id)) slot.returning.add(id);
      for (const ref of refs.get(id)) slot.byRef[ref] = (slot.byRef[ref] || 0) + 1;
    }
  }
  const by_week = [...byWeekMap.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([week, s]) => ({
    week, distinct: s.ids.size, returning: s.returning.size,
    by_ref: Object.fromEntries(Object.entries(s.byRef).sort((a, b) => a[0].localeCompare(b[0]))),
  }));
  return {
    distinct: days.size,
    returning: returningIds.size,
    by_ref: Object.fromEntries(Object.entries(byRef).sort((a, b) => a[0].localeCompare(b[0]))),
    by_week,
    note: "returning = install id seen on 2+ distinct UTC days in this stats window; weekly returning counts ids seen that ISO week that meet the 2+ day definition (the other day may fall outside the week). Aggregates only; raw install ids are not published. version 0.0.0 excluded.",
  };
}

export const FEED_URL = "https://thelanternworks.com/api/v1/deals.json";
export const SRCS = new Set(["site", "mcp", "feed", "readme"].flatMap((x) => [x, x + "-test"]));
const ID_RE = /^[a-z0-9][a-z0-9-]{0,79}$/;
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

// T136: vendor-level links for providers with no feed deal. /go/v/<vendor-slug> resolves the slug ONLY from the served
// feeds: a disclosed referral_url on a GPU rate, else that vendor's checked source_url, else the redeem_url of the vendor's
// only deal. Never a caller-supplied URL, so not an open redirect.
export const GPU_FEED_URL = "https://thelanternworks.com/api/v1/gpu-prices.json";
export const vendorSlug = (name) => String(name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,59}$/;
let vendorCache = { at: 0, bySlug: null };
const https = (u) => typeof u === "string" && /^https:\/\//.test(u);

export async function vendorMap(fetchFn = fetch, now = Date.now()) {
  if (vendorCache.bySlug && now - vendorCache.at < 300_000) return vendorCache.bySlug;
  const bySlug = new Map(), ref = new Map(), src = new Map(), deals = new Map();
  const r = await fetchFn(GPU_FEED_URL, { cf: { cacheTtl: 300 } });
  if (!r.ok) { if (vendorCache.bySlug) return vendorCache.bySlug; throw new Error("gpu feed " + r.status); }
  const g = await r.json();
  for (const x of g.rates || []) {
    const s = vendorSlug(x && x.advertiser); if (!s) continue;
    if (https(x.referral_url) && !ref.has(s)) ref.set(s, { url: x.referral_url, provider: x.advertiser });
    if (https(x.source_url) && !src.has(s)) src.set(s, { url: x.source_url, provider: x.advertiser });
  }
  for (const v of g.vendors || []) {
    const s = vendorSlug(v && v.vendor);
    if (s && https(v.source_url) && !src.has(s)) src.set(s, { url: v.source_url, provider: v.vendor });
  }
  try {
    for (const [, d] of await dealMap(fetchFn, now)) {
      const s = vendorSlug(d.provider); if (s) deals.set(s, deals.has(s) ? null : d);
    }
  } catch {}
  for (const [s, d] of deals) if (d) bySlug.set(s, d);
  for (const [s, d] of src) bySlug.set(s, d);
  for (const [s, d] of ref) bySlug.set(s, d);  // a disclosed referral link wins
  vendorCache = { at: now, bySlug };
  return bySlug;
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
      const { id, ref } = installMeta(body);
      if (id) {
        try {
          const inst = env.DB.prepare(
            "INSERT INTO installs (day, install_id, ref, tool, version, n) VALUES (?1, ?2, ?3, ?4, ?5, ?6) ON CONFLICT(day, install_id, ref, tool, version) DO UPDATE SET n = n + excluded.n");
          await env.DB.batch(body.events.map((e) => inst.bind(e.d, id, ref, e.t, e.v, e.n)));
        } catch {}  // ignore if the installs table is not migrated yet; counts already saved
      }
      return new Response(null, { status: 204 });
    }
    if (url.pathname === "/v1/stats" && request.method === "GET") {
      const days = Math.min(Math.max(parseInt(url.searchParams.get("days") || "30", 10) || 30, 1), 365);
      const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
      const { results } = await env.DB.prepare(
        "SELECT day, tool, version, n FROM counts WHERE day >= ?1 ORDER BY day, tool, version").bind(since).all();
      const total = results.reduce((s, r) => s + r.n, 0);
      let installs = { distinct: 0, returning: 0, by_ref: {}, by_week: [],
        note: "returning = install id seen on 2+ distinct UTC days in this stats window; weekly returning counts ids seen that ISO week that meet the 2+ day definition (the other day may fall outside the week). Aggregates only; raw install ids are not published. version 0.0.0 excluded." };
      try {
        const inst = await env.DB.prepare(
          "SELECT day, install_id, ref, version FROM installs WHERE day >= ?1").bind(since).all();
        installs = aggregateInstalls(inst.results || []);
      } catch {}
      return json({ since, total_calls: total, rows: results, installs,
        note: "Opt-in (LANTERN_TELEMETRY=1) aggregate tool-call counts. No IPs are stored. installs are aggregates only (no raw install ids)." });
    }
    if (url.pathname.startsWith("/go/") && (request.method === "GET" || request.method === "HEAD")) {
      let id = url.pathname.slice(4).replace(/\/$/, "").toLowerCase(), deal;
      if (id.startsWith("v/")) {  // T136: vendor-level link, counted as deal_id "v:<slug>"
        const slug = id.slice(2);
        if (!SLUG_RE.test(slug)) return json({ error: "bad vendor" }, 400);
        let bySlug;
        try { bySlug = await vendorMap(); } catch { return json({ error: "feed unavailable" }, 503); }
        deal = bySlug.get(slug);
        if (!deal) return json({ error: "unknown vendor" }, 404);
        id = "v:" + slug;
      } else {
        if (!ID_RE.test(id)) return json({ error: "bad deal id" }, 400);
        let byId;
        try { byId = await dealMap(); } catch { return json({ error: "feed unavailable" }, 503); }
        deal = byId.get(id);
        if (!deal) return json({ error: "unknown deal id" }, 404);
      }
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
