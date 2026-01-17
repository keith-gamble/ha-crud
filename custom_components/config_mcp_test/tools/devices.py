"""MCP Tools for Device Discovery.

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


@mcp_tool(
    name="ha_list_devices",
    description=(
        "List all devices in Home Assistant with optional filtering. Returns "
        "device info including name, manufacturer, model, area, and entity count."
    ),
    schema={
        "type": "object",
        "properties": {
            "area": {
                "type": "string",
                "description": "Filter by area_id",
            },
            "floor": {
                "type": "string",
                "description": "Filter by floor_id",
            },
            "integration": {
                "type": "string",
                "description": "Filter by integration domain (e.g., 'hue', 'zwave_js', 'ring')",
            },
            "manufacturer": {
                "type": "string",
                "description": "Filter by manufacturer name",
            },
            "model": {
                "type": "string",
                "description": "Filter by model name",
            },
            "include_disabled": {
                "type": "boolean",
                "description": "Include disabled devices (default: false)",
                "default": False,
            },
        },
        "required": [],
    },
)
async def list_devices(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List devices with optional filtering."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    area_registry = ar.async_get(hass)

    area_filter = arguments.get("area")
    floor_filter = arguments.get("floor")
    integration_filter = arguments.get("integration")
    manufacturer_filter = arguments.get("manufacturer")
    model_filter = arguments.get("model")
    include_disabled = arguments.get("include_disabled", False)

    # Build area-to-floor mapping
    area_to_floor: dict[str, str | None] = {}
    for area in area_registry.async_list_areas():
        area_to_floor[area.id] = area.floor_id

    # Count entities per device
    device_entity_counts: dict[str, int] = {}
    for entry in entity_registry.entities.values():
        if entry.device_id:
            device_entity_counts[entry.device_id] = device_entity_counts.get(entry.device_id, 0) + 1

    devices = []
    for device in device_registry.devices.values():
        if device.disabled_by and not include_disabled:
            continue
        if area_filter and device.area_id != area_filter:
            continue
        if floor_filter:
            if not device.area_id:
                continue
            if area_to_floor.get(device.area_id) != floor_filter:
                continue
        if manufacturer_filter and device.manufacturer != manufacturer_filter:
            continue
        if model_filter and device.model != model_filter:
            continue

        # Check integration filter
        if integration_filter:
            has_integration = False
            for identifier in device.identifiers:
                if identifier[0] == integration_filter:
                    has_integration = True
                    break
            if not has_integration:
                for connection in device.connections:
                    if connection[0] == integration_filter:
                        has_integration = True
                        break
            if not has_integration:
                continue

        devices.append({
            "id": device.id,
            "name": device.name_by_user or device.name,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "area_id": device.area_id,
            "entity_count": device_entity_counts.get(device.id, 0),
        })

    devices.sort(key=lambda x: x["name"] or "")
    return devices


@mcp_tool(
    name="ha_get_device",
    description=(
        "Get full details for a specific device including all its entities. "
        "Useful for understanding what entities belong to a device."
    ),
    schema={
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "The device ID (UUID format)",
            }
        },
        "required": ["device_id"],
    },
)
async def get_device(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get full device details."""
    device_id = arguments["device_id"]
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    area_registry = ar.async_get(hass)
    floor_registry = fr.async_get(hass)

    device = device_registry.async_get(device_id)
    if device is None:
        raise ValueError(f"Device '{device_id}' not found")

    # Get device entities
    entities = []
    for entry in entity_registry.entities.values():
        if entry.device_id == device_id:
            state = hass.states.get(entry.entity_id)
            entities.append({
                "entity_id": entry.entity_id,
                "state": state.state if state else "unavailable",
                "friendly_name": state.attributes.get("friendly_name", entry.entity_id) if state else entry.entity_id,
            })

    data: dict[str, Any] = {
        "id": device.id,
        "name": device.name_by_user or device.name,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "sw_version": device.sw_version,
        "hw_version": device.hw_version,
        "area_id": device.area_id,
        "entities": entities,
    }

    if device.area_id:
        area = area_registry.async_get_area(device.area_id)
        if area:
            data["area_name"] = area.name
            data["floor_id"] = area.floor_id
            if area.floor_id:
                floor = floor_registry.async_get_floor(area.floor_id)
                if floor:
                    data["floor_name"] = floor.name

    return data
