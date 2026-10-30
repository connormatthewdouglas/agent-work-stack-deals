// re20 P2: $0 trigger independent of GitHub's cron. Every 10 min, dispatch the gated scout-import workflow.
// Needs Worker secret GH_DISPATCH_TOKEN: a fine-grained token for connormatthewdouglas/agent-work-stack-deals only,
// permission Actions: read and write, nothing else. The token is never logged.
const URL = "https://api.github.com/repos/connormatthewdouglas/agent-work-stack-deals/actions/workflows/scout-import.yml/dispatches";
async function dispatch(env) {
  if (!env.GH_DISPATCH_TOKEN) { console.log("scout-import dispatch skipped: GH_DISPATCH_TOKEN not set"); return 0; }
  const r = await fetch(URL, { method: "POST", headers: {
    "authorization": `Bearer ${env.GH_DISPATCH_TOKEN}`, "accept": "application/vnd.github+json",
    "user-agent": "lantern-works-import-cron", "x-github-api-version": "2022-11-28" }, body: JSON.stringify({ ref: "main", inputs: { gated: "true" } }) });
  console.log(`scout-import dispatch: HTTP ${r.status}`);
  return r.status;
}
export default {
  async scheduled(_e, env, ctx) { ctx.waitUntil(dispatch(env)); },
  async fetch() { return new Response("lantern-works import cron (no public actions)\n", { status: 200 }); },
};
