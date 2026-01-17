"""MCP Tools for Lovelace Dashboards.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    CONF_DASHBOARDS_VALIDATE,
    DATA_DASHBOARDS_COLLECTION,
    DEFAULT_OPTIONS,
    DOMAIN,
    LOVELACE_DATA,
    MODE_STORAGE,
    MODE_YAML,
    VALIDATE_NONE,
    VALIDATE_STRICT,
    VALIDATE_WARN,
)
from ..mcp_registry import mcp_tool
from ..validation import validate_dashboard_entities

_LOGGER = logging.getLogger(__name__)


def _get_config_options(hass: HomeAssistant) -> dict[str, Any]:
    """Get the current configuration options for config_mcp."""
    options = DEFAULT_OPTIONS.copy()
    if DOMAIN in hass.data:
        for entry_id in hass.data[DOMAIN]:
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.entry_id == entry_id:
                    options.update(entry.options)
                    break
    return options


# =============================================================================
# Dashboard List/Get Tools
# =============================================================================

@mcp_tool(
    name="ha_list_dashboards",
    description=(
        "List all Lovelace dashboards in Home Assistant. Returns an array of "
        "dashboard metadata including id, url_path, title, icon, mode "
        "(storage/yaml), and visibility settings."
    ),
    permission="dashboards_read",
)
async def list_dashboards(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all dashboards."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if not lovelace_data:
        return []

    dashboards = []
    for url_path, config in lovelace_data.dashboards.items():
        try:
            info = await config.async_get_info()
            dashboards.append({
                "id": url_path if url_path else "lovelace",
                "url_path": url_path,
                "mode": info.get("mode", MODE_STORAGE),
                "title": info.get("title"),
                "icon": info.get("icon"),
                "show_in_sidebar": info.get("show_in_sidebar", True),
                "require_admin": info.get("require_admin", False),
            })
        except Exception as err:
            _LOGGER.warning("Error getting info for dashboard %s: %s", url_path, err)

    return dashboards


@mcp_tool(
    name="ha_get_dashboard",
    description=(
        "Get metadata for a specific dashboard. Use 'lovelace' as the "
        "dashboard_id for the default dashboard."
    ),
    schema={
        "type": "object",
        "properties": {
            "dashboard_id": {
                "type": "string",
                "description": "Dashboard URL path (e.g., 'my-dashboard') or 'lovelace' for the default dashboard",
            }
        },
        "required": ["dashboard_id"],
    },
    permission="dashboards_read",
)
async def get_dashboard(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get single dashboard metadata."""
    dashboard_id = arguments["dashboard_id"]
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if not lovelace_data:
        raise ValueError(f"Dashboard '{dashboard_id}' not found")

    url_path = None if dashboard_id == "lovelace" else dashboard_id
    config = lovelace_data.dashboards.get(url_path)

    if config is None:
        raise ValueError(f"Dashboard '{dashboard_id}' not found")

    info = await config.async_get_info()
    return {
        "id": dashboard_id,
        "url_path": url_path,
        "mode": info.get("mode", MODE_STORAGE),
        "title": info.get("title"),
        "icon": info.get("icon"),
        "show_in_sidebar": info.get("show_in_sidebar", True),
        "require_admin": info.get("require_admin", False),
    }


@mcp_tool(
    name="ha_get_dashboard_config",
    description=(
        "Get the full configuration (views, cards, etc.) of a dashboard. "
        "This returns the actual dashboard content that defines what users see."
    ),
    schema={
        "type": "object",
        "properties": {
            "dashboard_id": {
                "type": "string",
                "description": "Dashboard URL path or 'lovelace' for default",
            }
        },
        "required": ["dashboard_id"],
    },
    permission="dashboards_read",
)
async def get_dashboard_config(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get dashboard configuration (views/cards)."""
    dashboard_id = arguments["dashboard_id"]
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if not lovelace_data:
        raise ValueError(f"Dashboard '{dashboard_id}' not found")

    url_path = None if dashboard_id == "lovelace" else dashboard_id
    config = lovelace_data.dashboards.get(url_path)

    if config is None:
        raise ValueError(f"Dashboard '{dashboard_id}' not found")

    return await config.async_load(force=False)


# =============================================================================
# Dashboard Create/Update/Delete Tools
# =============================================================================

@mcp_tool(
    name="ha_create_dashboard",
    description=(
        "Create a new Lovelace dashboard. Requires admin privileges. "
        "The url_path must contain a hyphen (e.g., 'my-dashboard')."
    ),
    schema={
        "type": "object",
        "properties": {
            "url_path": {
                "type": "string",
                "description": "Unique URL path for the dashboard. Must contain a hyphen (e.g., 'my-dashboard', 'home-view')",
            },
            "title": {
                "type": "string",
                "description": "Display title for the dashboard",
            },
            "icon": {
                "type": "string",
                "description": "Material Design Icon (e.g., 'mdi:view-dashboard')",
                "default": "mdi:view-dashboard",
            },
            "show_in_sidebar": {
                "type": "boolean",
                "description": "Whether to show this dashboard in the sidebar",
                "default": True,
            },
            "require_admin": {
                "type": "boolean",
                "description": "Whether only admins can view this dashboard",
                "default": False,
            },
        },
        "required": ["url_path", "title"],
    },
    permission="dashboards_create",
)
async def create_dashboard(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a new dashboard."""
    from homeassistant.components.lovelace.dashboard import LovelaceStorage
    from homeassistant.components.frontend import async_register_built_in_panel

    url_path = arguments["url_path"]
    title = arguments["title"]
    icon = arguments.get("icon", "mdi:view-dashboard")
    show_in_sidebar = arguments.get("show_in_sidebar", True)
    require_admin = arguments.get("require_admin", False)

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data and url_path in lovelace_data.dashboards:
        raise ValueError(f"Dashboard '{url_path}' already exists")

    # Create via collection
    collection = hass.data.get(DATA_DASHBOARDS_COLLECTION)
    if collection is None:
        raise ValueError("Dashboard collection not available")

    create_data = {
        "url_path": url_path,
        "title": title,
        "icon": icon,
        "show_in_sidebar": show_in_sidebar,
        "require_admin": require_admin,
    }
    await collection.async_create_item(create_data)

    # Register with frontend
    if lovelace_data:
        config = {
            "id": url_path,
            "url_path": url_path,
            "title": title,
            "icon": icon,
            "show_in_sidebar": show_in_sidebar,
            "require_admin": require_admin,
        }
        lovelace_data.dashboards[url_path] = LovelaceStorage(hass, config)

        async_register_built_in_panel(
            hass,
            "lovelace",
            config_panel_domain="lovelace",
            sidebar_title=title,
            sidebar_icon=icon,
            frontend_url_path=url_path,
            config={"mode": "storage"},
            require_admin=require_admin,
        )

    return {
        "id": url_path,
        "url_path": url_path,
        "title": title,
        "icon": icon,
        "show_in_sidebar": show_in_sidebar,
        "require_admin": require_admin,
        "mode": MODE_STORAGE,
    }


@mcp_tool(
    name="ha_update_dashboard_config",
    description=(
        "Replace the full configuration (views, cards) of a dashboard. "
        "This is how you upload dashboard JSON content. Requires admin privileges. "
        "Entity validation mode can be overridden with the 'validate' parameter."
    ),
    schema={
        "type": "object",
        "properties": {
            "dashboard_id": {
                "type": "string",
                "description": "Dashboard URL path or 'lovelace' for default",
            },
            "config": {
                "type": "object",
                "description": "Dashboard configuration object containing views array and optional settings",
            },
            "validate": {
                "type": "string",
                "enum": ["none", "warn", "strict"],
                "description": "Override entity validation mode. 'none' = skip validation, 'warn' = accept but return warnings, 'strict' = reject if entities missing. If not specified, uses global config setting.",
            },
        },
        "required": ["dashboard_id", "config"],
    },
    permission="dashboards_update",
)
async def update_dashboard_config(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Update dashboard configuration."""
    dashboard_id = arguments["dashboard_id"]
    config = arguments["config"]

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if not lovelace_data:
        raise ValueError(f"Dashboard '{dashboard_id}' not found")

    url_path = None if dashboard_id == "lovelace" else dashboard_id
    dashboard = lovelace_data.dashboards.get(url_path)

    if dashboard is None:
        raise ValueError(f"Dashboard '{dashboard_id}' not found")

    info = await dashboard.async_get_info()
    if info.get("mode") == MODE_YAML:
        raise ValueError(f"Dashboard '{dashboard_id}' is YAML-based and read-only")

    # Get validation mode from config, allow argument override
    options = _get_config_options(hass)
    default_validate_mode = options.get(CONF_DASHBOARDS_VALIDATE, VALIDATE_WARN)
    validate_mode = arguments.get("validate", default_validate_mode)

    # Validate entities if enabled
    missing_entities: list[str] = []
    if validate_mode != VALIDATE_NONE:
        missing_entities = validate_dashboard_entities(hass, config)

        # In strict mode, reject if any entities are missing
        if validate_mode == VALIDATE_STRICT and missing_entities:
            raise ValueError(
                f"Dashboard references {len(missing_entities)} missing entities: "
                f"{', '.join(missing_entities[:5])}{'...' if len(missing_entities) > 5 else ''}"
            )

    await dashboard.async_save(config)

    # Build response with optional warnings
    result = dict(config)
    if validate_mode == VALIDATE_WARN and missing_entities:
        result["warnings"] = {"missing_entities": missing_entities}

    return result


@mcp_tool(
    name="ha_delete_dashboard",
    description=(
        "Delete a dashboard. Cannot delete the default 'lovelace' dashboard "
        "or YAML-based dashboards. Requires admin privileges."
    ),
    schema={
        "type": "object",
        "properties": {
            "dashboard_id": {
                "type": "string",
                "description": "Dashboard URL path to delete (cannot be 'lovelace')",
            }
        },
        "required": ["dashboard_id"],
    },
    permission="dashboards_delete",
)
async def delete_dashboard(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Delete a dashboard."""
    from homeassistant.components.frontend import async_remove_panel

    dashboard_id = arguments["dashboard_id"]

    if dashboard_id == "lovelace":
        raise ValueError("Cannot delete the default dashboard")

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if not lovelace_data:
        raise ValueError(f"Dashboard '{dashboard_id}' not found")

    url_path = dashboard_id
    config = lovelace_data.dashboards.get(url_path)

    if config is None:
        raise ValueError(f"Dashboard '{dashboard_id}' not found")

    info = await config.async_get_info()
    if info.get("mode") == MODE_YAML:
        raise ValueError(f"Dashboard '{dashboard_id}' is YAML-based and cannot be deleted")

    # Delete via collection
    collection = hass.data.get(DATA_DASHBOARDS_COLLECTION)
    if collection:
        await collection.async_load()
        item_id = None
        for iid, item in collection.data.items():
            if item.get("url_path") == url_path:
                item_id = iid
                break
        if item_id:
            await collection.async_delete_item(item_id)

    # Remove from lovelace and frontend
    if url_path in lovelace_data.dashboards:
        del lovelace_data.dashboards[url_path]
    async_remove_panel(hass, url_path)

    return {"deleted": dashboard_id}
