"""plugin-funnelfighters — Marketing intelligence via FunnelFighters + 4 Ducks methodology.

Registers read-only tools for querying the FunnelFighters API and a 4 Ducks
methodology skill the agent can load on demand. A connectors-category plugin
that ships installed-but-OFF (``default_enabled=False``): it shows in the
Plugins list toggled off. Turning it on exposes its tools/skill to the agent
and surfaces a "FunnelFighters" tab in Settings.

0.4.0 (001-multi-workspace): supports N workspace connections. The owner adds
keys in Settings; the agent adds them via ``ff_connect``. Each connection is
named after the FunnelFighters workspace (fetched right after a successful
verify). Data tools take an optional ``workspace`` arg; with a single
connection it can be omitted. Tools stay registered before any connection and
return a friendly "not connected" result.

0.5.0 (002-org-id-optional): connecting needs only the API key — the org id is
discovered from the key (``GET /api/settings``; a FunnelFighters key is bound
to exactly one organization server-side). Supplying an org id still works.
"""

from __future__ import annotations

import asyncio
import logging
import os

from luna_sdk import (
    CredentialSlot,
    LunaPlugin,
    PluginContext,
    PluginManifest,
    SettingsTab,
    SkillDef,
)

from .config import (
    FF_DEFAULT_BASE_URL,
    FF_ENV_BASE_URL,
    FF_ENV_KEY,
    FF_ENV_ORG,
    FF_VAULT_KEY_API,
    FF_VAULT_KEY_ORG,
)
from .connections import (
    fetch_workspace_name,
    load_connections,
    make_connection,
    save_connections,
)
from .knowledge import FOUR_DUCKS_KNOWLEDGE
from .state import add_connection, all_connections, close_all, reset, set_base_url
from .tools import build_management_tools, build_tools

log = logging.getLogger("plugin-funnelfighters")

# Cap on the boot-time workspace-name lookup for migrated/env connections —
# never let a slow FunnelFighters hold up Luna startup. Placeholder-named
# connections get re-resolved lazily by /status and ff_workspaces.
_BOOT_NAME_TIMEOUT = 8.0


class FunnelFightersPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="plugin-funnelfighters",
        shown_name="FunnelFighters",
        icon="filter",
        image="assets/icon.png",
        version="0.6.0",
        description="Marketing intelligence via FunnelFighters + 4 Ducks methodology",
        category="connectors",
        depends_on=["plugin-vault"],
        # Discovered and loaded at boot so it appears in the Plugins list, but
        # seeded OFF — the user enables it and adds credentials in Settings.
        auto_load=True,
        default_enabled=False,
        routes_module="routes",
        settings_tabs=[
            SettingsTab(
                id="funnelfighters",
                label="FunnelFighters",
                icon="target",
                sort_order=75,
                iframe_src="/api/p/plugin-funnelfighters/ui/settings/",
            ),
        ],
        interfaces={"webui": "interface/webui"},
    )

    @property
    def active(self) -> bool:
        return len(all_connections()) > 0

    def credential_slots(self) -> list[CredentialSlot]:
        # env_base_url_var on the api-key slot marks funnelfighters
        # proxy-provisionable: the gateway sets LUNA_FUNNELFIGHTERS_BASE_URL
        # (={gateway}/proxy/funnelfighters) + the token, so the real key never
        # lands on the tenant machine.
        return [
            CredentialSlot(
                slug="funnelfighters",
                credential_name=FF_VAULT_KEY_API,
                env_key_var=FF_ENV_KEY,
                env_base_url_var=FF_ENV_BASE_URL,
                owner=self.manifest.name,
            ),
            CredentialSlot(
                slug="funnelfighters",
                credential_name=FF_VAULT_KEY_ORG,
                env_key_var=FF_ENV_ORG,
                owner=self.manifest.name,
            ),
        ]

    async def on_load(self, ctx: PluginContext) -> None:
        # Tools + skill always register so the agent can see them the moment the
        # plugin is toggled on; the runtime filter hides them while it's off.
        # The registry stays empty until connections are present (loaded here at
        # boot or added later via Settings / ff_connect), and data tools report
        # "not connected".
        reset([])
        # 0.6.0: the 15 data tools ride behind the four-ducks skill — they're
        # only useful mid-analysis, and 15 schemas in every turn's prompt is
        # pure flooding. Management tools (ff_workspaces/ff_connect/
        # ff_disconnect) stay visible so connecting never needs a skill load.
        # Cores without a skill registry get everything ungated.
        gate = ctx.skill_registry is not None
        data_tool_names: list[str] = []
        for tool_def, handler in build_tools():
            data_tool_names.append(tool_def.name)
            if gate:
                try:
                    ctx.tool_registry.register(
                        self.manifest.name, tool_def, handler, skill_gated=True
                    )
                    continue
                except TypeError:  # core knows skills but not the kwarg
                    gate = False
            ctx.tool_registry.register(self.manifest.name, tool_def, handler)
        for tool_def, handler in build_management_tools(ctx):
            ctx.tool_registry.register(self.manifest.name, tool_def, handler)

        if ctx.skill_registry is not None:
            ctx.skill_registry.register(
                self.manifest.name,
                SkillDef(
                    name="four-ducks",
                    description=(
                        "marketing funnel analysis methodology + the "
                        "FunnelFighters data tools (campaigns, ads, funnels, "
                        "keywords, ROI) — load before analyzing ads, funnels, "
                        "or campaign performance; the tools unlock on your "
                        "next turn"
                    ),
                    body=FOUR_DUCKS_KNOWLEDGE,
                    tools=data_tool_names if gate else [],
                ),
            )

        await self._load_connections(ctx)
        log.info(
            "plugin-funnelfighters loaded (tools=18, workspaces=%d)",
            len(all_connections()),
        )

    async def _load_connections(self, ctx: PluginContext) -> None:
        """Rebuild the registry: persisted list, legacy-pair migration, env pair."""
        set_base_url(self._resolve_base_url(ctx))

        vault = getattr(ctx, "vault", None)
        conns = await load_connections(vault) if vault is not None else []

        # Migrate the pre-0.4 single connection (vault pair) into the list.
        if not conns and vault is not None:
            api_key = await self._vault_value(vault, FF_VAULT_KEY_API)
            org_id = await self._vault_value(vault, FF_VAULT_KEY_ORG)
            if api_key:
                conn = make_connection(api_key, org_id or "")
                conn.name = await self._boot_name(conn)
                conns = [conn]
                try:
                    await save_connections(vault, conns)
                    log.info("migrated legacy funnelfighters credentials to workspace list")
                except Exception as exc:  # noqa: BLE001
                    log.warning("could not persist migrated workspace list: %s", exc)

        reset(conns)

        # Gateway/env-provisioned key joins as a non-removable extra connection.
        # The org id is optional — the key carries the org server-side.
        env_key = self._env(ctx, FF_ENV_KEY, "FUNNELFIGHTERS_API_KEY")
        env_org = self._env(ctx, FF_ENV_ORG, "FUNNELFIGHTERS_ORG_ID")
        if env_key:
            conn = make_connection(env_key, env_org or "", source="env")
            conn.name = await self._boot_name(conn)
            add_connection(conn)
            log.info("registered env-provisioned funnelfighters workspace '%s'", conn.name)

    async def _boot_name(self, conn) -> str:
        try:
            return await asyncio.wait_for(
                fetch_workspace_name(conn.ensure_client(self._current_base_url()), conn.org_id),
                timeout=_BOOT_NAME_TIMEOUT,
            )
        except Exception:  # noqa: BLE001
            return conn.name

    @staticmethod
    def _current_base_url() -> str:
        from .state import get_base_url

        return get_base_url()

    @staticmethod
    async def _vault_value(vault, key: str) -> str | None:
        try:
            cred = await vault.get_credential(key)
            return (cred.value or "").strip() or None
        except KeyError:
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("plugin-funnelfighters: vault read failed for %s: %s", key, exc)
            return None

    @staticmethod
    def _env(ctx: PluginContext, env_key: str, native: str) -> str | None:
        if getattr(ctx, "get_env", None) is not None:
            val = (ctx.get_env(env_key) or "").strip()
            if val:
                return val
        return (os.environ.get(native) or "").strip() or None

    def _resolve_base_url(self, ctx: PluginContext) -> str:
        if getattr(ctx, "get_env", None) is not None:
            val = (ctx.get_env(FF_ENV_BASE_URL) or "").strip()
            if val:
                return val
        return (os.environ.get("FUNNELFIGHTERS_BASE_URL") or "").strip() or FF_DEFAULT_BASE_URL

    async def on_unload(self) -> None:
        await close_all()
