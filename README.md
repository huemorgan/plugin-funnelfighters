# plugin-funnelfighters

Marketing intelligence for [Luna](https://github.com/huemorgan/luna), powered by
the **FunnelFighters** API and the **4 Ducks** funnel-analysis methodology.

Ships **installed but OFF** — enable it in *Settings → Plugins*, then add your
API key + organization ID pairs in the *FunnelFighters* tab (a themed iframe
served from the plugin's managed dir).

## What you get

- **Multiple workspaces** — connect several API key + org ID pairs; each
  connection is named after its FunnelFighters workspace (fetched right after a
  successful connect). The Settings tab lists all connections and lets you
  remove them; the agent can add/remove them too.
- **15 read-only data tools** — campaigns, ads, keywords, landing pages, funnels,
  visitors, cohorts, ROI, wasted spend, portfolio/home summaries, and the 4 Ducks
  analyze/reports endpoints. Each takes an optional `workspace` (name or id) —
  omit it when only one workspace is connected.
- **3 management tools** — `ff_workspaces` (list), `ff_connect` (add a key + org
  pair; approval-gated), `ff_disconnect` (remove; approval-gated).
- **`four-ducks` skill** — the agent loads it on demand before analyzing ads,
  funnels, or campaign performance.

## How it connects

API-key connector. Each pair is verified against `/api/home/summary`, the
workspace name is copied from FunnelFighters, and all connections persist as one
JSON vault credential (`funnelfighters_workspaces`). A pre-0.4 single connection
migrates into the list automatically on load; a gateway/env-provisioned pair
(`LUNA_FUNNELFIGHTERS_API_KEY`/`_ORG_ID`) appears as a non-removable
"provisioned" connection. Live clients rebuild immediately — no server restart.
Authed routes use `luna_sdk.get_current_user`.

## Built on `luna_sdk` v0

No `import luna.*` anywhere — only `luna_sdk`, the standard library, and `httpx`.
Live connections are held in a module-level registry (`state.py`) so connect /
disconnect work identically from a managed dir.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT © 2026 Hue Morgan
