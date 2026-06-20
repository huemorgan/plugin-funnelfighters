# plugin-funnelfighters

Marketing intelligence for [Luna](https://github.com/huemorgan/luna), powered by
the **FunnelFighters** API and the **4 Ducks** funnel-analysis methodology.

Ships **installed but OFF** — enable it in *Settings → Plugins*, then paste your
API key + organization ID in the *FunnelFighters* tab (a themed iframe served
from the plugin's managed dir).

## What you get

- **15 read-only tools** — campaigns, ads, keywords, landing pages, funnels,
  visitors, cohorts, ROI, wasted spend, portfolio/home summaries, and the 4 Ducks
  analyze/reports endpoints.
- **`four-ducks` skill** — the agent loads it on demand before analyzing ads,
  funnels, or campaign performance.

## How it connects

API-key connector. Credentials are verified against `/api/home/summary`, stored in
Luna's vault (`ctx.vault`), and used to build a live `FFClient` immediately — no
server restart. Authed routes use `luna_sdk.get_current_user`.

## Built on `luna_sdk` v0

No `import luna.*` anywhere — only `luna_sdk`, the standard library, and `httpx`.
The live client is held in a module-level singleton (`state.py`) so connect /
disconnect work identically from a managed dir.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT © 2026 Hue Morgan
