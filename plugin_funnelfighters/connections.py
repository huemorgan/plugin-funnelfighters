"""Multi-workspace connections — model, vault persistence, org/name discovery.

001-multi-workspace: a connection is an api_key (plus the org id it belongs
to) and the workspace name fetched from FunnelFighters right after a
successful verify. All vault-backed connections persist as ONE JSON credential
(``funnelfighters_workspaces``); the gateway/env-provisioned pair surfaces as
an extra non-removable connection with ``source="env"``.

002-org-id-optional: a FunnelFighters API key is bound to exactly one
organization server-side, so the org id is discovered from the key —
``GET /api/settings`` (auth: key, no org header) returns the key's org row
(id, name). Supplying org_id is still accepted for back-compat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .client import FFClient
from .config import FF_VAULT_KEY_WORKSPACES

log = logging.getLogger("plugin-funnelfighters.connections")

VERIFY_PATH = "/api/home/summary"
SETTINGS_PATH = "/api/settings"  # org row of the key's org: id, name, slug


def connection_id(api_key: str, org_id: str) -> str:
    """Stable key-derived id — same pair always maps to the same connection."""
    return hashlib.sha256(f"{api_key}:{org_id}".encode()).hexdigest()[:8]


def placeholder_name(org_id: str, conn_id: str = "") -> str:
    return f"org {org_id[:8]}" if org_id else f"workspace {conn_id or '?'}"


@dataclass
class Connection:
    id: str
    name: str
    api_key: str
    org_id: str
    connected_at: str = ""
    source: str = "vault"  # "vault" (owner/agent-added) | "env" (gateway-provisioned)
    client: FFClient | None = field(default=None, repr=False)

    def ensure_client(self, base_url: str) -> FFClient:
        if self.client is None:
            self.client = FFClient(base_url=base_url, api_key=self.api_key, org_id=self.org_id)
        return self.client

    def public(self) -> dict:
        """Wire shape for status/tools — never includes the api key."""
        return {
            "id": self.id,
            "name": self.name,
            "org_id": self.org_id,
            "source": self.source,
            "connected_at": self.connected_at,
        }


def make_connection(api_key: str, org_id: str = "", name: str = "", source: str = "vault") -> Connection:
    cid = connection_id(api_key, org_id)
    return Connection(
        id=cid,
        name=name or placeholder_name(org_id, cid),
        api_key=api_key,
        org_id=org_id,
        connected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source=source,
    )


# --- workspace-name discovery -------------------------------------------------

def _name_from_record(data: object) -> str | None:
    """Pull a display name out of one org/workspace record."""
    if not isinstance(data, dict):
        return None
    for key in ("name", "organizationName", "organization_name", "orgName", "org_name", "workspaceName", "title"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _name_nested(data: object) -> str | None:
    """Pull a name from a payload that EMBEDS the org record (e.g. home summary).

    Top-level ``name`` is deliberately ignored here — in a dashboard payload it
    could be anything.
    """
    if not isinstance(data, dict):
        return None
    for key in ("organization", "org", "workspace", "account"):
        name = _name_from_record(data.get(key))
        if name:
            return name
    for key in ("organizationName", "organization_name", "orgName", "org_name", "workspaceName"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _match_in_list(data: object, org_id: str) -> str | None:
    items = data
    if isinstance(data, dict):
        items = data.get("organizations") or data.get("items") or data.get("data")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        ids = {str(item.get(k)) for k in ("id", "_id", "organizationId", "organization_id", "org_id")}
        if org_id in ids:
            return _name_from_record(item)
    return None


async def discover_workspace(client: FFClient) -> tuple[str, str]:
    """Read the key's own org row from ``/api/settings`` → (org_id, name).

    Under key auth the server scopes this to the key's organization with no
    header needed (verified against server source, 2026-07-10). Returns
    ("", "") when the route is unavailable; raises nothing.
    """
    try:
        data = await client.get(SETTINGS_PATH)
    except Exception:  # noqa: BLE001
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    org_id = str(data.get("id") or "").strip()
    return org_id, (_name_from_record(data) or "")


async def fetch_workspace_name(client: FFClient, org_id: str) -> str:
    """Best-effort name lookup; falls back to a placeholder, never raises."""
    _, name = await discover_workspace(client)
    if name:
        return name
    try:
        name = _name_nested(await client.get(VERIFY_PATH))
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    try:
        name = _match_in_list(await client.get("/api/organizations"), org_id)
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    return placeholder_name(org_id)


# --- vault persistence ----------------------------------------------------------

def _serialize(conns: list[Connection]) -> str:
    return json.dumps(
        [
            {
                "id": c.id,
                "name": c.name,
                "api_key": c.api_key,
                "org_id": c.org_id,
                "connected_at": c.connected_at,
            }
            for c in conns
            if c.source == "vault"
        ]
    )


async def load_connections(vault) -> list[Connection]:
    """Read the persisted list; missing credential or bad JSON → empty."""
    try:
        raw = (await vault.get_credential(FF_VAULT_KEY_WORKSPACES)).value
    except KeyError:
        return []
    except Exception as exc:  # noqa: BLE001
        log.warning("vault read failed for %s: %s", FF_VAULT_KEY_WORKSPACES, exc)
        return []
    try:
        entries = json.loads(raw or "[]")
    except json.JSONDecodeError:
        log.warning("corrupt %s credential; ignoring", FF_VAULT_KEY_WORKSPACES)
        return []
    out: list[Connection] = []
    for e in entries:
        if not isinstance(e, dict) or not e.get("api_key"):
            continue
        org_id = e.get("org_id") or ""
        cid = e.get("id") or connection_id(e["api_key"], org_id)
        out.append(
            Connection(
                id=cid,
                name=e.get("name") or placeholder_name(org_id, cid),
                api_key=e["api_key"],
                org_id=org_id,
                connected_at=e.get("connected_at", ""),
                source="vault",
            )
        )
    return out


async def save_connections(vault, conns: list[Connection]) -> None:
    await vault.store_credential(FF_VAULT_KEY_WORKSPACES, _serialize(conns), kind="config")


_refresh_attempted: set[str] = set()


async def refresh_placeholder_names(conns: list[Connection], base_url: str, vault=None) -> None:
    """Re-resolve placeholder names (once per connection per process).

    Placeholders only occur when FunnelFighters was unreachable during the
    boot-time lookup for migrated/env connections; status and ff_workspaces
    call this so the real name appears as soon as the API is reachable.
    """
    changed = False
    for c in conns:
        if c.name != placeholder_name(c.org_id, c.id) or c.id in _refresh_attempted:
            continue
        _refresh_attempted.add(c.id)
        name = await fetch_workspace_name(c.ensure_client(base_url), c.org_id)
        if name != c.name:
            c.name = name
            changed = True
    if changed and vault is not None:
        try:
            await save_connections(vault, conns)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not persist refreshed workspace names: %s", exc)


async def verify_and_discover(api_key: str, base_url: str, org_id: str = "") -> tuple[str, str]:
    """Verify the key against the API and return ``(org_id, name)``.

    The key alone is enough: ``/api/settings`` (key auth, no org header)
    returns the org row the key is bound to. A supplied ``org_id`` is kept
    (and sent as a header, which the server checks) for back-compat.

    Raises ``ValueError`` (with the upstream detail) when the credentials are
    rejected — callers turn that into an HTTP 400 or a tool error.
    """
    client = FFClient(base_url=base_url, api_key=api_key, org_id=org_id)
    try:
        discovered, name = await discover_workspace(client)
        if discovered:
            org_id = org_id or discovered
            return org_id, (name or placeholder_name(org_id))
        # /api/settings unavailable (older server / proxy): fall back to the
        # 0.4 behavior — verify via the home summary, then best-effort name.
        try:
            await client.get(VERIFY_PATH)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Could not connect with those credentials: {e}") from e
        return org_id, await fetch_workspace_name(client, org_id)
    finally:
        await client.close()
