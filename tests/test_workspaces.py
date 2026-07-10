"""001-multi-workspace acceptance — registry resolution, persistence,
migration, name discovery, and the management tools."""

from __future__ import annotations

import asyncio
import json

import pytest

from plugin_funnelfighters import state
from plugin_funnelfighters.config import (
    FF_VAULT_KEY_API,
    FF_VAULT_KEY_ORG,
    FF_VAULT_KEY_WORKSPACES,
)
from plugin_funnelfighters.connections import (
    Connection,
    connection_id,
    fetch_workspace_name,
    load_connections,
    make_connection,
    placeholder_name,
    save_connections,
)


class FakeCredential:
    def __init__(self, value: str):
        self.value = value


class FakeVault:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def store_credential(self, name, value, *, kind="api_key", metadata=None):
        self.store[name] = value

    async def get_credential(self, name):
        if name not in self.store:
            raise KeyError(name)
        return FakeCredential(self.store[name])

    async def delete_credential(self, name):
        return self.store.pop(name, None) is not None


class FakeClient:
    """Duck-typed FFClient: path -> response dict, or Exception to raise."""

    def __init__(self, responses: dict):
        self.responses = responses

    async def get(self, path, params=None):
        r = self.responses.get(path, KeyError(path))
        if isinstance(r, Exception):
            raise r
        return r

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def clean_registry():
    state.reset([])
    yield
    state.reset([])


def _conn(name="Acme", key="k1", org="org1", source="vault") -> Connection:
    return make_connection(key, org, name=name, source=source)


# --- registry resolution -----------------------------------------------------

def test_get_client_no_connections():
    with pytest.raises(RuntimeError, match="not connected"):
        state.get_client()


def test_get_client_single_connection_default():
    c = _conn()
    state.add_connection(c)
    assert state.get_client() is c.ensure_client(state.get_base_url())


def test_get_client_multiple_requires_workspace():
    state.add_connection(_conn("Acme", "k1", "org1"))
    state.add_connection(_conn("Beta", "k2", "org2"))
    with pytest.raises(RuntimeError, match="Acme.*Beta|Beta.*Acme"):
        state.get_client()


def test_get_client_by_name_case_insensitive_and_by_id():
    a = _conn("Acme", "k1", "org1")
    b = _conn("Beta", "k2", "org2")
    state.add_connection(a)
    state.add_connection(b)
    assert state.get_client("acme") is a.ensure_client(state.get_base_url())
    assert state.get_client(b.id) is b.ensure_client(state.get_base_url())
    with pytest.raises(RuntimeError, match="No FunnelFighters workspace matches 'nope'"):
        state.get_client("nope")


def test_same_pair_same_id_replaces():
    state.add_connection(_conn("Old", "k1", "org1"))
    state.add_connection(_conn("New", "k1", "org1"))
    conns = state.all_connections()
    assert len(conns) == 1 and conns[0].name == "New"
    assert connection_id("k1", "org1") == conns[0].id


# --- persistence + migration ---------------------------------------------------

@pytest.mark.asyncio
async def test_save_load_roundtrip_excludes_env():
    vault = FakeVault()
    state.add_connection(_conn("Acme", "k1", "org1"))
    state.add_connection(_conn("Gateway", "k2", "org2", source="env"))
    await save_connections(vault, state.all_connections())

    entries = json.loads(vault.store[FF_VAULT_KEY_WORKSPACES])
    assert [e["name"] for e in entries] == ["Acme"]
    assert entries[0]["api_key"] == "k1"

    loaded = await load_connections(vault)
    assert len(loaded) == 1
    assert loaded[0].name == "Acme" and loaded[0].source == "vault"


@pytest.mark.asyncio
async def test_load_tolerates_missing_and_corrupt():
    vault = FakeVault()
    assert await load_connections(vault) == []
    vault.store[FF_VAULT_KEY_WORKSPACES] = "{not json"
    assert await load_connections(vault) == []


@pytest.mark.asyncio
async def test_legacy_pair_migrates_on_load(monkeypatch):
    from plugin_funnelfighters import FunnelFightersPlugin

    vault = FakeVault()
    vault.store[FF_VAULT_KEY_API] = "legacy-key"
    vault.store[FF_VAULT_KEY_ORG] = "legacy-org"

    class Ctx:
        pass

    ctx = Ctx()
    ctx.vault = vault
    ctx.get_env = lambda k: None

    async def fake_name(client, org_id):
        return "Legacy Workspace"

    import plugin_funnelfighters as pkg

    monkeypatch.setattr(pkg, "fetch_workspace_name", fake_name)

    await FunnelFightersPlugin()._load_connections(ctx)
    conns = state.all_connections()
    assert len(conns) == 1
    assert conns[0].name == "Legacy Workspace"
    assert conns[0].api_key == "legacy-key"
    # migration persisted the list
    assert FF_VAULT_KEY_WORKSPACES in vault.store
    # legacy keys are kept (gateway slot targets)
    assert vault.store[FF_VAULT_KEY_API] == "legacy-key"


@pytest.mark.asyncio
async def test_env_pair_registers_as_env_connection(monkeypatch):
    from plugin_funnelfighters import FunnelFightersPlugin
    import plugin_funnelfighters as pkg

    class Ctx:
        vault = FakeVault()

        @staticmethod
        def get_env(k):
            return {
                "LUNA_FUNNELFIGHTERS_API_KEY": "gw-token",
                "LUNA_FUNNELFIGHTERS_ORG_ID": "gw-org",
                "LUNA_FUNNELFIGHTERS_BASE_URL": "https://gw.example/proxy/funnelfighters",
            }.get(k)

    async def fake_name(client, org_id):
        return "Hosted Org"

    monkeypatch.setattr(pkg, "fetch_workspace_name", fake_name)

    await FunnelFightersPlugin()._load_connections(Ctx())
    conns = state.all_connections()
    assert len(conns) == 1
    assert conns[0].source == "env" and conns[0].name == "Hosted Org"
    assert state.get_base_url() == "https://gw.example/proxy/funnelfighters"


# --- name discovery -------------------------------------------------------------

@pytest.mark.asyncio
async def test_name_from_home_summary_nested():
    client = FakeClient({"/api/home/summary": {"organization": {"name": "Acme Inc"}}})
    assert await fetch_workspace_name(client, "org1") == "Acme Inc"


@pytest.mark.asyncio
async def test_name_ignores_toplevel_name_in_summary_falls_to_org_record():
    client = FakeClient({
        "/api/home/summary": {"name": "Some Dashboard"},
        "/api/organizations/org1": {"id": "org1", "name": "Real Org"},
    })
    assert await fetch_workspace_name(client, "org1") == "Real Org"


@pytest.mark.asyncio
async def test_name_from_org_list():
    client = FakeClient({
        "/api/home/summary": {},
        "/api/organizations/org2": RuntimeError("404"),
        "/api/organizations": {"organizations": [
            {"id": "org1", "name": "Wrong"},
            {"id": "org2", "name": "Right"},
        ]},
    })
    assert await fetch_workspace_name(client, "org2") == "Right"


@pytest.mark.asyncio
async def test_name_falls_back_to_placeholder():
    client = FakeClient({})  # every path raises
    assert await fetch_workspace_name(client, "org-abcdef-123") == placeholder_name("org-abcdef-123")


# --- management tools ------------------------------------------------------------

def _mgmt_handlers(vault):
    from plugin_funnelfighters.tools import build_management_tools

    class Ctx:
        pass

    ctx = Ctx()
    ctx.vault = vault
    return {td.name: h for td, h in build_management_tools(ctx)}


@pytest.mark.asyncio
async def test_ff_connect_and_workspaces_and_disconnect(monkeypatch):
    from plugin_funnelfighters import tools as tools_mod

    async def fake_verify(api_key, org_id, base_url):
        if api_key == "bad":
            raise ValueError("Could not connect with those credentials: 401")
        return f"WS-{org_id}"

    monkeypatch.setattr(tools_mod, "verify_and_name", fake_verify)
    vault = FakeVault()
    h = _mgmt_handlers(vault)

    r = await h["ff_connect"](api_key="k1", org_id="org1")
    assert r["connected"] and r["workspace"]["name"] == "WS-org1"
    r2 = await h["ff_connect"](api_key="k2", org_id="org2")
    assert r2["workspace"]["name"] == "WS-org2"

    bad = await h["ff_connect"](api_key="bad", org_id="orgX")
    assert bad["error"] == "verify_failed"

    ws = await h["ff_workspaces"]()
    assert ws["count"] == 2
    assert {w["name"] for w in ws["workspaces"]} == {"WS-org1", "WS-org2"}
    assert all("api_key" not in w for w in ws["workspaces"])

    # persisted both
    assert len(json.loads(vault.store[FF_VAULT_KEY_WORKSPACES])) == 2

    d = await h["ff_disconnect"](workspace="WS-org1")
    assert d["disconnected"]
    assert len(state.all_connections()) == 1
    assert len(json.loads(vault.store[FF_VAULT_KEY_WORKSPACES])) == 1

    miss = await h["ff_disconnect"](workspace="ghost")
    assert miss["error"] == "not_found"


@pytest.mark.asyncio
async def test_ff_disconnect_refuses_env_connection():
    vault = FakeVault()
    state.add_connection(_conn("Hosted", "gk", "gorg", source="env"))
    h = _mgmt_handlers(vault)
    r = await h["ff_disconnect"](workspace="Hosted")
    assert r["error"] == "provisioned"
    assert len(state.all_connections()) == 1


# --- data tools thread the workspace arg -----------------------------------------

@pytest.mark.asyncio
async def test_data_tool_errors_list_workspaces():
    from plugin_funnelfighters.tools import build_tools

    handlers = {td.name: h for td, h in build_tools()}
    state.add_connection(_conn("Acme", "k1", "org1"))
    state.add_connection(_conn("Beta", "k2", "org2"))

    r = await handlers["ff_campaigns"]()
    assert r["error"] == "not_connected"
    assert "Acme" in r["detail"] and "Beta" in r["detail"]

    r2 = await handlers["ff_campaigns"](workspace="ghost")
    assert "ghost" in r2["detail"]


def test_every_data_tool_declares_workspace_param():
    from plugin_funnelfighters.tools import build_tools

    for td, _ in build_tools():
        assert "workspace" in td.parameters["properties"], td.name
