# 002 — Org ID optional: connect with just the API key

**Ask:** "remove the org id requirement — if you can get it yourself with the key it's best."

## Feasibility (confirmed from FunnelFighters server source, 2026-07-10)

- `apiKeyAuth.js`: an API key is bound to exactly ONE organization (`api_keys.organization_id`); key auth sets `req.organizationId` from the key.
- `requireOrg.js`: "API-key auth: the key itself carries the org, no header needed" — the `x-organization-id` header is optional under key auth (and checked if sent).
- `settings.js` (`GET /api/settings`, requireAuth + requireOrg): returns the key's own org row — **id, name, slug** — in one headerless call. This is the discovery endpoint.
- `/api/home/summary` carries only KPI counts (no org block) and `organizations.js` has no `GET /:id` — so the 0.4.0 name chain's first two sources were dead against the real server; fixed here.

## Changes (0.5.0)

- `client.py`: omit the `x-organization-id` header when the org is unknown.
- `connections.py`: `discover_workspace(client)` → `(org_id, name)` from `/api/settings`; `verify_and_name` → `verify_and_discover(api_key, base_url, org_id="") -> (org_id, name)` (falls back to the 0.4 `/api/home/summary` verify for older servers); name chain now `/api/settings` → summary-nested → org-list → placeholder; orgless connections allowed everywhere (id = sha256(key:""), placeholder "workspace {id}").
- `routes.py` `/connect` + `tools.py` `ff_connect`: `org_id` optional (kept for back-compat; supplied value wins and is sent as a header, which the server validates).
- `__init__.py`: env-provisioned key registers even without an org env var.
- Settings UI: org field marked optional ("auto-detected"); key alone connects.

## Verification

- Unit tests extended 27 → 39.
- Real fresh Luna + stub mirroring the real auth semantics (key→one org, headerless OK, mismatched header rejected, `/api/settings` org row, no `organizations/:id`): key-only REST connect discovers org + copies name; bad key → 400; explicit-org connect maps to the same connection id; agent `ff_connect` with only a key → approval → connected.
