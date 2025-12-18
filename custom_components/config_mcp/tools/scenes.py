"""MCP Tools for Scenes.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from homeassistant.core import HomeAssistant

from ..mcp_registry import mcp_tool
from ..views.scenes import (
    get_scene_component,
    _format_scene,
    _load_scene_config,
    _save_scene_config,
    _reload_scenes,
    _cleanup_entity_registry,
    _find_scene_by_id,
    validate_entities,
)

_LOGGER = logging.getLogger(__name__)


@mcp_tool(
    name="ha_list_scenes",
    description=(
        "List all scenes in Home Assistant. Returns scene metadata including "
        "id, entity_id, name, and state."
    ),
    permission="scenes_read",
)
async def list_scenes(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all scenes."""
    component = get_scene_component(hass)
    if component is None:
        return []

    scenes = []
    for entity in component.entities:
        try:
            scenes.append(_format_scene(entity, include_config=False))
        except Exception as err:
            _LOGGER.warning("Error formatting scene %s: %s", entity.entity_id, err)
    return scenes


@mcp_tool(
    name="ha_get_scene",
    description=(
        "Get full details for a specific scene including its entity configuration "
        "(which entities and their states)."
    ),
    schema={
        "type": "object",
        "properties": {
            "scene_id": {
                "type": "string",
                "description": "The scene ID or full entity_id (e.g., 'scene.movie_night')",
            }
        },
        "required": ["scene_id"],
    },
    permission="scenes_read",
)
async def get_scene(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get a single scene with config."""
    scene_id = arguments["scene_id"]
    scenes = await _load_scene_config(hass)
    clean_id = scene_id.replace("scene.", "")

    # Find scene by ID in YAML
    _, scene_config = _find_scene_by_id(scenes, clean_id)

    if scene_config is not None:
        return {
            "id": scene_config.get("id"),
            "name": scene_config.get("name"),
            "icon": scene_config.get("icon"),
            "entities": scene_config.get("entities", {}),
        }

    # Try to find by entity_id
    entity_id = f"scene.{clean_id}" if not scene_id.startswith("scene.") else scene_id
    component = get_scene_component(hass)
    if component is None:
        raise ValueError(f"Scene '{scene_id}' not found")

    entity = component.get_entity(entity_id)
    if entity is None:
        raise ValueError(f"Scene '{scene_id}' not found")

    return _format_scene(entity, include_config=True)


@mcp_tool(
    name="ha_create_scene",
    description=(
        "Create a new scene. A scene stores the states of entities that can be "
        "activated together. Use ha_list_entities to discover valid entity_ids."
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Human-readable name for the scene (required)",
            },
            "id": {
                "type": "string",
                "description": "Scene ID (optional, auto-generated if not provided)",
            },
            "icon": {
                "type": "string",
                "description": "Material Design Icon (e.g., 'mdi:movie')",
            },
            "entities": {
                "type": "object",
                "description": "Object mapping entity_id to state configuration",
            },
        },
        "required": ["name"],
    },
    permission="scenes_create",
)
async def create_scene(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a new scene."""
    if "name" not in arguments:
        raise ValueError("Missing required field: name")

    scene_id = arguments.get("id", uuid.uuid4().hex)
    scenes = await _load_scene_config(hass)

    # Check for duplicates
    existing_idx, _ = _find_scene_by_id(scenes, scene_id)
    if existing_idx >= 0:
        raise ValueError(f"Scene with id '{scene_id}' already exists")

    # Build new scene
    new_scene: dict[str, Any] = {
        "id": scene_id,
        "name": arguments["name"],
    }

    if "icon" in arguments:
        new_scene["icon"] = arguments["icon"]

    entities = arguments.get("entities", {})
    new_scene["entities"] = entities

    # Validate entities exist
    entity_errors = validate_entities(hass, entities)
    if entity_errors:
        raise ValueError("Invalid entities:\n" + "\n".join(entity_errors))

    scenes.append(new_scene)
    await _save_scene_config(hass, scenes)
    await _reload_scenes(hass)

    entity_id = f"scene.{arguments['name'].lower().replace(' ', '_').replace('-', '_')}"
    return {"id": scene_id, "entity_id": entity_id, "message": "Scene created"}


@mcp_tool(
    name="ha_update_scene",
    description=(
        "Fully update a scene's configuration. Replaces the entire scene config."
    ),
    schema={
        "type": "object",
        "properties": {
            "scene_id": {
                "type": "string",
                "description": "The scene ID to update",
            },
            "name": {
                "type": "string",
                "description": "Human-readable name for the scene",
            },
            "icon": {
                "type": "string",
                "description": "Material Design Icon",
            },
            "entities": {
                "type": "object",
                "description": "Object mapping entity_id to state configuration",
            },
        },
        "required": ["scene_id", "entities"],
    },
    permission="scenes_update",
)
async def update_scene(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Full update of a scene."""
    scene_id = arguments["scene_id"]
    scenes = await _load_scene_config(hass)
    clean_id = scene_id.replace("scene.", "")

    existing_idx, existing_scene = _find_scene_by_id(scenes, clean_id)
    if existing_idx < 0:
        raise ValueError(f"Scene '{scene_id}' not found")

    updated: dict[str, Any] = {
        "id": clean_id,
        "name": arguments.get("name", existing_scene.get("name", clean_id)),
    }

    if "icon" in arguments:
        updated["icon"] = arguments["icon"]

    entities = arguments.get("entities", {})
    updated["entities"] = entities

    entity_errors = validate_entities(hass, entities)
    if entity_errors:
        raise ValueError("Invalid entities:\n" + "\n".join(entity_errors))

    scenes[existing_idx] = updated
    await _save_scene_config(hass, scenes)
    await _reload_scenes(hass)

    return {"id": clean_id, "name": updated.get("name"), "message": "Scene updated"}


@mcp_tool(
    name="ha_patch_scene",
    description="Partially update a scene. Only provided fields are updated.",
    schema={
        "type": "object",
        "properties": {
            "scene_id": {
                "type": "string",
                "description": "The scene ID to update",
            },
            "name": {
                "type": "string",
                "description": "New name for the scene (optional)",
            },
            "icon": {
                "type": "string",
                "description": "New icon (optional)",
            },
            "entities": {
                "type": "object",
                "description": "New entity configuration (optional)",
            },
        },
        "required": ["scene_id"],
    },
    permission="scenes_update",
)
async def patch_scene(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Partial update of a scene."""
    scene_id = arguments["scene_id"]
    scenes = await _load_scene_config(hass)
    clean_id = scene_id.replace("scene.", "")

    existing_idx, existing_scene = _find_scene_by_id(scenes, clean_id)
    if existing_idx < 0:
        raise ValueError(f"Scene '{scene_id}' not found")

    updated = existing_scene.copy()

    if "name" in arguments:
        updated["name"] = arguments["name"]
    if "icon" in arguments:
        updated["icon"] = arguments["icon"]
    if "entities" in arguments:
        updated["entities"] = arguments["entities"]
        entity_errors = validate_entities(hass, arguments["entities"])
        if entity_errors:
            raise ValueError("Invalid entities:\n" + "\n".join(entity_errors))

    scenes[existing_idx] = updated
    await _save_scene_config(hass, scenes)
    await _reload_scenes(hass)

    return {"id": clean_id, "name": updated.get("name"), "message": "Scene updated"}


@mcp_tool(
    name="ha_delete_scene",
    description="Delete a scene. This action cannot be undone.",
    schema={
        "type": "object",
        "properties": {
            "scene_id": {
                "type": "string",
                "description": "The scene ID to delete",
            }
        },
        "required": ["scene_id"],
    },
    permission="scenes_delete",
)
async def delete_scene(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Delete a scene."""
    scene_id = arguments["scene_id"]
    scenes = await _load_scene_config(hass)
    clean_id = scene_id.replace("scene.", "")

    existing_idx, existing_scene = _find_scene_by_id(scenes, clean_id)
    if existing_idx < 0:
        raise ValueError(f"Scene '{scene_id}' not found")

    # Get entity_id for registry cleanup
    scene_name = existing_scene.get("name", clean_id)
    entity_id = f"scene.{scene_name.lower().replace(' ', '_').replace('-', '_')}"

    scenes.pop(existing_idx)
    await _save_scene_config(hass, scenes)
    await _reload_scenes(hass)
    await _cleanup_entity_registry(hass, entity_id)

    return {"deleted": scene_id}


@mcp_tool(
    name="ha_activate_scene",
    description=(
        "Activate a scene, applying all the stored entity states. Can optionally "
        "specify a transition time."
    ),
    schema={
        "type": "object",
        "properties": {
            "scene_id": {
                "type": "string",
                "description": "The scene ID to activate",
            },
            "transition": {
                "type": "number",
                "description": "Transition time in seconds for lights and other entities that support it",
            },
        },
        "required": ["scene_id"],
    },
    permission="scenes_update",
)
async def activate_scene(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Activate a scene."""
    scene_id = arguments["scene_id"]
    scenes = await _load_scene_config(hass)
    clean_id = scene_id.replace("scene.", "")

    # Try to find by ID in YAML
    _, scene_config = _find_scene_by_id(scenes, clean_id)

    if scene_config is not None:
        # Found by ID - derive entity_id from name
        scene_name = scene_config.get("name", clean_id)
        entity_id = f"scene.{scene_name.lower().replace(' ', '_').replace('-', '_')}"
    else:
        # Try as entity_id directly
        entity_id = f"scene.{clean_id}" if not scene_id.startswith("scene.") else scene_id

    service_data: dict[str, Any] = {"entity_id": entity_id}
    if arguments.get("transition"):
        service_data["transition"] = arguments["transition"]

    await hass.services.async_call("scene", "turn_on", service_data, blocking=True)
    return {"entity_id": entity_id, "activated": True, "message": "Scene activated"}
