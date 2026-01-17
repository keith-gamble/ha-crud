"""MCP Tools for Areas and Floors.

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

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Area Tools
# =============================================================================

@mcp_tool(
    name="ha_list_areas",
    description=(
        "List all areas in Home Assistant. Returns area info including name, "
        "floor, icon, and device/entity counts. Useful for organizing dashboards "
        "by location."
    ),
    schema={
        "type": "object",
        "properties": {
            "floor": {
                "type": "string",
                "description": "Filter by floor_id",
            }
        },
        "required": [],
    },
)
async def list_areas(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all areas."""
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    floor_filter = arguments.get("floor")

    # Count devices and entities per area
    area_device_counts: dict[str, int] = {}
    area_entity_counts: dict[str, int] = {}

    for device in device_registry.devices.values():
        if device.area_id:
            area_device_counts[device.area_id] = area_device_counts.get(device.area_id, 0) + 1

    for entry in entity_registry.entities.values():
        if entry.area_id:
            area_entity_counts[entry.area_id] = area_entity_counts.get(entry.area_id, 0) + 1

    areas = []
    for area in area_registry.async_list_areas():
        if floor_filter and area.floor_id != floor_filter:
            continue

        areas.append({
            "id": area.id,
            "name": area.name,
            "floor_id": area.floor_id,
            "icon": area.icon,
            "device_count": area_device_counts.get(area.id, 0),
            "entity_count": area_entity_counts.get(area.id, 0),
        })

    areas.sort(key=lambda x: x["name"])
    return areas


@mcp_tool(
    name="ha_get_area",
    description=(
        "Get full details for a specific area including all devices and entities "
        "in that area. Useful for building area-specific dashboards."
    ),
    schema={
        "type": "object",
        "properties": {
            "area_id": {
                "type": "string",
                "description": "The area ID (e.g., 'living_room', 'bedroom')",
            }
        },
        "required": ["area_id"],
    },
)
async def get_area(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get full area details."""
    area_id = arguments["area_id"]
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    floor_registry = fr.async_get(hass)

    area = area_registry.async_get_area(area_id)
    if area is None:
        raise ValueError(f"Area '{area_id}' not found")

    # Get devices in area
    devices = []
    for device in device_registry.devices.values():
        if device.area_id == area_id:
            devices.append({
                "id": device.id,
                "name": device.name_by_user or device.name,
            })

    # Get entities in area
    entities = []
    for entry in entity_registry.entities.values():
        if entry.area_id == area_id:
            state = hass.states.get(entry.entity_id)
            entities.append({
                "entity_id": entry.entity_id,
                "state": state.state if state else "unavailable",
            })

    data: dict[str, Any] = {
        "id": area.id,
        "name": area.name,
        "floor_id": area.floor_id,
        "icon": area.icon,
        "devices": devices,
        "entities": entities,
    }

    if area.floor_id:
        floor = floor_registry.async_get_floor(area.floor_id)
        if floor:
            data["floor_name"] = floor.name

    return data


# =============================================================================
# Floor Tools
# =============================================================================

@mcp_tool(
    name="ha_list_floors",
    description=(
        "List all floors in Home Assistant. Returns floor info including name, "
        "level, icon, and area count. Useful for multi-story home organization."
    ),
)
async def list_floors(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all floors."""
    floor_registry = fr.async_get(hass)
    area_registry = ar.async_get(hass)

    # Count areas per floor
    floor_area_counts: dict[str, int] = {}
    for area in area_registry.async_list_areas():
        if area.floor_id:
            floor_area_counts[area.floor_id] = floor_area_counts.get(area.floor_id, 0) + 1

    floors = []
    for floor in floor_registry.async_list_floors():
        floors.append({
            "id": floor.floor_id,
            "name": floor.name,
            "level": floor.level,
            "icon": floor.icon,
            "area_count": floor_area_counts.get(floor.floor_id, 0),
        })

    floors.sort(key=lambda x: x.get("level") or 0)
    return floors


@mcp_tool(
    name="ha_get_floor",
    description=(
        "Get full details for a specific floor including all areas on that floor. "
        "Useful for building floor-specific views."
    ),
    schema={
        "type": "object",
        "properties": {
            "floor_id": {
                "type": "string",
                "description": "The floor ID (e.g., 'ground_floor', 'upstairs')",
            }
        },
        "required": ["floor_id"],
    },
)
async def get_floor(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get full details for a specific floor."""
    floor_id = arguments["floor_id"]
    floor_registry = fr.async_get(hass)
    area_registry = ar.async_get(hass)

    floor = floor_registry.async_get_floor(floor_id)
    if floor is None:
        raise ValueError(f"Floor '{floor_id}' not found")

    # Get areas on this floor
    areas = []
    for area in area_registry.async_list_areas():
        if area.floor_id == floor_id:
            areas.append({
                "id": area.id,
                "name": area.name,
                "icon": area.icon,
            })

    return {
        "id": floor.floor_id,
        "name": floor.name,
        "level": floor.level,
        "icon": floor.icon,
        "areas": areas,
    }
