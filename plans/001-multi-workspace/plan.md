# 001 — Multi-workspace connections

**Goal:** plugin-funnelfighters supports N workspace connections instead of one. The owner adds keys in Settings; the agent adds keys via a tool. Each connection is named after the FunnelFighters workspace/organization (fetched from the FF API right after a successful connect). Settings lists all connections and lets the owner manage (remove) them. Tools can target a specific workspace.

Version: 0.3.2 → **0.4.0** (all THREE stamps: `pyproject.toml`, `plugin_funnelfighters/luna-plugin.toml`, in-code `PluginManifest`).

## Current state (0.3.2)

- `state.py` — module singleton `_client: FFClient | None`.
- Credentials: two vault keys (`funnelfighters_api_key`, `funnelfighters_org_id`), or gateway env provisioning (`LUNA_FUNNELFIGHTERS_API_KEY` / `_ORG_ID` / `_BASE_URL` via CredentialSlots).
- `routes.py` — `POST /connect` (verify via `GET /api/home/summary`, store both vault keys), `POST /disconnect`, `GET /status`.
- 15 read-only tools built around one `ClientProvider`; `RuntimeError` → `_NOT_CONNECTED`.
- Settings iframe UI: single api-key/org-id form.

## Design

### Name source (verified by probing the live API)

The FF codebase on Drive is dehydrated (unreadable), but live probing of funnelfighters.io settles it: the server is Express; unauthenticated hits return 401 `{"error":"Authentication required"}` for routes that EXIST and `Cannot GET` 404 for routes that don't. Confirmed real: `GET /api/organizations`, `GET /api/organizations/:id`, `/api/auth/me`, `/api/api-keys`, `/api/settings`, `/api/home/*`. Not present: `/api/me`, `/api/workspaces`, `/api/orgs`.

Whether bearer-key auth is accepted on `/api/organizations` (vs session-only) is unknown without a key, so the name fetch is a tolerant chain after a successful verify:

1. Try `organization.name` / `organizationName` / `org_name` / `workspace.name` in the `/api/home/summary` response.
2. Fallback: `GET /api/organizations/{org_id}` → `name`.
3. Fallback: `GET /api/organizations` → find entry with matching id → `name`.
4. Last resort: name the connection `org <first-8-of-org-id>`.

(One helper `fetch_workspace_name(client, org_id) -> str` implements the chain; tolerant of shape drift.)

### Data model — one JSON vault credential

New vault credential `funnelfighters_workspaces` (kind `config`), value = JSON:

```json
[
  {"id": "a1b2c3d4", "name": "Acme Store", "api_key": "...", "org_id": "...", "connected_at": "2026-07-10T12:00:00Z"}
]
```

- `id` = first 8 hex of `sha256(api_key + ":" + org_id)` — stable, key-derived, no randomness needed.
- Slug-stem ACL: `funnelfighters_*` is self-owned, no grant needed.
- **Migration:** on load, if `funnelfighters_workspaces` is absent but the legacy pair (`funnelfighters_api_key` + `funnelfighters_org_id`) exists, build a one-entry list from it, fetch its name (best-effort; placeholder if FF unreachable at boot — re-fetched lazily on first successful call), store the JSON, keep the legacy keys (harmless; still what the gateway CredentialSlots point at).
- **Gateway/env connection:** if `LUNA_FUNNELFIGHTERS_API_KEY`+`_ORG_ID` are provisioned via env, register that as a connection too (marked `"source": "env"`, not persisted to vault, not removable from the UI list — shown with a "provisioned" tag).

### state.py — registry

```python
_connections: dict[str, Connection] = {}   # id -> Connection(meta + FFClient)
```

API: `set_connections(list)`, `get_connections()`, `get_client(workspace=None)`, `add_connection(conn)`, `remove_connection(id)`, `close_all()`.

`get_client(workspace)` resolution:
- 0 connections → `RuntimeError` (existing "not connected" path).
- `workspace` given → match by id or case-insensitive name; no match → `RuntimeError` listing available names.
- `workspace` omitted, exactly 1 connection → it.
- `workspace` omitted, >1 → `RuntimeError` telling the agent to pass `workspace=` and listing the names.

### tools.py

- All 15 tools get an optional `workspace` string param ("workspace name or id; required when several are connected"). `_safe_get/_safe_post` thread it into the provider; `RuntimeError` messages surface as `{"error": ...}` so the agent self-corrects.
- New tools:
  - `ff_workspaces` — list connections `{id, name, org_id, source, connected_at}` (no keys). `policy="auto_approve"`.
  - `ff_connect(api_key, org_id)` — verify, fetch name, persist, register. `policy="require_approval"` (writes credentials).
  - `ff_disconnect(workspace)` — remove by name/id. `policy="require_approval"`. Env-provisioned connection refuses removal.

### routes.py

- `GET /status` → back-compat fields (`connected`, `org_id` of first connection) **plus** `workspaces: [{id, name, org_id, source, connected_at}]`.
- `POST /connect` `{api_key, org_id}` → verify, fetch name, append (replace if same id), return the new entry. Kept at the same path so the old UI flow still works.
- `POST /disconnect` `{id}` → remove one; `{}` (legacy body) → remove all vault-backed connections (old semantics).
- Shared logic lives in `connections.py` (verify + name-fetch + persist), used by routes AND agent tools.

### Settings UI (`interface/webui/settings/index.html`)

- Connection list: one row per workspace — name, org id (truncated), source tag (`vault`/`provisioned`), connected date, Remove button (hidden for provisioned).
- Always-visible "Add workspace" form (api key + org id + Connect button). On success the new row appears with its fetched name.
- Empty state = today's disconnected card.
- Keep testids: `ff-api-key`, `ff-org-id`, `ff-connect-btn`; add `ff-conn-row`, `ff-remove-btn`.

### `__init__.py`

- `on_load`: register tools (15 + 3 new), skill, then `_connect_from_vault` → load `funnelfighters_workspaces` JSON (with legacy migration) + env-provisioned connection.
- `active` property: `len(get_connections()) > 0`.
- `on_unload`: `close_all()`.
- CredentialSlots unchanged (gateway provisioning contract intact).

### Tests

- Update conftest stub vault if needed (store/get/delete/list already stubbed?  — verify).
- New: registry resolution (0/1/N, by-name, by-id, miss), migration from legacy pair, name-fetch fallback chain (mock httpx), connect/disconnect tools, status shape.
- Keep: version-lockstep test (`test_manifest_and_code_versions_agree`), no-core-imports test.

## Execution order

1. `connections.py` (model, id derivation, name fetch, vault persistence, migration) + `state.py` registry.
2. `__init__.py` load path; `tools.py` workspace param + 3 new tools; `routes.py`.
3. Settings UI rewrite.
4. Version bump ×3; tests.
5. `pytest -q` from plugin dir (luna venv python).
6. Real-Luna verification: fresh DB, copy plugin into managed dir, connect two fake workspaces against a stub FF server (or one real key twice with different org ids), check Settings list, agent `ff_workspaces`/`ff_connect`, tool `workspace=` routing.
7. Ship: commit, push to `huemorgan/plugin-funnelfighters`, package + publish to marketplaces.com.ai `official`, verify index shows 0.4.0.
