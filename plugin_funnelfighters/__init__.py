"""plugin-funnelfighters — Marketing intelligence via FunnelFighters + 4 Ducks methodology.

Registers read-only tools for querying the FunnelFighters API and a 4 Ducks
methodology skill the agent can load on demand. A connectors-category plugin
that ships installed-but-OFF (``default_enabled=False``): it shows in the
Plugins list toggled off. Turning it on exposes its tools/skill to the agent
and surfaces a "FunnelFighters" tab in Settings where the user pastes their
API key + org ID. Tools stay registered before connection and return a
friendly "not connected" result until credentials are saved.
"""

from __future__ import annotations

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

from .client import FFClient
from .config import (
    FF_DEFAULT_BASE_URL,
    FF_ENV_BASE_URL,
    FF_ENV_KEY,
    FF_ENV_ORG,
    FF_VAULT_KEY_API,
    FF_VAULT_KEY_ORG,
)
from .knowledge import FOUR_DUCKS_KNOWLEDGE
from .state import get_client, set_client
from .tools import build_tools

log = logging.getLogger("plugin-funnelfighters")


class FunnelFightersPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="plugin-funnelfighters",
        icon="filter",
        image="assets/icon.png",
        version="0.3.1",
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
        return get_client() is not None

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

    def _get_client(self) -> FFClient:
        client = get_client()
        if client is None:
            raise RuntimeError(
                "FunnelFighters not connected — add the API key and org ID in Settings."
            )
        return client

    async def on_load(self, ctx: PluginContext) -> None:
        # Tools + skill always register so the agent can see them the moment the
        # plugin is toggled on; the runtime filter hides them while it's off.
        # The client stays None until credentials are present (here at boot or
        # later via the Settings connect flow), and tools report "not connected".
        set_client(None)
        for tool_def, handler in build_tools(self._get_client):
            ctx.tool_registry.register(self.manifest.name, tool_def, handler)

        if ctx.skill_registry is not None:
            ctx.skill_registry.register(
                self.manifest.name,
                SkillDef(
                    name="four-ducks",
                    description=(
                        "marketing funnel analysis methodology — load before "
                        "analyzing ads, funnels, or campaign performance"
                    ),
                    body=FOUR_DUCKS_KNOWLEDGE,
                ),
            )

        await self._connect_from_vault(ctx)
        log.info("plugin-funnelfighters loaded (tools=15, connected=%s)", self.active)

    async def _connect_from_vault(self, ctx: PluginContext) -> None:
        """Build the client from vault → env credentials (env = gateway token in
        proxy mode), routing through LUNA_FUNNELFIGHTERS_BASE_URL when set."""
        api_key = await self._resolve(ctx, FF_VAULT_KEY_API, FF_ENV_KEY, "FUNNELFIGHTERS_API_KEY")
        org_id = await self._resolve(ctx, FF_VAULT_KEY_ORG, FF_ENV_ORG, "FUNNELFIGHTERS_ORG_ID")

        if not api_key or not org_id:
            log.info("API key or org_id not configured; not connected")
            return

        base_url = self._resolve_base_url(ctx)
        set_client(FFClient(base_url=base_url, api_key=api_key, org_id=org_id))
        log.info("plugin-funnelfighters connected (gateway=%s)", base_url != FF_DEFAULT_BASE_URL)

    async def _resolve(self, ctx: PluginContext, vault_key: str, env_key: str, native: str) -> str | None:
        vault = getattr(ctx, "vault", None)
        if vault is not None:
            try:
                cred = await vault.get_credential(vault_key)
                if (cred.value or "").strip():
                    return cred.value.strip()
            except KeyError:
                pass
            except Exception as exc:  # noqa: BLE001
                log.warning("plugin-funnelfighters: vault read failed for %s: %s", vault_key, exc)
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
        client = get_client()
        if client is not None:
            await client.close()
            set_client(None)
