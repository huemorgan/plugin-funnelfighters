"""plugin-funnelfighters API routes — connect, disconnect, status, settings UI.

0.4.0 (001-multi-workspace): `/connect` appends a connection (verifying the
pair and copying the workspace name from FunnelFighters), `/disconnect` removes
one by id (or, with an empty body, all vault-backed ones — the pre-0.4
semantics), `/status` keeps its old shape and adds the full `workspaces` list.
Connections persist as one JSON vault credential and rebuild the module-level
registry (``state.py``) so the agent's tools work immediately, without a
server restart.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import state
from .config import FF_VAULT_KEY_API, FF_VAULT_KEY_ORG
from .connections import (
    make_connection,
    refresh_placeholder_names,
    save_connections,
    verify_and_name,
)

log = logging.getLogger("plugin-funnelfighters.routes")

_SETTINGS_DIR = Path(__file__).parent / "interface" / "webui" / "settings"


class _ConnectReq(BaseModel):
    api_key: str
    org_id: str


class _DisconnectReq(BaseModel):
    id: str | None = None


class _StatusResp(BaseModel):
    connected: bool
    org_id: str | None = None
    workspaces: list[dict] = []


def register_routes(app, ctx):
    from luna_sdk import get_current_user

    router = APIRouter(prefix="/api/p/plugin-funnelfighters", tags=["funnelfighters"])

    def _vault():
        vault = ctx.vault
        if vault is None:
            raise HTTPException(503, "Vault not available")
        return vault

    @router.post("/connect")
    async def connect(body: _ConnectReq, user=Depends(get_current_user)):
        api_key = body.api_key.strip()
        org_id = body.org_id.strip()
        if not api_key or not org_id:
            raise HTTPException(400, "Both API key and org ID are required")

        vault = _vault()
        try:
            name = await verify_and_name(api_key, org_id, state.get_base_url())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        conn = make_connection(api_key, org_id, name=name)
        state.add_connection(conn)
        await save_connections(vault, state.all_connections())

        return {"connected": True, "org_id": org_id, "workspace": conn.public()}

    @router.post("/disconnect")
    async def disconnect(body: _DisconnectReq | None = None, user=Depends(get_current_user)):
        vault = _vault()
        conn_id = (body.id or "").strip() if body else ""

        if conn_id:
            conn = state.find_connection(conn_id)
            if conn is None:
                raise HTTPException(404, f"No workspace with id '{conn_id}'")
            if conn.source == "env":
                raise HTTPException(400, "This workspace is provisioned by the environment and cannot be removed here")
            state.remove_connection(conn.id)
            if conn.client is not None:
                await conn.client.close()
                conn.client = None
        else:
            # Legacy no-body call: drop every vault-backed connection.
            for conn in list(state.all_connections()):
                if conn.source != "vault":
                    continue
                state.remove_connection(conn.id)
                if conn.client is not None:
                    await conn.client.close()
                    conn.client = None
            for key in (FF_VAULT_KEY_API, FF_VAULT_KEY_ORG):
                try:
                    await vault.delete_credential(key)
                except KeyError:
                    pass

        await save_connections(vault, state.all_connections())
        return {"connected": len(state.all_connections()) > 0}

    @router.get("/status", response_model=_StatusResp)
    async def status(user=Depends(get_current_user)):
        conns = state.all_connections()
        await refresh_placeholder_names(conns, state.get_base_url(), getattr(ctx, "vault", None))
        if not conns:
            return _StatusResp(connected=False)
        return _StatusResp(
            connected=True,
            org_id=conns[0].org_id,
            workspaces=[c.public() for c in conns],
        )

    # --- Settings UI (served as a themed iframe by the host) ---

    @router.get("/ui/settings/")
    async def settings_index():
        index = _SETTINGS_DIR / "index.html"
        if not index.exists():
            raise HTTPException(404, "settings UI not found")
        return FileResponse(str(index), headers={"Cache-Control": "no-cache"})

    @router.get("/ui/settings/{path:path}")
    async def settings_asset(path: str):
        target = (_SETTINGS_DIR / path).resolve()
        if not str(target).startswith(str(_SETTINGS_DIR.resolve())):
            raise HTTPException(403, "forbidden")
        if not target.exists() or target.is_dir():
            return FileResponse(str(_SETTINGS_DIR / "index.html"), headers={"Cache-Control": "no-cache"})
        return FileResponse(str(target), headers={"Cache-Control": "no-cache"})

    app.include_router(router)
