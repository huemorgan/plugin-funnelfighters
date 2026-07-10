"""Configuration constants for the FunnelFighters plugin."""

FF_DEFAULT_BASE_URL = "https://funnelfighters.io"
FF_VAULT_KEY_API = "funnelfighters_api_key"
FF_VAULT_KEY_ORG = "funnelfighters_org_id"

# 0.4.0 multi-workspace: all connections live in ONE vault credential holding a
# JSON list. The legacy pair above is migrated into it on first load and kept
# only as the gateway CredentialSlot target.
FF_VAULT_KEY_WORKSPACES = "funnelfighters_workspaces"

# Cloud key-provisioning: when set, route through `{gateway}/proxy/funnelfighters`
# and treat the api key as the opaque gateway token.
FF_ENV_KEY = "LUNA_FUNNELFIGHTERS_API_KEY"
FF_ENV_ORG = "LUNA_FUNNELFIGHTERS_ORG_ID"
FF_ENV_BASE_URL = "LUNA_FUNNELFIGHTERS_BASE_URL"
