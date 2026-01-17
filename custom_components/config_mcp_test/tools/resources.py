"""MCP Tools for Lovelace Resources.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import LOVELACE_DATA
from ..mcp_registry import mcp_tool

_LOGGER = logging.getLogger(__name__)


@mcp_tool(
    name="ha_list_resources",
    description=(
        "List all Lovelace resources (custom cards, modules, CSS) installed via "
        "HACS or manually. Returns resource metadata including id, type "
        "(module/js/css/html), and url. Useful for understanding what custom UI "
        "components are available when generating dashboards."
    ),
    schema={
        "type": "object",
        "properties": {},
        "required": []
    },
    permission="dashboards_read",
)
async def list_resources(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all Lovelace resources (custom cards, modules, CSS)."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if not lovelace_data:
        return []

    resources = []
    try:
        resource_collection = lovelace_data.resources

        # Ensure storage collection is loaded
        if hasattr(resource_collection, 'loaded') and not resource_collection.loaded:
            if hasattr(resource_collection, 'async_load'):
                await resource_collection.async_load()
                resource_collection.loaded = True

        # async_items() is actually a synchronous method
        items = resource_collection.async_items()

        for item in items:
            resources.append({
                "id": item.get("id"),
                "type": item.get("type"),
                "url": item.get("url"),
            })
    except Exception as err:
        _LOGGER.warning("Error getting lovelace resources: %s", err)

    return resources
