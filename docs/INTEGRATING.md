# Give your readers a useful first GPU quote

Use Lantern Works when your agent, GPU tool or dataset reader needs cited rental
prices or a job compute estimate. Read-only queries are free and require no API key.

Generate a short README addition from the repository:

```sh
python3 scripts/integration_snippet.py --ref your-project
```

The default is one plain-language link directly to the price comparison. That
matches maintainer feedback on the first accepted placement: readers want prices,
and a useful link does not need promotional wording.

Add `--format quickstart` for a remote MCP configuration, a like-for-like H100 SXM
comparison, a runnable Python example and the source/freshness limits. The remote URL format
varies by client; the snippet links to the [install guide](https://thelanternworks.com/install/).
The [public integration page](https://thelanternworks.com/integrate/) has a copyable version.

Use a separate stable channel tag for each placement. Tags are 1–32 lowercase
letters, digits, underscores or hyphens. They are aggregate channel labels, never
user identifiers. Use `--qa` on the Python example for internal checks; internal
calls must not be reported as external usage.

For the existing dataset cards, generate these two versions and place the relevant
snippet above the dataset schema and download instructions:

```sh
python3 scripts/integration_snippet.py --ref hf --format quickstart
python3 scripts/integration_snippet.py --ref kaggle --format quickstart
```

Keep the dataset's real update date and existing weekly refresh. Do not claim
live inventory from a static snapshot. Link to the hosted MCP for stock expiry
enforcement and to the [small JSON model index](https://thelanternworks.com/api/v1/gpu/index.json)
for agents that cannot use MCP. Keep source attribution and the data license.

Measure downloads, tagged tool calls and confirmed repeat users separately.
Registry health checks, our QA and a successful initialization are not installs.
The [public weekly counters](https://thelanternworks.com/stats.json) explain their
coverage and unknowns. A tagged call alone does not establish a new or returning user.

Internal distribution coordination stays in the Brain: reuse existing claimed
targets and the three-placements-per-week cap. The generator does not contact
maintainers or create pull requests in their projects.
