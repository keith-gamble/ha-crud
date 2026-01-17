"""MCP Tools for Integrations.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
)

from ..mcp_registry import mcp_tool

_LOGGER = logging.getLogger(__name__)


@mcp_tool(
    name="ha_list_integrations",
    description=(
        "List all active integrations in Home Assistant. Returns integration info "
        "including name, config entry count, device/entity counts, and state."
    ),
)
async def list_integrations(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all active integrations."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    # Get config entries
    integrations: dict[str, dict[str, Any]] = {}

    for entry in hass.config_entries.async_entries():
        domain = entry.domain
        if domain not in integrations:
            integrations[domain] = {
                "domain": domain,
                "name": entry.title or domain,
                "config_entries": 0,
                "device_count": 0,
                "entity_count": 0,
            }
        integrations[domain]["config_entries"] += 1

    # Count devices per integration
    for device in device_registry.devices.values():
        for identifier in device.identifiers:
            domain = identifier[0]
            if domain in integrations:
                integrations[domain]["device_count"] += 1

    # Count entities per integration
    for entry in entity_registry.entities.values():
        if entry.platform in integrations:
            integrations[entry.platform]["entity_count"] += 1

    result = list(integrations.values())
    result.sort(key=lambda x: x["domain"])
    return result


@mcp_tool(
    name="ha_get_integration",
    description=(
        "Get full details for a specific integration including config entries, "
        "devices, and entity breakdown by domain."
    ),
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The integration domain (e.g., 'hue', 'zwave_js', 'ring', 'homekit')",
            }
        },
        "required": ["domain"],
    },
)
async def get_integration(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get full details for a specific integration."""
    domain = arguments["domain"]
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    # Find config entries for this domain
    entries = [e for e in hass.config_entries.async_entries() if e.domain == domain]
    if not entries:
        raise ValueError(f"Integration '{domain}' not found")

    # Get devices for this integration
    devices = []
    for device in device_registry.devices.values():
        for identifier in device.identifiers:
            if identifier[0] == domain:
                devices.append({
                    "id": device.id,
                    "name": device.name_by_user or device.name,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                })
                break

    # Count entities by domain for this integration
    entity_domains: dict[str, int] = {}
    for entry in entity_registry.entities.values():
        if entry.platform == domain:
            entity_domain = entry.entity_id.split(".")[0]
            entity_domains[entity_domain] = entity_domains.get(entity_domain, 0) + 1

    return {
        "domain": domain,
        "name": entries[0].title or domain,
        "config_entries": len(entries),
        "devices": devices,
        "entity_breakdown": entity_domains,
        "total_entities": sum(entity_domains.values()),
    }
