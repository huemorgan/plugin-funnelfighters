"""Configuration constants for the FunnelFighters plugin."""

FF_DEFAULT_BASE_URL = "https://funnelfighters.io"
FF_VAULT_KEY_API = "funnelfighters_api_key"
FF_VAULT_KEY_ORG = "funnelfighters_org_id"

# Cloud key-provisioning: when set, route through `{gateway}/proxy/funnelfighters`
# and treat the api key as the opaque gateway token.
FF_ENV_KEY = "LUNA_FUNNELFIGHTERS_API_KEY"
FF_ENV_ORG = "LUNA_FUNNELFIGHTERS_ORG_ID"
FF_ENV_BASE_URL = "LUNA_FUNNELFIGHTERS_BASE_URL"
