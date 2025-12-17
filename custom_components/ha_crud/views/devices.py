"""HTTP views for device discovery REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr

from ..const import (
    API_BASE_PATH_DEVICES,
    ERR_DEVICE_NOT_FOUND,
)

_LOGGER = logging.getLogger(__name__)


def _get_device_data(
    device: dr.DeviceEntry,
    area_registry: ar.AreaRegistry,
    floor_registry: fr.FloorRegistry,
    entity_count: int | None = None,
) -> dict[str, Any]:
    """Build device data dictionary.

    Args:
        device: Device registry entry
        area_registry: Area registry
        floor_registry: Floor registry
        entity_count: Optional pre-computed entity count

    Returns:
        Dictionary with device data
    """
    data: dict[str, Any] = {
        "id": device.id,
        "name": device.name_by_user or device.name,
        "name_by_user": device.name_by_user,
        "original_name": device.name,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "model_id": device.model_id,
        "sw_version": device.sw_version,
        "hw_version": device.hw_version,
        "serial_number": device.serial_number,
        "area_id": device.area_id,
        "via_device_id": device.via_device_id,
        "disabled": device.disabled,
        "disabled_by": device.disabled_by.value if device.disabled_by else None,
        "configuration_url": device.configuration_url,
    }

    # Add area and floor info
    if device.area_id:
        area = area_registry.async_get_area(device.area_id)
        if area:
            data["area_name"] = area.name
            data["floor_id"] = area.floor_id
            if area.floor_id:
                floor = floor_registry.async_get_floor(area.floor_id)
                if floor:
                    data["floor_name"] = floor.name

    # Add integration info from identifiers
    if device.identifiers:
        # Get the first identifier's domain as the integration
        for identifier in device.identifiers:
            if isinstance(identifier, (tuple, list)) and len(identifier) >= 1:
                data["integration"] = identifier[0]
                break

    # Add identifiers and connections
    data["identifiers"] = [list(i) if isinstance(i, (tuple, list)) else [i] for i in device.identifiers] if device.identifiers else []
    data["connections"] = [list(c) if isinstance(c, (tuple, list)) else [c] for c in device.connections] if device.connections else []

    if entity_count is not None:
        data["entity_count"] = entity_count

    return data


def _get_full_device_data(
    hass: HomeAssistant,
    device: dr.DeviceEntry,
    entity_registry: er.EntityRegistry,
    area_registry: ar.AreaRegistry,
    floor_registry: fr.FloorRegistry,
) -> dict[str, Any]:
    """Build full device data with entities.

    Args:
        hass: Home Assistant instance
        device: Device registry entry
        entity_registry: Entity registry
        area_registry: Area registry
        floor_registry: Floor registry

    Returns:
        Dictionary with full device data including entities
    """
    # Get device entities
    entities = []
    for entity_entry in er.async_entries_for_device(entity_registry, device.id):
        state = hass.states.get(entity_entry.entity_id)

        entity_data = {
            "entity_id": entity_entry.entity_id,
            "domain": entity_entry.entity_id.split(".")[0],
            "friendly_name": entity_entry.name or entity_entry.original_name or entity_entry.entity_id,
            "state": state.state if state else "unavailable",
            "device_class": entity_entry.device_class or entity_entry.original_device_class,
            "unit_of_measurement": state.attributes.get("unit_of_measurement") if state else None,
            "disabled": entity_entry.disabled,
            "entity_category": entity_entry.entity_category.value if entity_entry.entity_category else None,
        }
        entities.append(entity_data)

    # Build device data
    data = _get_device_data(device, area_registry, floor_registry, len(entities))

    # Add config entry info
    if device.config_entries:
        data["config_entry_ids"] = list(device.config_entries)

    # Add entities
    data["entities"] = sorted(entities, key=lambda x: x["entity_id"])

    return data


class DeviceListView(HomeAssistantView):
    """View to list all devices with optional filtering."""

    url = API_BASE_PATH_DEVICES
    name = "api:ha_crud:devices"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all devices.

        Query params:
            area: Filter by area_id
            floor: Filter by floor_id
            integration: Filter by integration domain
            manufacturer: Filter by manufacturer
            model: Filter by model
            include_disabled: Include disabled devices (default: false)

        Returns:
            200: JSON array of device data
        """
        hass: HomeAssistant = request.app["hass"]

        # Get query parameters
        area_filter = request.query.get("area")
        floor_filter = request.query.get("floor")
        integration_filter = request.query.get("integration")
        manufacturer_filter = request.query.get("manufacturer")
        model_filter = request.query.get("model")
        include_disabled = request.query.get("include_disabled", "false").lower() == "true"

        # Get registries
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        area_registry = ar.async_get(hass)
        floor_registry = fr.async_get(hass)

        # Build area-to-floor mapping for floor filtering
        area_to_floor: dict[str, str | None] = {}
        if floor_filter:
            for area in area_registry.async_list_areas():
                area_to_floor[area.id] = area.floor_id

        # Count entities per device
        device_entity_counts: dict[str, int] = {}
        for entity_entry in entity_registry.entities.values():
            if entity_entry.device_id:
                device_entity_counts[entity_entry.device_id] = (
                    device_entity_counts.get(entity_entry.device_id, 0) + 1
                )

        devices = []
        for device in device_registry.devices.values():
            # Skip disabled unless requested
            if device.disabled and not include_disabled:
                continue

            # Area filter
            if area_filter and device.area_id != area_filter:
                continue

            # Floor filter
            if floor_filter:
                if not device.area_id:
                    continue
                device_floor = area_to_floor.get(device.area_id)
                if device_floor != floor_filter:
                    continue

            # Manufacturer filter
            if manufacturer_filter and device.manufacturer != manufacturer_filter:
                continue

            # Model filter
            if model_filter and device.model != model_filter:
                continue

            # Integration filter - check identifiers
            if integration_filter:
                has_integration = False
                for identifier in device.identifiers:
                    if isinstance(identifier, (tuple, list)) and len(identifier) >= 1:
                        if identifier[0] == integration_filter:
                            has_integration = True
                            break
                if not has_integration:
                    continue

            # Build device data
            entity_count = device_entity_counts.get(device.id, 0)
            device_data = _get_device_data(device, area_registry, floor_registry, entity_count)
            devices.append(device_data)

        # Sort by name
        devices.sort(key=lambda x: (x.get("name") or "").lower())

        return self.json(devices)


class DeviceDetailView(HomeAssistantView):
    """View to get single device details with entities."""

    url = API_BASE_PATH_DEVICES + "/{device_id}"
    name = "api:ha_crud:device"
    requires_auth = True

    async def get(self, request: web.Request, device_id: str) -> web.Response:
        """Handle GET request - get device details with entities.

        Path params:
            device_id: The device ID

        Returns:
            200: Device details with entities array
            404: Device not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Get registries
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        area_registry = ar.async_get(hass)
        floor_registry = fr.async_get(hass)

        # Get device
        device = device_registry.async_get(device_id)
        if device is None:
            return self.json_message(
                f"Device '{device_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DEVICE_NOT_FOUND,
            )

        device_data = _get_full_device_data(
            hass,
            device,
            entity_registry,
            area_registry,
            floor_registry,
        )

        return self.json(device_data)
