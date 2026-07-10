# 002 — Org ID optional: execution summary

**Shipped 2026-07-10 as 0.5.0.** Connecting a FunnelFighters workspace now needs
only the API key; the organization id and workspace name are discovered from the
key via `GET /api/settings` (a key is bound to exactly one org server-side —
confirmed from the FunnelFighters server source).

Built exactly per plan.md: headerless `FFClient` when the org is unknown,
`verify_and_discover` returning `(org_id, name)`, optional `org_id` in
`/connect` / `ff_connect` / Settings UI, env key registers without an org var,
dead `GET /api/organizations/:id` name fallback removed. Versions bumped in all
three stamps.

Verification: 39/39 unit tests; fresh real Luna against a stub mirroring the
real auth semantics — key-only REST connect discovered org + copied names
("Alpha Rockets"/"Beta Bakery"), bad key → 400, explicit-org connect is
back-compatible (same connection id), agent `ff_connect` with only a key went
through the approval gate and connected; data calls work with and without the
org header.
