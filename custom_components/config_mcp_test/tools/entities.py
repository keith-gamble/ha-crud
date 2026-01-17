"""MCP Tools for Entity Discovery.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)

from ..mcp_registry import mcp_tool
from ..validation import find_entity_usage

_LOGGER = logging.getLogger(__name__)


@mcp_tool(
    name="ha_list_entities",
    description=(
        "List all entities in Home Assistant with optional filtering. Returns "
        "entity_id, state, domain, friendly_name, device_id, area_id, platform, "
        "and more. Use filters to narrow results."
    ),
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Filter by domain (e.g., 'light', 'sensor', 'switch', 'climate')",
            },
            "area": {
                "type": "string",
                "description": "Filter by area_id",
            },
            "floor": {
                "type": "string",
                "description": "Filter by floor_id",
            },
            "device": {
                "type": "string",
                "description": "Filter by device_id",
            },
            "platform": {
                "type": "string",
                "description": "Filter by integration platform (e.g., 'hue', 'zwave_js')",
            },
            "device_class": {
                "type": "string",
                "description": "Filter by device_class (e.g., 'temperature', 'motion')",
            },
            "state": {
                "type": "string",
                "description": "Filter by current state (e.g., 'on', 'off', 'unavailable')",
            },
            "include_disabled": {
                "type": "boolean",
                "description": "Include disabled entities (default: false)",
                "default": False,
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Include hidden entities (default: false)",
                "default": False,
            },
        },
        "required": [],
    },
)
async def list_entities(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List entities with optional filtering."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)

    domain_filter = arguments.get("domain")
    area_filter = arguments.get("area")
    floor_filter = arguments.get("floor")
    device_filter = arguments.get("device")
    platform_filter = arguments.get("platform")
    device_class_filter = arguments.get("device_class")
    state_filter = arguments.get("state")
    include_disabled = arguments.get("include_disabled", False)
    include_hidden = arguments.get("include_hidden", False)

    # Build area-to-floor mapping
    area_to_floor: dict[str, str | None] = {}
    if floor_filter:
        for area in area_registry.async_list_areas():
            area_to_floor[area.id] = area.floor_id

    # Device area mappings
    device_to_area: dict[str, str | None] = {}
    for device in device_registry.devices.values():
        device_to_area[device.id] = device.area_id

    entities = []
    for state in hass.states.async_all():
        entity_id = state.entity_id
        domain = entity_id.split(".")[0]

        if domain_filter and domain != domain_filter:
            continue
        if state_filter and state.state != state_filter:
            continue

        entity_entry = entity_registry.async_get(entity_id)

        if entity_entry:
            if entity_entry.disabled and not include_disabled:
                continue
            if entity_entry.hidden_by and not include_hidden:
                continue
            if platform_filter and entity_entry.platform != platform_filter:
                continue

            device_class = entity_entry.device_class or entity_entry.original_device_class
            if device_class_filter and device_class != device_class_filter:
                continue
            if device_filter and entity_entry.device_id != device_filter:
                continue

            entity_area = entity_entry.area_id
            if not entity_area and entity_entry.device_id:
                entity_area = device_to_area.get(entity_entry.device_id)

            if area_filter and entity_area != area_filter:
                continue
            if floor_filter:
                if not entity_area:
                    continue
                if area_to_floor.get(entity_area) != floor_filter:
                    continue

        entities.append({
            "entity_id": entity_id,
            "state": state.state,
            "domain": domain,
            "friendly_name": state.attributes.get("friendly_name", entity_id),
            "device_id": entity_entry.device_id if entity_entry else None,
            "area_id": entity_entry.area_id if entity_entry else None,
            "platform": entity_entry.platform if entity_entry else None,
        })

    entities.sort(key=lambda x: x["entity_id"])
    return entities


@mcp_tool(
    name="ha_get_entity",
    description=(
        "Get full details for a specific entity including state, attributes, "
        "device info, area, and floor. Useful for understanding entity capabilities."
    ),
    schema={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The entity ID (e.g., 'light.living_room', 'sensor.temperature')",
            }
        },
        "required": ["entity_id"],
    },
)
async def get_entity(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get full entity details."""
    entity_id = arguments["entity_id"]
    state = hass.states.get(entity_id)
    if state is None:
        raise ValueError(f"Entity '{entity_id}' not found")

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)
    floor_registry = fr.async_get(hass)

    entity_entry = entity_registry.async_get(entity_id)
    domain = entity_id.split(".")[0]

    data: dict[str, Any] = {
        "entity_id": entity_id,
        "state": state.state,
        "domain": domain,
        "friendly_name": state.attributes.get("friendly_name", entity_id),
        "attributes": dict(state.attributes),
        "last_changed": state.last_changed.isoformat() if state.last_changed else None,
        "last_updated": state.last_updated.isoformat() if state.last_updated else None,
    }

    if entity_entry:
        data["device_id"] = entity_entry.device_id
        data["area_id"] = entity_entry.area_id
        data["platform"] = entity_entry.platform
        data["device_class"] = entity_entry.device_class
        data["icon"] = entity_entry.icon

        if entity_entry.device_id:
            device = device_registry.async_get(entity_entry.device_id)
            if device:
                data["device_name"] = device.name_by_user or device.name
                if not data.get("area_id") and device.area_id:
                    data["area_id"] = device.area_id

        if data.get("area_id"):
            area = area_registry.async_get_area(data["area_id"])
            if area:
                data["area_name"] = area.name
                data["floor_id"] = area.floor_id
                if area.floor_id:
                    floor = floor_registry.async_get_floor(area.floor_id)
                    if floor:
                        data["floor_name"] = floor.name

    return data


@mcp_tool(
    name="ha_list_domains",
    description=(
        "List all entity domains in Home Assistant with entity counts and "
        "descriptions. Useful for understanding what types of entities are available."
    ),
)
async def list_domains(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all entity domains with counts."""
    domain_counts: dict[str, int] = {}
    for state in hass.states.async_all():
        domain = state.entity_id.split(".")[0]
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

    domains = []
    for domain, count in sorted(domain_counts.items()):
        domains.append({
            "domain": domain,
            "count": count,
        })

    return domains


@mcp_tool(
    name="ha_list_domain_entities",
    description=(
        "List all entities for a specific domain with full attributes. "
        "More detailed than ha_list_entities with domain filter."
    ),
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The entity domain (e.g., 'light', 'sensor', 'climate', 'media_player')",
            },
            "include_disabled": {
                "type": "boolean",
                "description": "Include disabled entities (default: false)",
                "default": False,
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Include hidden entities (default: false)",
                "default": False,
            },
        },
        "required": ["domain"],
    },
)
async def list_domain_entities(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all entities for a specific domain with full attributes."""
    domain = arguments["domain"]
    entity_registry = er.async_get(hass)
    include_disabled = arguments.get("include_disabled", False)
    include_hidden = arguments.get("include_hidden", False)

    entities = []
    for state in hass.states.async_all():
        entity_id = state.entity_id
        if not entity_id.startswith(f"{domain}."):
            continue

        entity_entry = entity_registry.async_get(entity_id)

        if entity_entry:
            if entity_entry.disabled and not include_disabled:
                continue
            if entity_entry.hidden_by and not include_hidden:
                continue

        entities.append({
            "entity_id": entity_id,
            "state": state.state,
            "friendly_name": state.attributes.get("friendly_name", entity_id),
            "attributes": dict(state.attributes),
            "device_id": entity_entry.device_id if entity_entry else None,
            "area_id": entity_entry.area_id if entity_entry else None,
            "platform": entity_entry.platform if entity_entry else None,
            "device_class": entity_entry.device_class if entity_entry else None,
        })

    entities.sort(key=lambda x: x["entity_id"])
    return entities


@mcp_tool(
    name="ha_get_entity_usage",
    description=(
        "Find where an entity is used across Home Assistant resources. "
        "Searches dashboards, automations, scripts, and scenes to identify all "
        "references to the specified entity. Useful for impact analysis before "
        "modifying or removing an entity."
    ),
    schema={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The entity ID to search for (e.g., 'light.living_room', 'sensor.temperature')",
            }
        },
        "required": ["entity_id"],
    },
    permission="discovery_entities",
)
async def get_entity_usage(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Find where an entity is used across all resources."""
    entity_id = arguments["entity_id"]
    return await find_entity_usage(hass, entity_id)
