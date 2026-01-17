"""Schema validation for dashboard configurations."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
    LOVELACE_DATA,
)


def validate_url_path(value: str) -> str:
    """Validate dashboard URL path.

    Home Assistant requires dashboard URL paths to:
    - Contain at least one hyphen
    - Use only lowercase alphanumeric characters and hyphens
    - Start and end with alphanumeric characters
    """
    if not value:
        raise vol.Invalid("URL path cannot be empty")

    # Must contain hyphen (Home Assistant convention)
    if "-" not in value:
        raise vol.Invalid("URL path must contain a hyphen (-)")

    # Validate characters (lowercase, numbers, hyphens)
    if not all(c.isalnum() or c == "-" for c in value):
        raise vol.Invalid(
            "URL path must contain only lowercase letters, numbers, and hyphens"
        )

    if not value[0].isalnum() or not value[-1].isalnum():
        raise vol.Invalid("URL path must start and end with alphanumeric character")

    return value.lower()


# Schema for creating a new dashboard
CREATE_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL_PATH): validate_url_path,
        vol.Required(CONF_TITLE): cv.string,
        vol.Optional(CONF_ICON, default="mdi:view-dashboard"): cv.icon,
        vol.Optional(CONF_SHOW_IN_SIDEBAR, default=True): cv.boolean,
        vol.Optional(CONF_REQUIRE_ADMIN, default=False): cv.boolean,
    }
)


# Schema for full update (PUT) - title required, others optional
UPDATE_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TITLE): cv.string,
        vol.Optional(CONF_ICON): vol.Any(cv.icon, None),
        vol.Optional(CONF_SHOW_IN_SIDEBAR, default=True): cv.boolean,
        vol.Optional(CONF_REQUIRE_ADMIN, default=False): cv.boolean,
    }
)


# Schema for partial update (PATCH) - all fields optional
PATCH_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TITLE): cv.string,
        vol.Optional(CONF_ICON): vol.Any(cv.icon, None),
        vol.Optional(CONF_SHOW_IN_SIDEBAR): cv.boolean,
        vol.Optional(CONF_REQUIRE_ADMIN): cv.boolean,
    }
)


# Schema for dashboard content/configuration (views, cards, etc.)
DASHBOARD_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional("views"): list,
        vol.Optional("title"): cv.string,
        vol.Optional("background"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)


def validate_create_data(data: dict) -> dict:
    """Validate data for creating a dashboard."""
    return CREATE_DASHBOARD_SCHEMA(data)


def validate_update_data(data: dict) -> dict:
    """Validate data for full update."""
    return UPDATE_DASHBOARD_SCHEMA(data)


def validate_patch_data(data: dict) -> dict:
    """Validate data for partial update."""
    return PATCH_DASHBOARD_SCHEMA(data)


def validate_dashboard_config(config: dict) -> dict:
    """Validate dashboard configuration content."""
    return DASHBOARD_CONFIG_SCHEMA(config)


# Entity ID pattern: domain.object_id (e.g., light.living_room, sensor.temperature)
ENTITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")

# Keys that commonly contain entity references in Lovelace cards
ENTITY_KEYS = frozenset({
    "entity",
    "entity_id",
    "camera_entity",
    "camera_image",
    "media_player",
    "state_entity",
})

# Keys that contain lists of entities
ENTITY_LIST_KEYS = frozenset({
    "entities",
    "state_filter",
})


def _is_entity_id(value: Any) -> bool:
    """Check if a value looks like an entity ID."""
    if not isinstance(value, str):
        return False
    return bool(ENTITY_ID_PATTERN.match(value))


def extract_entity_references(config: Any, entities: set[str] | None = None) -> set[str]:
    """Recursively extract all entity IDs from a dashboard configuration.

    Scans the config structure for common entity reference patterns:
    - Direct entity fields (entity, entity_id, camera_image, etc.)
    - Entity lists (entities, state_filter, etc.)
    - Entities in nested objects (cards, conditions, actions, etc.)

    Args:
        config: The dashboard configuration (dict, list, or value)
        entities: Set to accumulate entity IDs (used in recursion)

    Returns:
        Set of all entity IDs found in the configuration
    """
    if entities is None:
        entities = set()

    if isinstance(config, dict):
        for key, value in config.items():
            # Check for single entity keys
            if key in ENTITY_KEYS and _is_entity_id(value):
                entities.add(value)
            # Check for entity list keys
            elif key in ENTITY_LIST_KEYS and isinstance(value, list):
                for item in value:
                    if _is_entity_id(item):
                        entities.add(item)
                    elif isinstance(item, dict):
                        # Handle {"entity": "...", ...} format in entities list
                        if "entity" in item and _is_entity_id(item["entity"]):
                            entities.add(item["entity"])
                        # Recurse into nested objects
                        extract_entity_references(item, entities)
            # Check for target.entity_id in service calls
            elif key == "target" and isinstance(value, dict):
                target_entity = value.get("entity_id")
                if _is_entity_id(target_entity):
                    entities.add(target_entity)
                elif isinstance(target_entity, list):
                    for eid in target_entity:
                        if _is_entity_id(eid):
                            entities.add(eid)
            # Recurse into nested structures
            else:
                extract_entity_references(value, entities)

    elif isinstance(config, list):
        for item in config:
            extract_entity_references(item, entities)

    return entities


def validate_dashboard_entities(
    hass: HomeAssistant,
    config: dict[str, Any],
) -> list[str]:
    """Check that all referenced entities exist in Home Assistant.

    Args:
        hass: Home Assistant instance
        config: Dashboard configuration to validate

    Returns:
        List of entity IDs that don't exist (empty if all exist)
    """
    referenced_entities = extract_entity_references(config)
    missing_entities = []

    for entity_id in sorted(referenced_entities):
        if hass.states.get(entity_id) is None:
            missing_entities.append(entity_id)

    return missing_entities


# =============================================================================
# Entity Usage Discovery
# =============================================================================

def extract_entity_locations(
    config: Any,
    current_path: str = "",
    locations: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Recursively extract entity IDs with their location paths.

    Args:
        config: The configuration to scan (dict, list, or value)
        current_path: Current path in the config structure (e.g., "views[0].cards[2]")
        locations: Dict to accumulate {entity_id: [path1, path2, ...]}

    Returns:
        Dict mapping entity IDs to list of paths where they appear
    """
    if locations is None:
        locations = {}

    def add_location(entity_id: str, path: str) -> None:
        if entity_id not in locations:
            locations[entity_id] = []
        locations[entity_id].append(path)

    if isinstance(config, dict):
        # Check for scene-style entities (dict keys are entity IDs)
        if current_path.endswith(".entities") or current_path == "entities":
            for key in config.keys():
                if _is_entity_id(key):
                    add_location(key, current_path)

        for key, value in config.items():
            child_path = f"{current_path}.{key}" if current_path else key

            # Check for single entity keys
            if key in ENTITY_KEYS and _is_entity_id(value):
                add_location(value, child_path)
            # Check for entity list keys
            elif key in ENTITY_LIST_KEYS and isinstance(value, list):
                for idx, item in enumerate(value):
                    item_path = f"{child_path}[{idx}]"
                    if _is_entity_id(item):
                        add_location(item, item_path)
                    elif isinstance(item, dict):
                        if "entity" in item and _is_entity_id(item["entity"]):
                            add_location(item["entity"], f"{item_path}.entity")
                        extract_entity_locations(item, item_path, locations)
            # Check for target.entity_id in service calls
            elif key == "target" and isinstance(value, dict):
                target_entity = value.get("entity_id")
                target_path = f"{child_path}.entity_id"
                if _is_entity_id(target_entity):
                    add_location(target_entity, target_path)
                elif isinstance(target_entity, list):
                    for idx, eid in enumerate(target_entity):
                        if _is_entity_id(eid):
                            add_location(eid, f"{target_path}[{idx}]")
            # Recurse into nested structures
            else:
                extract_entity_locations(value, child_path, locations)

    elif isinstance(config, list):
        for idx, item in enumerate(config):
            item_path = f"{current_path}[{idx}]"
            extract_entity_locations(item, item_path, locations)

    return locations


async def find_entity_usage_in_dashboards(
    hass: HomeAssistant,
    entity_id: str,
) -> list[dict[str, Any]]:
    """Find where an entity is used in dashboards.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to search for

    Returns:
        List of dicts with dashboard info and locations
    """
    results = []
    lovelace_data = hass.data.get(LOVELACE_DATA)

    if not lovelace_data:
        return results

    for url_path, dashboard in lovelace_data.dashboards.items():
        try:
            config = await dashboard.async_load(force=False)
            if config:
                all_locations = extract_entity_locations(config)
                if entity_id in all_locations:
                    info = await dashboard.async_get_info()
                    results.append({
                        "id": url_path if url_path else "lovelace",
                        "title": info.get("title", url_path or "Home"),
                        "locations": all_locations[entity_id],
                    })
        except Exception:
            # Dashboard config might not exist or be loadable
            pass

    return results


async def find_entity_usage_in_automations(
    hass: HomeAssistant,
    entity_id: str,
) -> list[dict[str, Any]]:
    """Find where an entity is used in automations.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to search for

    Returns:
        List of dicts with automation info and locations
    """
    results = []

    # Get automation component
    component = hass.data.get("automation")
    if component is None or not hasattr(component, "entities"):
        return results

    for entity in component.entities:
        if hasattr(entity, "raw_config") and entity.raw_config:
            config = entity.raw_config
            all_locations = extract_entity_locations(config)
            if entity_id in all_locations:
                results.append({
                    "id": config.get("id", entity.entity_id),
                    "alias": config.get("alias", entity.name or entity.entity_id),
                    "entity_id": entity.entity_id,
                    "locations": all_locations[entity_id],
                })

    return results


async def find_entity_usage_in_scripts(
    hass: HomeAssistant,
    entity_id: str,
) -> list[dict[str, Any]]:
    """Find where an entity is used in scripts.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to search for

    Returns:
        List of dicts with script info and locations
    """
    results = []

    # Get script component
    component = hass.data.get("script")
    if component is None or not hasattr(component, "entities"):
        return results

    for entity in component.entities:
        if hasattr(entity, "raw_config") and entity.raw_config:
            config = entity.raw_config
            all_locations = extract_entity_locations(config)
            if entity_id in all_locations:
                # Extract script ID from entity_id (script.my_script -> my_script)
                script_id = entity.entity_id.split(".", 1)[1] if "." in entity.entity_id else entity.entity_id
                results.append({
                    "id": script_id,
                    "alias": config.get("alias", entity.name or script_id),
                    "entity_id": entity.entity_id,
                    "locations": all_locations[entity_id],
                })

    return results


async def find_entity_usage_in_scenes(
    hass: HomeAssistant,
    entity_id: str,
) -> list[dict[str, Any]]:
    """Find where an entity is used in scenes.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to search for

    Returns:
        List of dicts with scene info and locations
    """
    results = []

    # Get scene component
    component = hass.data.get("scene")
    if component is None or not hasattr(component, "entities"):
        return results

    for entity in component.entities:
        config = None
        # Try different config access patterns
        if hasattr(entity, "scene_config") and entity.scene_config:
            config = entity.scene_config
        elif hasattr(entity, "_config") and entity._config:
            config = entity._config

        if config:
            # Scenes store entities directly as a dict
            entities_dict = config.get("entities", {})
            if entity_id in entities_dict:
                # Extract scene ID from entity_id (scene.my_scene -> my_scene)
                scene_id = entity.entity_id.split(".", 1)[1] if "." in entity.entity_id else entity.entity_id
                results.append({
                    "id": config.get("id", scene_id),
                    "name": config.get("name", entity.name or scene_id),
                    "entity_id": entity.entity_id,
                    "locations": ["entities"],
                })

    return results


async def find_entity_usage(
    hass: HomeAssistant,
    entity_id: str,
) -> dict[str, Any]:
    """Find where an entity is used across all resources.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to search for

    Returns:
        Dict with usage info across dashboards, automations, scripts, and scenes
    """
    dashboards = await find_entity_usage_in_dashboards(hass, entity_id)
    automations = await find_entity_usage_in_automations(hass, entity_id)
    scripts = await find_entity_usage_in_scripts(hass, entity_id)
    scenes = await find_entity_usage_in_scenes(hass, entity_id)

    # Calculate total references
    total = (
        sum(len(d.get("locations", [])) for d in dashboards) +
        sum(len(a.get("locations", [])) for a in automations) +
        sum(len(s.get("locations", [])) for s in scripts) +
        sum(len(s.get("locations", [])) for s in scenes)
    )

    return {
        "entity_id": entity_id,
        "usage": {
            "dashboards": dashboards,
            "automations": automations,
            "scripts": scripts,
            "scenes": scenes,
        },
        "total_references": total,
    }
