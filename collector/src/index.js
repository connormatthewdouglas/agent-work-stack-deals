// Lantern Works MCP telemetry collector (Cloudflare Worker, free plan, D1).
// Stores ONLY aggregate counts per (day, tool, version). Never stores IPs, headers or IDs.
// POST /v1/events  {"events":[{"t":tool,"v":version,"d":"YYYY-MM-DD","n":count}, ...]}
// GET  /v1/stats?days=30  -> read-only aggregates
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
    if (url.pathname === "/") return json({ service: "lantern-works-mcp-telemetry", endpoints: ["POST /v1/events", "GET /v1/stats?days=30"] });
    return json({ error: "not found" }, 404);
  },
};
