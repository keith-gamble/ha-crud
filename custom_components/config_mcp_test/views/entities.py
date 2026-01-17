"""HTTP views for entity discovery REST API."""

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
    API_BASE_PATH_ENTITIES,
    ERR_DOMAIN_NOT_FOUND,
    ERR_ENTITY_NOT_FOUND,
)
from ..validation import find_entity_usage

_LOGGER = logging.getLogger(__name__)


def _get_entity_data(
    hass: HomeAssistant,
    entity_id: str,
    entity_entry: er.RegistryEntry | None,
    include_attributes: bool = True,
) -> dict[str, Any]:
    """Build entity data dictionary.

    Args:
        hass: Home Assistant instance
        entity_id: The entity ID
        entity_entry: Entity registry entry (may be None for entities not in registry)
        include_attributes: Whether to include full attributes

    Returns:
        Dictionary with entity data
    """
    state = hass.states.get(entity_id)
    domain = entity_id.split(".")[0]

    # Base data from state
    data: dict[str, Any] = {
        "entity_id": entity_id,
        "state": state.state if state else "unavailable",
        "domain": domain,
    }

    # Add friendly name from state attributes or registry
    if state and state.attributes.get("friendly_name"):
        data["friendly_name"] = state.attributes.get("friendly_name")
    elif entity_entry and entity_entry.name:
        data["friendly_name"] = entity_entry.name
    else:
        data["friendly_name"] = entity_id

    # Add registry data if available
    if entity_entry:
        data["device_id"] = entity_entry.device_id
        data["area_id"] = entity_entry.area_id
        data["platform"] = entity_entry.platform
        data["device_class"] = entity_entry.device_class or entity_entry.original_device_class
        data["icon"] = entity_entry.icon or entity_entry.original_icon
        data["disabled"] = entity_entry.disabled
        data["hidden"] = entity_entry.hidden_by is not None
        data["entity_category"] = (
            entity_entry.entity_category.value if entity_entry.entity_category else None
        )

    # Add state attributes
    if state and include_attributes:
        # Common attributes
        data["unit_of_measurement"] = state.attributes.get("unit_of_measurement")
        data["last_changed"] = state.last_changed.isoformat() if state.last_changed else None
        data["last_updated"] = state.last_updated.isoformat() if state.last_updated else None

        # Include all attributes
        data["attributes"] = dict(state.attributes)
        # Remove friendly_name from attributes since it's top-level
        data["attributes"].pop("friendly_name", None)

    return data


def _get_full_entity_data(
    hass: HomeAssistant,
    entity_id: str,
    entity_entry: er.RegistryEntry | None,
    device_registry: dr.DeviceRegistry,
    area_registry: ar.AreaRegistry,
    floor_registry: fr.FloorRegistry,
) -> dict[str, Any]:
    """Build full entity data with device/area/floor names.

    Args:
        hass: Home Assistant instance
        entity_id: The entity ID
        entity_entry: Entity registry entry
        device_registry: Device registry
        area_registry: Area registry
        floor_registry: Floor registry

    Returns:
        Dictionary with full entity data
    """
    data = _get_entity_data(hass, entity_id, entity_entry, include_attributes=True)

    # Add device info
    if entity_entry and entity_entry.device_id:
        device = device_registry.async_get(entity_entry.device_id)
        if device:
            data["device_name"] = device.name_by_user or device.name
            data["integration"] = device.primary_config_entry

            # Get area from device if entity doesn't have one
            if not data.get("area_id") and device.area_id:
                data["area_id"] = device.area_id

    # Add area info
    if data.get("area_id"):
        area = area_registry.async_get_area(data["area_id"])
        if area:
            data["area_name"] = area.name
            data["floor_id"] = area.floor_id
            if area.floor_id:
                floor = floor_registry.async_get_floor(area.floor_id)
                if floor:
                    data["floor_name"] = floor.name

    # Add supported features as list if available
    state = hass.states.get(entity_id)
    if state:
        supported_features = state.attributes.get("supported_features")
        if supported_features:
            data["supported_features"] = supported_features

    return data


class EntityListView(HomeAssistantView):
    """View to list all entities with optional filtering."""

    url = API_BASE_PATH_ENTITIES
    name = "api:config_mcp:entities"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all entities.

        Query params:
            domain: Filter by domain (e.g., 'light', 'sensor')
            area: Filter by area_id
            floor: Filter by floor_id
            device: Filter by device_id
            platform: Filter by integration platform
            device_class: Filter by device_class
            state: Filter by current state
            include_disabled: Include disabled entities (default: false)
            include_hidden: Include hidden entities (default: false)

        Returns:
            200: JSON array of entity data
        """
        hass: HomeAssistant = request.app["hass"]

        # Get query parameters
        domain_filter = request.query.get("domain")
        area_filter = request.query.get("area")
        floor_filter = request.query.get("floor")
        device_filter = request.query.get("device")
        platform_filter = request.query.get("platform")
        device_class_filter = request.query.get("device_class")
        state_filter = request.query.get("state")
        include_disabled = request.query.get("include_disabled", "false").lower() == "true"
        include_hidden = request.query.get("include_hidden", "false").lower() == "true"

        # Get registries
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        area_registry = ar.async_get(hass)
        floor_registry = fr.async_get(hass)

        # Build area-to-floor mapping for floor filtering
        area_to_floor: dict[str, str | None] = {}
        if floor_filter:
            for area in area_registry.async_list_areas():
                area_to_floor[area.id] = area.floor_id

        # Get device area mappings for entities without direct area
        device_to_area: dict[str, str | None] = {}
        for device in device_registry.devices.values():
            device_to_area[device.id] = device.area_id

        entities = []

        # Iterate through all states
        for state in hass.states.async_all():
            entity_id = state.entity_id
            domain = entity_id.split(".")[0]

            # Domain filter
            if domain_filter and domain != domain_filter:
                continue

            # State filter
            if state_filter and state.state != state_filter:
                continue

            # Get entity registry entry
            entity_entry = entity_registry.async_get(entity_id)

            # Skip disabled/hidden unless requested
            if entity_entry:
                if entity_entry.disabled and not include_disabled:
                    continue
                if entity_entry.hidden_by and not include_hidden:
                    continue

                # Platform filter
                if platform_filter and entity_entry.platform != platform_filter:
                    continue

                # Device class filter
                device_class = entity_entry.device_class or entity_entry.original_device_class
                if device_class_filter and device_class != device_class_filter:
                    continue

                # Device filter
                if device_filter and entity_entry.device_id != device_filter:
                    continue

                # Area filter - check entity area or device area
                entity_area = entity_entry.area_id
                if not entity_area and entity_entry.device_id:
                    entity_area = device_to_area.get(entity_entry.device_id)

                if area_filter and entity_area != area_filter:
                    continue

                # Floor filter - check area's floor
                if floor_filter:
                    if not entity_area:
                        continue
                    entity_floor = area_to_floor.get(entity_area)
                    if entity_floor != floor_filter:
                        continue
            else:
                # Entity not in registry - skip filters that require registry
                if platform_filter or device_class_filter or device_filter:
                    continue
                if area_filter or floor_filter:
                    continue

            # Build entity data (minimal for list view)
            entity_data = _get_entity_data(hass, entity_id, entity_entry, include_attributes=False)
            entities.append(entity_data)

        # Sort by entity_id
        entities.sort(key=lambda x: x["entity_id"])

        return self.json(entities)


class EntityDetailView(HomeAssistantView):
    """View to get single entity details."""

    url = API_BASE_PATH_ENTITIES + "/{entity_id}"
    name = "api:config_mcp:entity"
    requires_auth = True

    async def get(self, request: web.Request, entity_id: str) -> web.Response:
        """Handle GET request - get entity details.

        Path params:
            entity_id: The entity ID (e.g., 'light.living_room')

        Returns:
            200: Entity details with full attributes
            404: Entity not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Check if entity exists
        state = hass.states.get(entity_id)
        if state is None:
            return self.json_message(
                f"Entity '{entity_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_ENTITY_NOT_FOUND,
            )

        # Get registries
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        area_registry = ar.async_get(hass)
        floor_registry = fr.async_get(hass)

        entity_entry = entity_registry.async_get(entity_id)

        entity_data = _get_full_entity_data(
            hass,
            entity_id,
            entity_entry,
            device_registry,
            area_registry,
            floor_registry,
        )

        return self.json(entity_data)


class DomainListView(HomeAssistantView):
    """View to list all entity domains with counts."""

    url = API_BASE_PATH_ENTITIES + "/domains"
    name = "api:config_mcp:entities:domains"
    requires_auth = True

    # Domain descriptions for common domains
    DOMAIN_DESCRIPTIONS = {
        "light": "Lights and dimmers",
        "switch": "On/off switches",
        "sensor": "Sensors",
        "binary_sensor": "Binary sensors",
        "climate": "Climate devices",
        "cover": "Covers and blinds",
        "media_player": "Media players",
        "camera": "Cameras",
        "automation": "Automations",
        "script": "Scripts",
        "scene": "Scenes",
        "fan": "Fans",
        "lock": "Locks",
        "vacuum": "Vacuums",
        "humidifier": "Humidifiers",
        "water_heater": "Water heaters",
        "input_boolean": "Input booleans",
        "input_number": "Input numbers",
        "input_text": "Input text",
        "input_select": "Input selects",
        "input_datetime": "Input datetimes",
        "input_button": "Input buttons",
        "button": "Buttons",
        "number": "Numbers",
        "select": "Selects",
        "text": "Text inputs",
        "person": "People",
        "zone": "Zones",
        "device_tracker": "Device trackers",
        "weather": "Weather",
        "sun": "Sun",
        "alarm_control_panel": "Alarm panels",
        "remote": "Remotes",
        "update": "Updates",
        "siren": "Sirens",
        "stt": "Speech-to-text",
        "tts": "Text-to-speech",
        "conversation": "Conversation agents",
    }

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all domains with entity counts.

        Returns:
            200: JSON array of domain info
        """
        hass: HomeAssistant = request.app["hass"]

        # Count entities by domain
        domain_counts: dict[str, int] = {}
        for state in hass.states.async_all():
            domain = state.entity_id.split(".")[0]
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

        # Build response
        domains = []
        for domain, count in sorted(domain_counts.items()):
            domains.append({
                "domain": domain,
                "count": count,
                "description": self.DOMAIN_DESCRIPTIONS.get(domain, f"{domain.replace('_', ' ').title()} entities"),
            })

        return self.json(domains)


class DomainEntitiesView(HomeAssistantView):
    """View to list entities for a specific domain."""

    url = API_BASE_PATH_ENTITIES + "/domains/{domain}"
    name = "api:config_mcp:entities:domain"
    requires_auth = True

    async def get(self, request: web.Request, domain: str) -> web.Response:
        """Handle GET request - list entities for a domain.

        Path params:
            domain: The entity domain (e.g., 'light', 'sensor')

        Query params:
            include_disabled: Include disabled entities (default: false)
            include_hidden: Include hidden entities (default: false)

        Returns:
            200: JSON array of entities for the domain
            404: Domain has no entities
        """
        hass: HomeAssistant = request.app["hass"]

        include_disabled = request.query.get("include_disabled", "false").lower() == "true"
        include_hidden = request.query.get("include_hidden", "false").lower() == "true"

        entity_registry = er.async_get(hass)

        entities = []
        for state in hass.states.async_all():
            entity_id = state.entity_id
            entity_domain = entity_id.split(".")[0]

            if entity_domain != domain:
                continue

            entity_entry = entity_registry.async_get(entity_id)

            # Skip disabled/hidden unless requested
            if entity_entry:
                if entity_entry.disabled and not include_disabled:
                    continue
                if entity_entry.hidden_by and not include_hidden:
                    continue

            entity_data = _get_entity_data(hass, entity_id, entity_entry, include_attributes=True)
            entities.append(entity_data)

        if not entities:
            return self.json_message(
                f"No entities found for domain '{domain}'",
                HTTPStatus.NOT_FOUND,
                ERR_DOMAIN_NOT_FOUND,
            )

        # Sort by entity_id
        entities.sort(key=lambda x: x["entity_id"])

        return self.json(entities)


class EntityUsageView(HomeAssistantView):
    """View to find where an entity is used across resources."""

    url = API_BASE_PATH_ENTITIES + "/{entity_id}/usage"
    name = "api:config_mcp:entity:usage"
    requires_auth = True

    async def get(self, request: web.Request, entity_id: str) -> web.Response:
        """Handle GET request - find where an entity is used.

        Path params:
            entity_id: The entity ID to search for (e.g., 'light.living_room')

        Returns:
            200: Usage info with references in dashboards, automations, scripts, scenes
        """
        hass: HomeAssistant = request.app["hass"]

        # Find usage across all resources
        usage_data = await find_entity_usage(hass, entity_id)

        return self.json(usage_data)
