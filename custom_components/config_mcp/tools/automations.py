"""MCP Tools for Automations.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..mcp_registry import mcp_tool
from ..views.automations import (
    get_automation_component,
    _format_automation,
    _load_automation_config,
    _save_automation_config,
    _reload_automations,
    _cleanup_entity_registry,
    validate_actions,
)

_LOGGER = logging.getLogger(__name__)


@mcp_tool(
    name="ha_list_automations",
    description=(
        "List all automations in Home Assistant. Returns automation metadata "
        "including id, entity_id, alias, state, and enabled status."
    ),
    permission="automations_read",
)
async def list_automations(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all automations."""
    component = get_automation_component(hass)
    if component is None:
        return []

    automations = []
    for entity in component.entities:
        try:
            automations.append(_format_automation(entity, hass=hass, include_config=False))
        except Exception as err:
            _LOGGER.warning("Error formatting automation %s: %s", entity.entity_id, err)
    return automations


@mcp_tool(
    name="ha_get_automation",
    description=(
        "Get full details for a specific automation including triggers, "
        "conditions, and actions."
    ),
    schema={
        "type": "object",
        "properties": {
            "automation_id": {
                "type": "string",
                "description": "The automation ID or entity_id",
            }
        },
        "required": ["automation_id"],
    },
    permission="automations_read",
)
async def get_automation(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get a single automation with config."""
    automation_id = arguments["automation_id"]
    entity_id = f"automation.{automation_id}" if not automation_id.startswith("automation.") else automation_id
    component = get_automation_component(hass)
    if component is None:
        raise ValueError(f"Automation '{automation_id}' not found")

    # First try to get by entity_id
    entity = component.get_entity(entity_id)

    # If not found and automation_id doesn't look like an entity_id, search by unique_id
    # This handles numeric IDs from UI-created automations (e.g., "1765219976897")
    if entity is None and not automation_id.startswith("automation."):
        for ent in component.entities:
            if ent.unique_id == automation_id:
                entity = ent
                break

    if entity is None:
        raise ValueError(f"Automation '{automation_id}' not found")

    return _format_automation(entity, hass=hass, include_config=True)


@mcp_tool(
    name="ha_create_automation",
    description=(
        "Create a new automation. Actions must use valid services "
        "(use ha_list_services to discover available services)."
    ),
    schema={
        "type": "object",
        "properties": {
            "alias": {
                "type": "string",
                "description": "Human-readable name for the automation (required)",
            },
            "id": {
                "type": "string",
                "description": "Automation ID (optional, auto-generated if not provided)",
            },
            "description": {
                "type": "string",
                "description": "Description of what the automation does",
            },
            "mode": {
                "type": "string",
                "description": "Execution mode: single, restart, queued, parallel",
            },
            "triggers": {
                "type": "array",
                "description": "List of trigger configurations",
            },
            "conditions": {
                "type": "array",
                "description": "List of condition configurations",
            },
            "actions": {
                "type": "array",
                "description": "List of action configurations (services to call)",
            },
        },
        "required": ["alias"],
    },
    permission="automations_create",
)
async def create_automation(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a new automation."""
    if "alias" not in arguments:
        raise ValueError("Missing required field: alias")

    automation_id = arguments.get("id", uuid.uuid4().hex)
    automations = await _load_automation_config(hass)

    # Check for duplicates
    for automation in automations:
        if automation.get("id") == automation_id:
            raise ValueError(f"Automation with id '{automation_id}' already exists")

    # Build new automation
    new_automation: dict[str, Any] = {
        "id": automation_id,
        "alias": arguments.get("alias"),
    }
    for field in ["description", "mode", "max", "max_exceeded", "variables", "trigger_variables"]:
        if field in arguments:
            new_automation[field] = arguments[field]

    new_automation["triggers"] = arguments.get("triggers", [])
    new_automation["conditions"] = arguments.get("conditions", [])
    new_automation["actions"] = arguments.get("actions", [])

    # Validate actions
    action_errors = validate_actions(hass, new_automation["actions"])
    if action_errors:
        raise ValueError("Invalid actions:\n" + "\n".join(action_errors))

    automations.append(new_automation)
    await _save_automation_config(hass, automations)
    await _reload_automations(hass)

    return {"id": automation_id, "entity_id": f"automation.{automation_id}", "message": "Automation created"}


@mcp_tool(
    name="ha_update_automation",
    description=(
        "Fully update an automation's configuration. Replaces the entire "
        "automation config."
    ),
    schema={
        "type": "object",
        "properties": {
            "automation_id": {
                "type": "string",
                "description": "The automation ID to update",
            },
            "alias": {"type": "string"},
            "description": {"type": "string"},
            "mode": {"type": "string"},
            "triggers": {"type": "array"},
            "conditions": {"type": "array"},
            "actions": {"type": "array"},
        },
        "required": ["automation_id"],
    },
    permission="automations_update",
)
async def update_automation(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Full update of an automation."""
    automation_id = arguments["automation_id"]
    automations = await _load_automation_config(hass)
    search_id = automation_id.replace("automation.", "")

    found_idx = None
    for idx, automation in enumerate(automations):
        if automation.get("id") == search_id:
            found_idx = idx
            break

    if found_idx is None:
        raise ValueError(f"Automation '{automation_id}' not found")

    updated: dict[str, Any] = {"id": search_id, "alias": arguments.get("alias", automations[found_idx].get("alias"))}
    for field in ["description", "mode", "max", "max_exceeded", "variables", "trigger_variables"]:
        if field in arguments:
            updated[field] = arguments[field]

    updated["triggers"] = arguments.get("triggers", [])
    updated["conditions"] = arguments.get("conditions", [])
    updated["actions"] = arguments.get("actions", [])

    action_errors = validate_actions(hass, updated["actions"])
    if action_errors:
        raise ValueError("Invalid actions:\n" + "\n".join(action_errors))

    automations[found_idx] = updated
    await _save_automation_config(hass, automations)
    await _reload_automations(hass)

    return {"id": search_id, "entity_id": f"automation.{search_id}", "message": "Automation updated"}


@mcp_tool(
    name="ha_patch_automation",
    description=(
        "Partially update an automation. Only provided fields are updated. "
        "Use enabled field to enable/disable. Use category_id to assign a category "
        "(from ha_list_categories with scope='automation'). Use labels to assign labels."
    ),
    schema={
        "type": "object",
        "properties": {
            "automation_id": {
                "type": "string",
                "description": "The automation ID to update",
            },
            "enabled": {
                "type": "boolean",
                "description": "Enable or disable the automation",
            },
            "category_id": {
                "type": "string",
                "description": "Category ID to assign (from ha_list_categories scope='automation'). Use null or empty string to remove.",
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of label IDs to assign (from ha_list_labels). Replaces existing labels.",
            },
            "alias": {"type": "string"},
            "description": {"type": "string"},
            "mode": {"type": "string"},
            "triggers": {"type": "array"},
            "conditions": {"type": "array"},
            "actions": {"type": "array"},
        },
        "required": ["automation_id"],
    },
    permission="automations_update",
)
async def patch_automation(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Partial update of an automation."""
    automation_id = arguments["automation_id"]
    entity_id = f"automation.{automation_id}" if not automation_id.startswith("automation.") else automation_id
    search_id = automation_id.replace("automation.", "")

    result_message = []

    # Handle enable/disable
    if "enabled" in arguments:
        service = "turn_on" if arguments["enabled"] else "turn_off"
        await hass.services.async_call("automation", service, {"entity_id": entity_id}, blocking=True)
        result_message.append(f"{'Enabled' if arguments['enabled'] else 'Disabled'}")

    # Handle category and label updates via entity registry
    if "category_id" in arguments or "labels" in arguments:
        entity_registry = er.async_get(hass)
        registry_entry = entity_registry.async_get(entity_id)

        if registry_entry is None:
            raise ValueError(f"Automation '{automation_id}' not found in entity registry")

        update_kwargs: dict[str, Any] = {}

        if "category_id" in arguments:
            category_id = arguments["category_id"]
            if category_id is None or category_id == "":
                # Remove category - set to empty dict for automation scope
                update_kwargs["categories"] = {}
            else:
                # Set category for automation scope
                update_kwargs["categories"] = {"automation": category_id}
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
    config_fields = ["alias", "description", "mode", "max", "max_exceeded", "variables", "trigger_variables", "triggers", "conditions", "actions"]
    has_config_updates = any(field in arguments for field in config_fields)

    if has_config_updates:
        automations = await _load_automation_config(hass)
        found_idx = None
        for idx, automation in enumerate(automations):
            if automation.get("id") == search_id:
                found_idx = idx
                break

        if found_idx is None:
            raise ValueError(f"Automation '{automation_id}' not found in config")

        updated = automations[found_idx].copy()
        for field in config_fields:
            if field in arguments:
                updated[field] = arguments[field]

        if "actions" in arguments:
            action_errors = validate_actions(hass, arguments["actions"])
            if action_errors:
                raise ValueError("Invalid actions:\n" + "\n".join(action_errors))

        automations[found_idx] = updated
        await _save_automation_config(hass, automations)
        await _reload_automations(hass)
        result_message.append("Config updated")

    if not result_message:
        result_message.append("No changes made")

    return {"id": search_id, "entity_id": entity_id, "message": ", ".join(result_message)}


@mcp_tool(
    name="ha_delete_automation",
    description="Delete an automation. This action cannot be undone.",
    schema={
        "type": "object",
        "properties": {
            "automation_id": {
                "type": "string",
                "description": "The automation ID to delete",
            }
        },
        "required": ["automation_id"],
    },
    permission="automations_delete",
)
async def delete_automation(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Delete an automation."""
    automation_id = arguments["automation_id"]
    automations = await _load_automation_config(hass)
    search_id = automation_id.replace("automation.", "")
    entity_id = f"automation.{search_id}"

    found_idx = None
    for idx, automation in enumerate(automations):
        if automation.get("id") == search_id:
            found_idx = idx
            break

    if found_idx is None:
        raise ValueError(f"Automation '{automation_id}' not found")

    automations.pop(found_idx)
    await _save_automation_config(hass, automations)
    await _reload_automations(hass)
    await _cleanup_entity_registry(hass, entity_id)

    return {"deleted": automation_id}


@mcp_tool(
    name="ha_trigger_automation",
    description="Manually trigger an automation to run immediately.",
    schema={
        "type": "object",
        "properties": {
            "automation_id": {
                "type": "string",
                "description": "The automation ID to trigger",
            },
            "skip_condition": {
                "type": "boolean",
                "description": "Skip condition evaluation",
            },
            "variables": {
                "type": "object",
                "description": "Variables to pass to the automation",
            },
        },
        "required": ["automation_id"],
    },
    permission="automations_update",
)
async def trigger_automation(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Trigger an automation."""
    automation_id = arguments["automation_id"]
    entity_id = f"automation.{automation_id}" if not automation_id.startswith("automation.") else automation_id

    service_data: dict[str, Any] = {"entity_id": entity_id}
    if arguments.get("skip_condition"):
        service_data["skip_condition"] = True
    if arguments.get("variables"):
        service_data["variables"] = arguments["variables"]

    await hass.services.async_call("automation", "trigger", service_data, blocking=True)
    return {"entity_id": entity_id, "triggered": True, "message": "Automation triggered"}
