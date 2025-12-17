"""HTTP views for area and floor discovery REST API."""

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
    API_BASE_PATH_AREAS,
    API_BASE_PATH_FLOORS,
    ERR_AREA_NOT_FOUND,
    ERR_FLOOR_NOT_FOUND,
)

_LOGGER = logging.getLogger(__name__)


class AreaListView(HomeAssistantView):
    """View to list all areas."""

    url = API_BASE_PATH_AREAS
    name = "api:ha_crud:areas"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all areas.

        Query params:
            floor: Filter by floor_id

        Returns:
            200: JSON array of area data
        """
        hass: HomeAssistant = request.app["hass"]

        floor_filter = request.query.get("floor")

        # Get registries
        area_registry = ar.async_get(hass)
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        floor_registry = fr.async_get(hass)

        # Count devices and entities per area
        area_device_counts: dict[str, int] = {}
        area_entity_counts: dict[str, int] = {}

        for device in device_registry.devices.values():
            if device.area_id and not device.disabled:
                area_device_counts[device.area_id] = area_device_counts.get(device.area_id, 0) + 1

        for entity in entity_registry.entities.values():
            area_id = entity.area_id
            # If entity doesn't have area, check its device
            if not area_id and entity.device_id:
                device = device_registry.async_get(entity.device_id)
                if device:
                    area_id = device.area_id
            if area_id and not entity.disabled:
                area_entity_counts[area_id] = area_entity_counts.get(area_id, 0) + 1

        areas = []
        for area in area_registry.async_list_areas():
            # Floor filter
            if floor_filter and area.floor_id != floor_filter:
                continue

            area_data: dict[str, Any] = {
                "id": area.id,
                "name": area.name,
                "floor_id": area.floor_id,
                "icon": area.icon,
                "picture": area.picture,
                "aliases": list(area.aliases) if area.aliases else [],
                "device_count": area_device_counts.get(area.id, 0),
                "entity_count": area_entity_counts.get(area.id, 0),
            }

            # Add floor name if available
            if area.floor_id:
                floor = floor_registry.async_get_floor(area.floor_id)
                if floor:
                    area_data["floor_name"] = floor.name

            areas.append(area_data)

        # Sort by name
        areas.sort(key=lambda x: x["name"].lower())

        return self.json(areas)


class AreaDetailView(HomeAssistantView):
    """View to get single area details with devices and entities."""

    url = API_BASE_PATH_AREAS + "/{area_id}"
    name = "api:ha_crud:area"
    requires_auth = True

    async def get(self, request: web.Request, area_id: str) -> web.Response:
        """Handle GET request - get area details.

        Path params:
            area_id: The area ID

        Returns:
            200: Area details with devices and entities
            404: Area not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Get registries
        area_registry = ar.async_get(hass)
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        floor_registry = fr.async_get(hass)

        # Get area
        area = area_registry.async_get_area(area_id)
        if area is None:
            return self.json_message(
                f"Area '{area_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_AREA_NOT_FOUND,
            )

        # Build area data
        area_data: dict[str, Any] = {
            "id": area.id,
            "name": area.name,
            "floor_id": area.floor_id,
            "icon": area.icon,
            "picture": area.picture,
            "aliases": list(area.aliases) if area.aliases else [],
        }

        # Add floor name
        if area.floor_id:
            floor = floor_registry.async_get_floor(area.floor_id)
            if floor:
                area_data["floor_name"] = floor.name

        # Get devices in this area
        devices = []
        for device in device_registry.devices.values():
            if device.area_id == area_id and not device.disabled:
                devices.append({
                    "id": device.id,
                    "name": device.name_by_user or device.name,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                })
        area_data["devices"] = sorted(devices, key=lambda x: (x.get("name") or "").lower())

        # Get entities in this area (directly assigned or via device)
        entities = []
        entity_domains: dict[str, int] = {}

        for entity in entity_registry.entities.values():
            if entity.disabled:
                continue

            entity_area = entity.area_id
            # If entity doesn't have area, check its device
            if not entity_area and entity.device_id:
                device = device_registry.async_get(entity.device_id)
                if device:
                    entity_area = device.area_id

            if entity_area == area_id:
                state = hass.states.get(entity.entity_id)
                domain = entity.entity_id.split(".")[0]

                entities.append({
                    "entity_id": entity.entity_id,
                    "friendly_name": entity.name or entity.original_name or entity.entity_id,
                    "domain": domain,
                    "state": state.state if state else "unavailable",
                })

                # Count by domain
                entity_domains[domain] = entity_domains.get(domain, 0) + 1

        area_data["entities"] = sorted(entities, key=lambda x: x["entity_id"])
        area_data["entity_summary"] = dict(sorted(entity_domains.items()))

        return self.json(area_data)


class FloorListView(HomeAssistantView):
    """View to list all floors."""

    url = API_BASE_PATH_FLOORS
    name = "api:ha_crud:floors"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all floors.

        Returns:
            200: JSON array of floor data
        """
        hass: HomeAssistant = request.app["hass"]

        # Get registries
        area_registry = ar.async_get(hass)
        floor_registry = fr.async_get(hass)

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
                "aliases": list(floor.aliases) if floor.aliases else [],
                "area_count": floor_area_counts.get(floor.floor_id, 0),
            })

        # Sort by level
        floors.sort(key=lambda x: (x.get("level") or 0, x["name"].lower()))

        return self.json(floors)


class FloorDetailView(HomeAssistantView):
    """View to get single floor details with areas."""

    url = API_BASE_PATH_FLOORS + "/{floor_id}"
    name = "api:ha_crud:floor"
    requires_auth = True

    async def get(self, request: web.Request, floor_id: str) -> web.Response:
        """Handle GET request - get floor details with areas.

        Path params:
            floor_id: The floor ID

        Returns:
            200: Floor details with areas
            404: Floor not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Get registries
        area_registry = ar.async_get(hass)
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        floor_registry = fr.async_get(hass)

        # Get floor
        floor = floor_registry.async_get_floor(floor_id)
        if floor is None:
            return self.json_message(
                f"Floor '{floor_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_FLOOR_NOT_FOUND,
            )

        # Count devices and entities per area
        area_device_counts: dict[str, int] = {}
        area_entity_counts: dict[str, int] = {}

        for device in device_registry.devices.values():
            if device.area_id and not device.disabled:
                area_device_counts[device.area_id] = area_device_counts.get(device.area_id, 0) + 1

        for entity in entity_registry.entities.values():
            area_id = entity.area_id
            if not area_id and entity.device_id:
                device = device_registry.async_get(entity.device_id)
                if device:
                    area_id = device.area_id
            if area_id and not entity.disabled:
                area_entity_counts[area_id] = area_entity_counts.get(area_id, 0) + 1

        # Build floor data
        floor_data: dict[str, Any] = {
            "id": floor.floor_id,
            "name": floor.name,
            "level": floor.level,
            "icon": floor.icon,
            "aliases": list(floor.aliases) if floor.aliases else [],
        }

        # Get areas on this floor
        areas = []
        for area in area_registry.async_list_areas():
            if area.floor_id == floor_id:
                areas.append({
                    "id": area.id,
                    "name": area.name,
                    "icon": area.icon,
                    "device_count": area_device_counts.get(area.id, 0),
                    "entity_count": area_entity_counts.get(area.id, 0),
                })

        floor_data["areas"] = sorted(areas, key=lambda x: x["name"].lower())

        return self.json(floor_data)
