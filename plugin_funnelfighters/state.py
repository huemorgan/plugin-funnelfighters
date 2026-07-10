"""Process-level registry of live workspace connections.

008.5/phase09 decoupled this from the plugin registry; 001-multi-workspace
turned the single ``FFClient`` singleton into an id-keyed connection registry
shared by ``on_load``, the routes, and the agent tools via relative import —
no core loader coupling, works the same from a managed dir.
"""

from __future__ import annotations

from .client import FFClient
from .config import FF_DEFAULT_BASE_URL
from .connections import Connection

_connections: dict[str, Connection] = {}
_base_url: str = FF_DEFAULT_BASE_URL


def set_base_url(url: str) -> None:
    global _base_url
    _base_url = url


def get_base_url() -> str:
    return _base_url


def all_connections() -> list[Connection]:
    return list(_connections.values())


def reset(conns: list[Connection]) -> None:
    _connections.clear()
    for c in conns:
        _connections[c.id] = c


def add_connection(conn: Connection) -> None:
    """Insert or replace (same key pair → same id → replace)."""
    _connections[conn.id] = conn


def find_connection(workspace: str) -> Connection | None:
    """Match by id first, then case-insensitive name."""
    conn = _connections.get(workspace)
    if conn is not None:
        return conn
    needle = workspace.strip().casefold()
    for c in _connections.values():
        if c.name.casefold() == needle:
            return c
    return None


def remove_connection(workspace: str) -> Connection | None:
    conn = find_connection(workspace)
    if conn is not None:
        del _connections[conn.id]
    return conn


def get_client(workspace: str | None = None) -> FFClient:
    """Resolve a workspace to its live client; raises RuntimeError otherwise.

    The messages double as agent-facing guidance — tools surface them verbatim,
    so a wrong/missing ``workspace`` arg tells the agent exactly what to pass.
    """
    if not _connections:
        raise RuntimeError(
            "FunnelFighters is not connected — add an API key and org ID in "
            "Settings > FunnelFighters, or use the ff_connect tool."
        )
    names = ", ".join(f"'{c.name}' ({c.id})" for c in _connections.values())
    if workspace:
        conn = find_connection(workspace)
        if conn is None:
            raise RuntimeError(
                f"No FunnelFighters workspace matches '{workspace}'. Connected: {names}."
            )
        return conn.ensure_client(_base_url)
    if len(_connections) == 1:
        return next(iter(_connections.values())).ensure_client(_base_url)
    raise RuntimeError(
        f"Several FunnelFighters workspaces are connected — pass workspace=<name or id>. Connected: {names}."
    )


async def close_all() -> None:
    for c in _connections.values():
        if c.client is not None:
            await c.client.close()
            c.client = None
    _connections.clear()
