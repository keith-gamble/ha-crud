"""MCP Tools for Automations.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from homeassistant.core import HomeAssistant

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
            automations.append(_format_automation(entity, include_config=False))
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

    entity = component.get_entity(entity_id)
    if entity is None:
        raise ValueError(f"Automation '{automation_id}' not found")

    return _format_automation(entity, include_config=True)


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
        "Use enabled field to enable/disable."
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

    # Handle enable/disable
    if "enabled" in arguments:
        service = "turn_on" if arguments["enabled"] else "turn_off"
        await hass.services.async_call("automation", service, {"entity_id": entity_id}, blocking=True)
        if len(arguments) == 2:  # Only automation_id and enabled
            return {"entity_id": entity_id, "enabled": arguments["enabled"], "message": f"Automation {'enabled' if arguments['enabled'] else 'disabled'}"}

    automations = await _load_automation_config(hass)
    found_idx = None
    for idx, automation in enumerate(automations):
        if automation.get("id") == search_id:
            found_idx = idx
            break

    if found_idx is None:
        raise ValueError(f"Automation '{automation_id}' not found")

    updated = automations[found_idx].copy()
    for field in ["alias", "description", "mode", "max", "max_exceeded", "variables", "trigger_variables", "triggers", "conditions", "actions"]:
        if field in arguments:
            updated[field] = arguments[field]

    if "actions" in arguments:
        action_errors = validate_actions(hass, arguments["actions"])
        if action_errors:
            raise ValueError("Invalid actions:\n" + "\n".join(action_errors))

    automations[found_idx] = updated
    await _save_automation_config(hass, automations)
    await _reload_automations(hass)

    return {"id": search_id, "entity_id": entity_id, "message": "Automation updated"}


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
