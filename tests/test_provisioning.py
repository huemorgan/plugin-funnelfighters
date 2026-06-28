"""Cloud key-provisioning contract for plugin-funnelfighters."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from plugin_funnelfighters import FunnelFightersPlugin
from plugin_funnelfighters.client import FFClient
from plugin_funnelfighters.config import FF_DEFAULT_BASE_URL

PKG = Path(__file__).resolve().parents[1] / "plugin_funnelfighters"


def test_client_uses_base_url_override() -> None:
    c = FFClient(base_url="https://gw.example/proxy/funnelfighters", api_key="k", org_id="o")
    assert str(c._http.base_url).rstrip("/") == "https://gw.example/proxy/funnelfighters"


def test_client_default_base() -> None:
    c = FFClient(base_url=FF_DEFAULT_BASE_URL, api_key="k", org_id="o")
    assert str(c._http.base_url).rstrip("/") == FF_DEFAULT_BASE_URL


def test_credential_slots_advertise_base_url_var() -> None:
    slots = FunnelFightersPlugin().credential_slots()
    api_slot = next(s for s in slots if s.credential_name == "funnelfighters_api_key")
    org_slot = next(s for s in slots if s.credential_name == "funnelfighters_org_id")
    assert api_slot.env_key_var == "LUNA_FUNNELFIGHTERS_API_KEY"
    assert api_slot.env_base_url_var == "LUNA_FUNNELFIGHTERS_BASE_URL"
    # org id is not a proxy target
    assert org_slot.env_base_url_var is None


def test_manifest_and_code_versions_agree() -> None:
    toml_version = tomllib.loads((PKG / "luna-plugin.toml").read_text())["version"]
    code_version = re.search(r'version="([^"]+)"', (PKG / "__init__.py").read_text()).group(1)
    assert toml_version == code_version == FunnelFightersPlugin.manifest.version
