"""MCP Tools for Scripts.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..mcp_registry import mcp_tool
from ..views.scripts import (
    get_script_component,
    _format_script,
    _load_script_config,
    _save_script_config,
    _reload_scripts,
    _cleanup_entity_registry,
    validate_sequence,
)

_LOGGER = logging.getLogger(__name__)


@mcp_tool(
    name="ha_list_scripts",
    description=(
        "List all scripts in Home Assistant. Returns script metadata including "
        "id, entity_id, alias, state, and mode."
    ),
    permission="scripts_read",
)
async def list_scripts(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all scripts."""
    component = get_script_component(hass)
    if component is None:
        return []

    scripts = []
    for entity in component.entities:
        try:
            scripts.append(_format_script(entity, hass=hass, include_config=False))
        except Exception as err:
            _LOGGER.warning("Error formatting script %s: %s", entity.entity_id, err)
    return scripts


@mcp_tool(
    name="ha_get_script",
    description=(
        "Get full details for a specific script including its sequence of actions."
    ),
    schema={
        "type": "object",
        "properties": {
            "script_id": {
                "type": "string",
                "description": "The script ID or entity_id",
            }
        },
        "required": ["script_id"],
    },
    permission="scripts_read",
)
async def get_script(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get a single script with config."""
    script_id = arguments["script_id"]
    entity_id = f"script.{script_id}" if not script_id.startswith("script.") else script_id
    component = get_script_component(hass)
    if component is None:
        raise ValueError(f"Script '{script_id}' not found")

    entity = component.get_entity(entity_id)
    if entity is None:
        raise ValueError(f"Script '{script_id}' not found")

    return _format_script(entity, hass=hass, include_config=True)


@mcp_tool(
    name="ha_create_script",
    description=(
        "Create a new script. Sequence actions must use valid services."
    ),
    schema={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Script ID (derived from alias if not provided)",
            },
            "alias": {
                "type": "string",
                "description": "Human-readable name for the script",
            },
            "description": {"type": "string"},
            "icon": {"type": "string"},
            "mode": {
                "type": "string",
                "description": "Execution mode: single, restart, queued, parallel",
            },
            "fields": {
                "type": "object",
                "description": "Input fields/parameters for the script",
            },
            "sequence": {
                "type": "array",
                "description": "List of actions to execute",
            },
        },
        "required": ["alias"],
    },
    permission="scripts_create",
)
async def create_script(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a new script."""
    if "alias" not in arguments and "id" not in arguments:
        raise ValueError("Missing required field: alias or id")

    if "id" in arguments:
        script_id = arguments["id"]
    else:
        script_id = arguments["alias"].lower().replace(" ", "_").replace("-", "_")
        script_id = "".join(c for c in script_id if c.isalnum() or c == "_")

    scripts = await _load_script_config(hass)
    if script_id in scripts:
        raise ValueError(f"Script with id '{script_id}' already exists")

    new_script: dict[str, Any] = {}
    for field in ["alias", "description", "icon", "mode", "max", "max_exceeded", "fields", "variables"]:
        if field in arguments:
            new_script[field] = arguments[field]

    new_script["sequence"] = arguments.get("sequence", [])

    sequence_errors = validate_sequence(hass, new_script["sequence"])
    if sequence_errors:
        raise ValueError("Invalid actions in sequence:\n" + "\n".join(sequence_errors))

    scripts[script_id] = new_script
    await _save_script_config(hass, scripts)
    await _reload_scripts(hass)

    return {"id": script_id, "entity_id": f"script.{script_id}", "message": "Script created"}


@mcp_tool(
    name="ha_update_script",
    description="Fully update a script's configuration.",
    schema={
        "type": "object",
        "properties": {
            "script_id": {
                "type": "string",
                "description": "The script ID to update",
            },
            "alias": {"type": "string"},
            "description": {"type": "string"},
            "icon": {"type": "string"},
            "mode": {"type": "string"},
            "fields": {"type": "object"},
            "sequence": {"type": "array"},
        },
        "required": ["script_id"],
    },
    permission="scripts_update",
)
async def update_script(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Full update of a script."""
    script_id = arguments["script_id"]
    clean_id = script_id.replace("script.", "")
    scripts = await _load_script_config(hass)

    if clean_id not in scripts:
        raise ValueError(f"Script '{script_id}' not found")

    updated: dict[str, Any] = {}
    for field in ["alias", "description", "icon", "mode", "max", "max_exceeded", "fields", "variables"]:
        if field in arguments:
            updated[field] = arguments[field]

    updated["sequence"] = arguments.get("sequence", [])

    sequence_errors = validate_sequence(hass, updated["sequence"])
    if sequence_errors:
        raise ValueError("Invalid actions in sequence:\n" + "\n".join(sequence_errors))

    scripts[clean_id] = updated
    await _save_script_config(hass, scripts)
    await _reload_scripts(hass)

    return {"id": clean_id, "entity_id": f"script.{clean_id}", "message": "Script updated"}


@mcp_tool(
    name="ha_patch_script",
    description=(
        "Partially update a script. Only provided fields are updated. "
        "Use category_id to assign a category (from ha_list_categories with scope='script'). "
        "Use labels to assign labels."
    ),
    schema={
        "type": "object",
        "properties": {
            "script_id": {
                "type": "string",
                "description": "The script ID to update",
            },
            "category_id": {
                "type": "string",
                "description": "Category ID to assign (from ha_list_categories scope='script'). Use null or empty string to remove.",
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of label IDs to assign (from ha_list_labels). Replaces existing labels.",
            },
            "alias": {"type": "string"},
            "description": {"type": "string"},
            "icon": {"type": "string"},
            "mode": {"type": "string"},
            "fields": {"type": "object"},
            "sequence": {"type": "array"},
        },
        "required": ["script_id"],
    },
    permission="scripts_update",
)
async def patch_script(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Partial update of a script."""
    script_id = arguments["script_id"]
    clean_id = script_id.replace("script.", "")
    entity_id = f"script.{clean_id}"

    result_message = []

    # Handle category and label updates via entity registry
    if "category_id" in arguments or "labels" in arguments:
        entity_registry = er.async_get(hass)
        registry_entry = entity_registry.async_get(entity_id)

        if registry_entry is None:
            raise ValueError(f"Script '{script_id}' not found in entity registry")

        update_kwargs: dict[str, Any] = {}

        if "category_id" in arguments:
            category_id = arguments["category_id"]
            if category_id is None or category_id == "":
                # Remove category - set to empty dict for script scope
                update_kwargs["categories"] = {}
            else:
                # Set category for script scope
                update_kwargs["categories"] = {"script": category_id}
            result_message.append("Category updated")

        if "labels" in arguments:
            label_ids = arguments["labels"]
            if label_ids is None:
                update_kwargs["labels"] = set()
            else:
                update_kwargs["labels"] = set(label_ids)
            result_message.append("Labels updated")

        if update_kwargs:
            entity_registry.async_update_entity(entity_id, **update_kwargs)

    # Check if we need to update config file fields
    config_fields = ["alias", "description", "icon", "mode", "max", "max_exceeded", "fields", "variables", "sequence"]
    has_config_updates = any(field in arguments for field in config_fields)

    if has_config_updates:
        scripts = await _load_script_config(hass)

        if clean_id not in scripts:
            raise ValueError(f"Script '{script_id}' not found in config")

        updated = scripts[clean_id].copy()
        for field in config_fields:
            if field in arguments:
                updated[field] = arguments[field]

        if "sequence" in arguments:
            sequence_errors = validate_sequence(hass, arguments["sequence"])
            if sequence_errors:
                raise ValueError("Invalid actions in sequence:\n" + "\n".join(sequence_errors))

        scripts[clean_id] = updated
        await _save_script_config(hass, scripts)
        await _reload_scripts(hass)
        result_message.append("Config updated")

    if not result_message:
        result_message.append("No changes made")

    return {"id": clean_id, "entity_id": entity_id, "message": ", ".join(result_message)}


@mcp_tool(
    name="ha_delete_script",
    description="Delete a script. This action cannot be undone.",
    schema={
        "type": "object",
        "properties": {
            "script_id": {
                "type": "string",
                "description": "The script ID to delete",
            }
        },
        "required": ["script_id"],
    },
    permission="scripts_delete",
)
async def delete_script(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Delete a script."""
    script_id = arguments["script_id"]
    clean_id = script_id.replace("script.", "")
    entity_id = f"script.{clean_id}"
    scripts = await _load_script_config(hass)

    if clean_id not in scripts:
        raise ValueError(f"Script '{script_id}' not found")

    del scripts[clean_id]
    await _save_script_config(hass, scripts)
    await _reload_scripts(hass)
    await _cleanup_entity_registry(hass, entity_id)

    return {"deleted": script_id}


@mcp_tool(
    name="ha_run_script",
    description="Run a script. Can pass variables as input.",
    schema={
        "type": "object",
        "properties": {
            "script_id": {
                "type": "string",
                "description": "The script ID to run",
            },
            "variables": {
                "type": "object",
                "description": "Variables to pass to the script",
            },
        },
        "required": ["script_id"],
    },
    permission="scripts_update",
)
async def run_script(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run a script."""
    script_id = arguments["script_id"]
    entity_id = f"script.{script_id}" if not script_id.startswith("script.") else script_id

    service_data: dict[str, Any] = {"entity_id": entity_id}
    if arguments.get("variables"):
        service_data["variables"] = arguments["variables"]

    await hass.services.async_call("script", "turn_on", service_data, blocking=True)
    return {"entity_id": entity_id, "started": True, "message": "Script started"}


@mcp_tool(
    name="ha_stop_script",
    description="Stop a running script.",
    schema={
        "type": "object",
        "properties": {
            "script_id": {
                "type": "string",
                "description": "The script ID to stop",
            }
        },
        "required": ["script_id"],
    },
    permission="scripts_update",
)
async def stop_script(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Stop a running script."""
    script_id = arguments["script_id"]
    entity_id = f"script.{script_id}" if not script_id.startswith("script.") else script_id
    await hass.services.async_call("script", "turn_off", {"entity_id": entity_id}, blocking=True)
    return {"entity_id": entity_id, "stopped": True, "message": "Script stopped"}
