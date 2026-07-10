"""FunnelFighters agent-facing tools — 15 read-only data endpoints + workspace management.

0.4.0 (001-multi-workspace): every data tool takes an optional ``workspace``
(name or id). With one connection it can be omitted; with several, omitting it
returns an error listing the connected names so the agent self-corrects.
``ff_workspaces`` lists connections, ``ff_connect`` adds one (verifying the
pair and copying the workspace name from FunnelFighters), ``ff_disconnect``
removes one.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from luna_sdk import ToolDef

from . import state
from .connections import (
    make_connection,
    refresh_placeholder_names,
    save_connections,
    verify_and_name,
)

MAX_RESPONSE_CHARS = 4000

_WORKSPACE_PARAM = {
    "type": "string",
    "description": (
        "Workspace name or id (see ff_workspaces). Optional when only one "
        "workspace is connected."
    ),
}


def _truncate(data: Any) -> str:
    """Serialize response and truncate if over MAX_RESPONSE_CHARS."""
    text = json.dumps(data, default=str)
    if len(text) > MAX_RESPONSE_CHARS:
        return text[:MAX_RESPONSE_CHARS] + "...truncated"
    return text


def _date_params(start_date: str | None, end_date: str | None) -> dict | None:
    params: dict[str, str] = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return params or None


async def _safe_get(workspace: str | None, path: str, params: dict | None = None) -> dict:
    try:
        client = state.get_client(workspace)
    except RuntimeError as e:
        return {"error": "not_connected", "detail": str(e)}
    try:
        data = await client.get(path, params=params)
        return {"result": _truncate(data)}
    except httpx.HTTPStatusError as e:
        return {"error": e.response.status_code, "detail": e.response.text[:500]}


async def _safe_post(workspace: str | None, path: str, json_body: dict | None = None) -> dict:
    try:
        client = state.get_client(workspace)
    except RuntimeError as e:
        return {"error": "not_connected", "detail": str(e)}
    try:
        data = await client.post(path, json=json_body)
        return {"result": _truncate(data)}
    except httpx.HTTPStatusError as e:
        return {"error": e.response.status_code, "detail": e.response.text[:500]}


def build_tools() -> list[tuple[ToolDef, Any]]:
    """Return (ToolDef, handler) pairs for the 15 read-only data tools.

    The workspace is resolved lazily per invocation (``state.get_client``) so
    tools stay registered even before any connection exists; resolution errors
    come back as friendly "not connected" results.
    """

    async def ff_portfolio_summary(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Get portfolio summary — spend, visitors, signups, activated, paying, revenue, tROI."""
        return await _safe_get(workspace, "/api/portfolio/summary", _date_params(start_date, end_date))

    async def ff_campaigns(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """List all campaigns with metrics for a date range."""
        return await _safe_get(workspace, "/api/campaigns/", _date_params(start_date, end_date))

    async def ff_campaign_detail(
        campaign_id: str, start_date: str | None = None, end_date: str | None = None,
        workspace: str | None = None,
    ) -> dict:
        """Deep dive into a campaign — hourly metrics, impression share, audience/device/geo breakdown."""
        return await _safe_get(workspace, f"/api/campaigns/{campaign_id}", _date_params(start_date, end_date))

    async def ff_ads(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """List ads with performance metrics."""
        return await _safe_get(workspace, "/api/ads/", _date_params(start_date, end_date))

    async def ff_ad_detail(
        ad_id: str, start_date: str | None = None, end_date: str | None = None,
        workspace: str | None = None,
    ) -> dict:
        """Ad creative, funnel through-rate, versions, agent action history."""
        return await _safe_get(workspace, f"/api/ads/{ad_id}", _date_params(start_date, end_date))

    async def ff_funnel(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Full waterfall: impressions → clicks → visitors → signups → activated → paying."""
        return await _safe_get(workspace, "/api/funnel/", _date_params(start_date, end_date))

    async def ff_cohorts(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Weekly signup cohorts with conversion progression."""
        return await _safe_get(workspace, "/api/cohorts/weekly", _date_params(start_date, end_date))

    async def ff_keywords(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Keyword performance + search terms."""
        return await _safe_get(workspace, "/api/keywords/", _date_params(start_date, end_date))

    async def ff_wasted_spend(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Wasted spend analysis — identify budget going to non-converting paths."""
        return await _safe_get(workspace, "/api/insights/wasted-spend", _date_params(start_date, end_date))

    async def ff_landing_pages(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Landing page performance — signup rates, bounce rates."""
        return await _safe_get(workspace, "/api/landing-pages/", _date_params(start_date, end_date))

    async def ff_duck_reports(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Get 4 Ducks alignment reports."""
        return await _safe_get(workspace, "/api/duck-reports/", _date_params(start_date, end_date))

    async def ff_duck_analyze(
        campaign_id: str | None = None, workspace: str | None = None
    ) -> dict:
        """Trigger a new 4 Ducks alignment analysis. Optionally scope to a campaign."""
        body = {}
        if campaign_id:
            body["campaign_id"] = campaign_id
        return await _safe_post(workspace, "/api/duck-reports/analyze", body or None)

    async def ff_roi_summary(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """ROI/tROI breakdown by campaign, ad, audience, LP."""
        return await _safe_get(workspace, "/api/roi/summary", _date_params(start_date, end_date))

    async def ff_visitors(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Visitor analytics with source/campaign filters."""
        return await _safe_get(workspace, "/api/visitors/", _date_params(start_date, end_date))

    async def ff_home_summary(
        start_date: str | None = None, end_date: str | None = None, workspace: str | None = None
    ) -> dict:
        """Dashboard KPIs + recent changelog."""
        return await _safe_get(workspace, "/api/home/summary", _date_params(start_date, end_date))

    def _dates(extra: dict | None = None, required: list[str] | None = None) -> dict:
        props = dict(extra or {})
        props["start_date"] = {"type": "string", "description": "ISO date (YYYY-MM-DD). Default: 28 days ago."}
        props["end_date"] = {"type": "string", "description": "ISO date (YYYY-MM-DD). Default: today."}
        props["workspace"] = _WORKSPACE_PARAM
        schema: dict = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return schema

    tools = [
        (ToolDef(
            name="ff_portfolio_summary",
            description="Get FunnelFighters portfolio summary — spend, visitors, signups, activated, paying, revenue, tROI for a date range.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_portfolio_summary),
        (ToolDef(
            name="ff_campaigns",
            description="List all campaigns with metrics for a date range.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_campaigns),
        (ToolDef(
            name="ff_campaign_detail",
            description="Deep dive into a specific campaign — hourly metrics, impression share, audience/device/geo breakdown.",
            parameters=_dates({"campaign_id": {"type": "string", "description": "Campaign ID to inspect."}}, required=["campaign_id"]),
            policy="auto_approve",
        ), ff_campaign_detail),
        (ToolDef(
            name="ff_ads",
            description="List ads with performance metrics.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_ads),
        (ToolDef(
            name="ff_ad_detail",
            description="Ad creative details, funnel through-rate, versions, and agent action history.",
            parameters=_dates({"ad_id": {"type": "string", "description": "Ad ID to inspect."}}, required=["ad_id"]),
            policy="auto_approve",
        ), ff_ad_detail),
        (ToolDef(
            name="ff_funnel",
            description="Full funnel waterfall: impressions → clicks → visitors → signups → activated → paying.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_funnel),
        (ToolDef(
            name="ff_cohorts",
            description="Weekly signup cohorts with conversion progression.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_cohorts),
        (ToolDef(
            name="ff_keywords",
            description="Keyword performance + search terms.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_keywords),
        (ToolDef(
            name="ff_wasted_spend",
            description="Wasted spend analysis — identify budget going to non-converting paths.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_wasted_spend),
        (ToolDef(
            name="ff_landing_pages",
            description="Landing page performance — signup rates, bounce rates, per-LP metrics.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_landing_pages),
        (ToolDef(
            name="ff_duck_reports",
            description="Get 4 Ducks alignment reports showing which ducks are misaligned.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_duck_reports),
        (ToolDef(
            name="ff_duck_analyze",
            description="Trigger a new 4 Ducks alignment analysis. Optionally scope to a specific campaign.",
            parameters={"type": "object", "properties": {
                "campaign_id": {"type": "string", "description": "Optional campaign ID to scope the analysis."},
                "workspace": _WORKSPACE_PARAM,
            }},
            policy="auto_approve",
        ), ff_duck_analyze),
        (ToolDef(
            name="ff_roi_summary",
            description="ROI/tROI breakdown by campaign, ad, audience, and landing page.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_roi_summary),
        (ToolDef(
            name="ff_visitors",
            description="Visitor analytics with source/campaign filters.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_visitors),
        (ToolDef(
            name="ff_home_summary",
            description="Dashboard KPIs + recent changelog from FunnelFighters home.",
            parameters=_dates(),
            policy="auto_approve",
        ), ff_home_summary),
    ]

    return tools


def build_management_tools(ctx) -> list[tuple[ToolDef, Any]]:
    """Workspace-management tools — list / connect / disconnect.

    ``ctx`` provides the vault used to persist the connection list; when it is
    unavailable, connect/disconnect still work for the session but warn that
    nothing was persisted.
    """

    def _vault():
        return getattr(ctx, "vault", None)

    async def ff_workspaces() -> dict:
        conns = state.all_connections()
        await refresh_placeholder_names(conns, state.get_base_url(), _vault())
        return {"workspaces": [c.public() for c in conns], "count": len(conns)}

    async def ff_connect(api_key: str, org_id: str) -> dict:
        api_key = (api_key or "").strip()
        org_id = (org_id or "").strip()
        if not api_key or not org_id:
            return {"error": "invalid_args", "detail": "Both api_key and org_id are required."}
        try:
            name = await verify_and_name(api_key, org_id, state.get_base_url())
        except ValueError as e:
            return {"error": "verify_failed", "detail": str(e)}
        conn = make_connection(api_key, org_id, name=name)
        state.add_connection(conn)
        persisted = True
        vault = _vault()
        if vault is not None:
            try:
                await save_connections(vault, state.all_connections())
            except Exception as e:  # noqa: BLE001
                persisted = False
                detail = str(e)
        else:
            persisted = False
            detail = "vault unavailable"
        result = {"connected": True, "workspace": conn.public()}
        if not persisted:
            result["warning"] = f"connection is live but was not persisted: {detail}"
        return result

    async def ff_disconnect(workspace: str) -> dict:
        conn = state.find_connection((workspace or "").strip())
        if conn is None:
            names = ", ".join(f"'{c.name}' ({c.id})" for c in state.all_connections()) or "none"
            return {"error": "not_found", "detail": f"No workspace matches '{workspace}'. Connected: {names}."}
        if conn.source == "env":
            return {
                "error": "provisioned",
                "detail": f"Workspace '{conn.name}' is provisioned by the environment/gateway and cannot be removed here.",
            }
        state.remove_connection(conn.id)
        if conn.client is not None:
            await conn.client.close()
            conn.client = None
        vault = _vault()
        if vault is not None:
            try:
                await save_connections(vault, state.all_connections())
            except Exception as e:  # noqa: BLE001
                return {"disconnected": True, "workspace": conn.public(), "warning": f"not persisted: {e}"}
        return {"disconnected": True, "workspace": conn.public()}

    return [
        (ToolDef(
            name="ff_workspaces",
            description="List connected FunnelFighters workspaces (name, id, org). Use the names/ids as the `workspace` arg of the other ff_ tools.",
            parameters={"type": "object", "properties": {}},
            policy="auto_approve",
        ), ff_workspaces),
        (ToolDef(
            name="ff_connect",
            description="Connect a FunnelFighters workspace from an API key + organization ID. Verifies the pair and names the connection after the FunnelFighters workspace.",
            parameters={"type": "object", "properties": {
                "api_key": {"type": "string", "description": "FunnelFighters API key."},
                "org_id": {"type": "string", "description": "FunnelFighters organization ID."},
            }, "required": ["api_key", "org_id"]},
            policy="prompt_always",
            risk_level="medium",
            sensitive_args=["api_key"],
        ), ff_connect),
        (ToolDef(
            name="ff_disconnect",
            description="Remove a connected FunnelFighters workspace by name or id.",
            parameters={"type": "object", "properties": {
                "workspace": {"type": "string", "description": "Workspace name or id to remove (see ff_workspaces)."},
            }, "required": ["workspace"]},
            policy="prompt_always",
            risk_level="medium",
        ), ff_disconnect),
    ]
