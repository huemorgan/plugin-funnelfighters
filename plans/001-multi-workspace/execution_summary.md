# 001 — Multi-workspace: execution summary

**Shipped 2026-07-10 as 0.4.0** — commit `4e056ae`, pushed to huemorgan/plugin-funnelfighters, published to marketplaces.com.ai `official` (index verified).

## What was built (matches plan; no deviations of substance)

- `connections.py` (new): `Connection` model, sha256-derived 8-char id, name-fetch chain (`/api/home/summary` nested org → `/api/organizations/{id}` → `/api/organizations` list → `org <id8>` placeholder), one-JSON-credential vault persistence (`funnelfighters_workspaces`), lazy placeholder-name refresh (once per connection per process), shared `verify_and_name`.
- `state.py`: singleton → id-keyed registry; `get_client(workspace)` resolves by id / case-insensitive name, defaults with one connection, errors listing names with several (messages double as agent guidance).
- `__init__.py`: 0.4.0; loads persisted list, migrates the pre-0.4 vault pair (kept for gateway slots), registers env-provisioned pair as a non-removable `source="env"` connection; boot name lookups capped at 8s.
- `tools.py`: `workspace` param on all 15 data tools; new `ff_workspaces` (auto-approve), `ff_connect` / `ff_disconnect` (prompt_always, medium risk, api_key sensitive).
- `routes.py`: `/connect` appends + returns the named workspace; `/disconnect` takes `{id}` (empty body = legacy remove-all); `/status` keeps old shape + `workspaces` list.
- Settings UI: connection list (name, org, source tag, since-date, Remove) + always-visible add form; testids kept, `ff-conn-row`/`ff-remove-btn` added.
- Versions bumped in all THREE stamps; `requires.tools` 15→18; conftest stub fixed (was missing `shown_name`/`icon`/`image` — baseline was red before this work).

## Verification

- Unit: 27/27 pass (registry resolution, persistence roundtrip excl. env, corrupt-JSON tolerance, legacy migration, env registration, name-chain incl. top-level-name trap, management tools, workspace threading).
- Real Luna (fresh DB, plugin in managed dir, stub FF API on :9777 with two orgs): connect copied names "Alpha Rockets"/"Beta Bakery"; bad pair → 400; remove by id; restart → both rebuilt from vault; settings UI 200. Agent: `ff_workspaces` listed both, `ff_campaigns(workspace="Beta Bakery")` routed to the right org, `ff_connect` created an approval request and connected after API approval.

## Notes

- FunnelFighters server source on Drive was dehydrated/unreadable; the name endpoint was confirmed by live probing (Express 401-vs-404): `/api/organizations` and `/api/organizations/:id` exist. Whether they accept bearer-key auth is still unconfirmed — the chain tolerates either answer, and the stub-verified primary path is the nested org in `/api/home/summary`.
- Same (key, org) pair re-connects idempotently (same id → replace). Same org via a different key creates a second connection with the same name; name-matching picks the first, id-matching is exact.
