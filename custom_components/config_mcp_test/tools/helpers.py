"""MCP Tools for Home Assistant Helpers.

Provides tools for managing Home Assistant helpers (input_boolean, input_number,
input_text, input_select, input_datetime, counter, timer) via the Home Assistant
Store API for direct storage file access.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from ..mcp_registry import mcp_tool
from ..const import HELPER_DOMAINS

_LOGGER = logging.getLogger(__name__)

# Storage version must match Home Assistant's internal version for these domains
STORAGE_VERSION = 1


# Domain-specific required fields for creation
HELPER_CREATE_FIELDS: dict[str, list[str]] = {
    "input_boolean": [],  # Only name required
    "input_number": ["min", "max"],  # min and max are required
    "input_text": [],  # Only name required
    "input_select": ["options"],  # options list is required
    "input_datetime": [],  # Only name required
    "counter": [],  # Only name required
    "timer": [],  # Only name required
}

# Domain-specific optional fields
HELPER_OPTIONAL_FIELDS: dict[str, list[str]] = {
    "input_boolean": ["icon"],
    "input_number": ["icon", "mode", "step", "unit_of_measurement"],
    "input_text": ["icon", "min", "max", "pattern", "mode"],
    "input_select": ["icon"],
    "input_datetime": ["icon", "has_date", "has_time"],
    "counter": ["icon", "initial", "minimum", "maximum", "step", "restore"],
    "timer": ["icon", "duration", "restore"],
}


async def _get_helpers_for_domain(hass: HomeAssistant, domain: str) -> list[dict[str, Any]]:
    """Get all helpers for a specific domain using the Store API.

    Args:
        hass: Home Assistant instance
        domain: The helper domain (e.g., 'input_boolean')

    Returns:
        List of helper configurations
    """
    helpers = []

    # Use Store API to read from .storage/core.{domain}
    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"core.{domain}")
    data = await store.async_load()

    if data is None:
        return helpers

    # The storage format has an "items" key containing the list of helpers
    items = data.get("items", [])

    for item in items:
        if isinstance(item, dict):
            helpers.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "domain": domain,
                **{k: v for k, v in item.items() if k not in ("id", "name")},
            })

    return helpers


async def _get_helper_by_id(
    hass: HomeAssistant,
    helper_id: str
) -> tuple[str | None, dict[str, Any] | None]:
    """Get a specific helper by ID using the Store API.

    Args:
        hass: Home Assistant instance
        helper_id: The helper ID

    Returns:
        Tuple of (domain, helper_config) or (None, None) if not found
    """
    for domain in HELPER_DOMAINS:
        try:
            store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"core.{domain}")
            data = await store.async_load()

            if data is None:
                continue

            items = data.get("items", [])
            for item in items:
                if isinstance(item, dict) and item.get("id") == helper_id:
                    return domain, {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "domain": domain,
                        **{k: v for k, v in item.items() if k not in ("id", "name")},
                    }
        except Exception as err:
            _LOGGER.warning("Error searching for helper in domain %s: %s", domain, err)
            continue

    return None, None


def _generate_helper_id(name: str) -> str:
    """Generate a helper ID from the name.

    Args:
        name: The helper name

    Returns:
        A valid helper ID
    """
    # Convert name to lowercase and replace spaces with underscores
    helper_id = name.lower().replace(" ", "_")
    # Remove any characters that aren't alphanumeric or underscores
    helper_id = "".join(c for c in helper_id if c.isalnum() or c == "_")
    # Ensure it doesn't start with a number
    if helper_id and helper_id[0].isdigit():
        helper_id = f"_{helper_id}"
    return helper_id or f"helper_{uuid.uuid4().hex[:8]}"


async def _create_helper(
    hass: HomeAssistant,
    domain: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Create a new helper using the Store API.

    Args:
        hass: Home Assistant instance
        domain: The helper domain
        config: The helper configuration

    Returns:
        The created helper data

    Raises:
        ValueError: If the domain is not supported or creation fails
    """
    if domain not in HELPER_DOMAINS:
        raise ValueError(f"Invalid helper domain: {domain}")

    # Use Store API to read/write .storage/core.{domain}
    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"core.{domain}")
    data = await store.async_load() or {"items": []}

    # Generate ID from name if not provided
    helper_id = config.get("id") or _generate_helper_id(config["name"])

    # Check for duplicate ID
    existing_ids = {item.get("id") for item in data.get("items", [])}
    if helper_id in existing_ids:
        raise ValueError(f"Helper with ID '{helper_id}' already exists")

    # Build the helper configuration
    new_helper = {
        "id": helper_id,
        **config,
    }

    # Add to items list
    if "items" not in data:
        data["items"] = []
    data["items"].append(new_helper)

    # Save to storage
    await store.async_save(data)

    # Reload the domain to pick up the new helper
    try:
        await hass.services.async_call(domain, "reload", blocking=True)
    except Exception as err:
        _LOGGER.warning("Failed to reload %s after creation: %s", domain, err)

    return {
        "id": helper_id,
        "name": config.get("name"),
        "domain": domain,
        **{k: v for k, v in new_helper.items() if k not in ("id", "name")},
    }


async def _update_helper(
    hass: HomeAssistant,
    domain: str,
    helper_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing helper using the Store API.

    Args:
        hass: Home Assistant instance
        domain: The helper domain
        helper_id: The helper ID
        updates: The fields to update

    Returns:
        The updated helper data

    Raises:
        ValueError: If update fails
    """
    # Use Store API to read/write .storage/core.{domain}
    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"core.{domain}")
    data = await store.async_load()

    if data is None:
        raise ValueError(f"Helper domain {domain} has no stored data")

    items = data.get("items", [])

    # Find and update the helper
    updated_item = None
    for i, item in enumerate(items):
        if isinstance(item, dict) and item.get("id") == helper_id:
            # Merge updates with existing item (don't change id)
            items[i] = {**item, **updates, "id": helper_id}
            updated_item = items[i]
            break

    if updated_item is None:
        raise ValueError(f"Helper '{helper_id}' not found in {domain}")

    # Save to storage
    data["items"] = items
    await store.async_save(data)

    # Reload the domain to pick up the changes
    try:
        await hass.services.async_call(domain, "reload", blocking=True)
    except Exception as err:
        _LOGGER.warning("Failed to reload %s after update: %s", domain, err)

    return {
        "id": updated_item.get("id"),
        "name": updated_item.get("name"),
        "domain": domain,
        **{k: v for k, v in updated_item.items() if k not in ("id", "name")},
    }


async def _delete_helper(
    hass: HomeAssistant,
    domain: str,
    helper_id: str,
) -> None:
    """Delete a helper using the Store API.

    Args:
        hass: Home Assistant instance
        domain: The helper domain
        helper_id: The helper ID

    Raises:
        ValueError: If deletion fails
    """
    # Use Store API to read/write .storage/core.{domain}
    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"core.{domain}")
    data = await store.async_load()

    if data is None:
        raise ValueError(f"Helper domain {domain} has no stored data")

    items = data.get("items", [])

    # Find and remove the helper
    original_count = len(items)
    items = [item for item in items if not (isinstance(item, dict) and item.get("id") == helper_id)]

    if len(items) == original_count:
        raise ValueError(f"Helper '{helper_id}' not found in {domain}")

    # Save to storage
    data["items"] = items
    await store.async_save(data)

    # Reload the domain to pick up the changes
    try:
        await hass.services.async_call(domain, "reload", blocking=True)
    except Exception as err:
        _LOGGER.warning("Failed to reload %s after deletion: %s", domain, err)


def _format_helper(
    helper_config: dict[str, Any],
    domain: str,
    entity_entry: er.RegistryEntry | None = None,
) -> dict[str, Any]:
    """Format a helper configuration for response.

    Args:
        helper_config: The raw helper configuration
        domain: The helper domain
        entity_entry: Optional entity registry entry

    Returns:
        Formatted helper data
    """
    helper_id = helper_config.get("id")
    entity_id = f"{domain}.{helper_id}" if helper_id else None

    data: dict[str, Any] = {
        "id": helper_id,
        "domain": domain,
        "entity_id": entity_id,
        "name": helper_config.get("name"),
        "icon": helper_config.get("icon"),
    }

    # Add domain-specific fields
    if domain == "input_number":
        data["min"] = helper_config.get("min")
        data["max"] = helper_config.get("max")
        data["step"] = helper_config.get("step")
        data["mode"] = helper_config.get("mode")
        data["unit_of_measurement"] = helper_config.get("unit_of_measurement")
    elif domain == "input_text":
        data["min"] = helper_config.get("min")
        data["max"] = helper_config.get("max")
        data["pattern"] = helper_config.get("pattern")
        data["mode"] = helper_config.get("mode")
    elif domain == "input_select":
        data["options"] = helper_config.get("options", [])
    elif domain == "input_datetime":
        data["has_date"] = helper_config.get("has_date")
        data["has_time"] = helper_config.get("has_time")
    elif domain == "counter":
        data["initial"] = helper_config.get("initial")
        data["minimum"] = helper_config.get("minimum")
        data["maximum"] = helper_config.get("maximum")
        data["step"] = helper_config.get("step")
        data["restore"] = helper_config.get("restore")
    elif domain == "timer":
        data["duration"] = helper_config.get("duration")
        data["restore"] = helper_config.get("restore")

    # Add entity registry info if available
    if entity_entry:
        data["area_id"] = entity_entry.area_id
        data["labels"] = list(entity_entry.labels) if entity_entry.labels else []
        data["disabled"] = entity_entry.disabled_by is not None

    return data


# =============================================================================
# List Helpers Tool
# =============================================================================

@mcp_tool(
    name="ha_list_helpers",
    description=(
        "List all helpers in Home Assistant with optional domain filter. "
        "Supported domains: input_boolean, input_number, input_text, input_select, "
        "input_datetime, counter, timer. Returns helper configuration including "
        "id, name, domain, entity_id, and domain-specific settings."
    ),
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Filter by helper domain. Valid values: input_boolean, "
                    "input_number, input_text, input_select, input_datetime, "
                    "counter, timer"
                ),
                "enum": HELPER_DOMAINS,
            },
        },
    },
    permission="helpers_read",
)
async def list_helpers(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all helpers with optional domain filter."""
    domain_filter = arguments.get("domain")
    entity_registry = er.async_get(hass)

    helpers: list[dict[str, Any]] = []

    domains_to_query = [domain_filter] if domain_filter else HELPER_DOMAINS

    for domain in domains_to_query:
        if domain not in HELPER_DOMAINS:
            continue

        domain_helpers = await _get_helpers_for_domain(hass, domain)

        for helper_config in domain_helpers:
            helper_id = helper_config.get("id")
            entity_id = f"{domain}.{helper_id}" if helper_id else None

            entity_entry = None
            if entity_id:
                entity_entry = entity_registry.async_get(entity_id)

            formatted = _format_helper(helper_config, domain, entity_entry)

            # Add current state
            if entity_id:
                state = hass.states.get(entity_id)
                if state:
                    formatted["current_state"] = state.state

            helpers.append(formatted)

    # Sort by domain, then by name
    helpers.sort(key=lambda x: (x.get("domain", ""), (x.get("name") or "").lower()))

    return helpers


# =============================================================================
# Get Helper Tool
# =============================================================================

@mcp_tool(
    name="ha_get_helper",
    description=(
        "Get full details for a specific helper by entity_id or helper_id. Returns "
        "the helper configuration, current state, and entity registry information."
    ),
    schema={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "The helper entity ID (e.g., 'input_boolean.my_toggle', "
                    "'counter.my_counter') or helper ID"
                ),
            },
        },
        "required": ["entity_id"],
    },
    permission="helpers_read",
)
async def get_helper(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get a specific helper by entity_id or helper_id."""
    entity_id = arguments["entity_id"]

    # Parse domain from entity_id if it contains a dot
    if "." in entity_id:
        domain = entity_id.split(".")[0]
        helper_id = entity_id.split(".", 1)[1]
    else:
        # Try to find by ID across all domains
        domain, helper_config = await _get_helper_by_id(hass, entity_id)
        if helper_config is None:
            raise ValueError(f"Helper '{entity_id}' not found")
        helper_id = entity_id

    if domain not in HELPER_DOMAINS:
        raise ValueError(
            f"Entity '{entity_id}' is not a helper. "
            f"Supported domains: {', '.join(HELPER_DOMAINS)}"
        )

    # Get helpers for the domain
    domain_helpers = await _get_helpers_for_domain(hass, domain)

    # Find the specific helper
    helper_config = None
    for h in domain_helpers:
        if h.get("id") == helper_id:
            helper_config = h
            break

    if helper_config is None:
        raise ValueError(f"Helper '{entity_id}' not found")

    # Get entity registry entry
    entity_registry = er.async_get(hass)
    full_entity_id = f"{domain}.{helper_id}"
    entity_entry = entity_registry.async_get(full_entity_id)

    # Format the response
    result = _format_helper(helper_config, domain, entity_entry)

    # Add current state information
    state = hass.states.get(full_entity_id)
    if state:
        result["current_state"] = {
            "state": state.state,
            "attributes": dict(state.attributes),
            "last_changed": state.last_changed.isoformat() if state.last_changed else None,
            "last_updated": state.last_updated.isoformat() if state.last_updated else None,
        }

    return result


# =============================================================================
# Create Helper Tool
# =============================================================================

@mcp_tool(
    name="ha_create_helper",
    description=(
        "Create a new helper entity. Requires specifying the helper domain and "
        "name. Additional fields depend on the domain:\n"
        "- input_boolean: icon\n"
        "- input_number: min (required), max (required), step, mode, unit_of_measurement, icon\n"
        "- input_text: min, max, pattern, mode, icon\n"
        "- input_select: options (required), icon\n"
        "- input_datetime: has_date, has_time, icon\n"
        "- counter: initial, minimum, maximum, step, restore, icon\n"
        "- timer: duration, restore, icon"
    ),
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The helper domain to create",
                "enum": HELPER_DOMAINS,
            },
            "name": {
                "type": "string",
                "description": "Human-readable name for the helper (required)",
            },
            "icon": {
                "type": "string",
                "description": "Material Design Icon (e.g., 'mdi:toggle-switch')",
            },
            # input_number fields
            "min": {
                "type": "number",
                "description": "Minimum value (required for input_number, optional for input_text)",
            },
            "max": {
                "type": "number",
                "description": "Maximum value (required for input_number, optional for input_text)",
            },
            "step": {
                "type": "number",
                "description": "Step value for input_number or counter",
            },
            "mode": {
                "type": "string",
                "description": "Display mode: 'box' or 'slider' for input_number, 'text' or 'password' for input_text",
            },
            "unit_of_measurement": {
                "type": "string",
                "description": "Unit of measurement for input_number",
            },
            # input_text fields
            "pattern": {
                "type": "string",
                "description": "Regex pattern for input_text validation",
            },
            # input_select fields
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of options for input_select (required)",
            },
            # input_datetime fields
            "has_date": {
                "type": "boolean",
                "description": "Whether input_datetime has date component",
            },
            "has_time": {
                "type": "boolean",
                "description": "Whether input_datetime has time component",
            },
            # counter fields
            "initial": {
                "type": "integer",
                "description": "Initial value for counter",
            },
            "minimum": {
                "type": "integer",
                "description": "Minimum value for counter",
            },
            "maximum": {
                "type": "integer",
                "description": "Maximum value for counter",
            },
            "restore": {
                "type": "boolean",
                "description": "Whether to restore value on restart (counter, timer)",
            },
            # timer fields
            "duration": {
                "type": "string",
                "description": "Default duration for timer (e.g., '00:01:00' for 1 minute)",
            },
        },
        "required": ["domain", "name"],
    },
    permission="helpers_create",
)
async def create_helper(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a new helper."""
    domain = arguments["domain"]
    name = arguments["name"]

    if domain not in HELPER_DOMAINS:
        raise ValueError(
            f"Invalid domain '{domain}'. "
            f"Supported domains: {', '.join(HELPER_DOMAINS)}"
        )

    # Validate required fields for the domain
    required_fields = HELPER_CREATE_FIELDS.get(domain, [])
    for field in required_fields:
        if field not in arguments:
            raise ValueError(f"Missing required field '{field}' for {domain}")

    # Build the create command data
    create_data: dict[str, Any] = {"name": name}

    # Add icon if provided
    if "icon" in arguments:
        create_data["icon"] = arguments["icon"]

    # Add domain-specific fields
    optional_fields = HELPER_OPTIONAL_FIELDS.get(domain, [])
    all_fields = required_fields + optional_fields

    for field in all_fields:
        if field in arguments and field != "icon":  # icon already handled
            create_data[field] = arguments[field]

    # Execute the create command
    try:
        result = await _create_helper(hass, domain, create_data)
    except ValueError as err:
        raise ValueError(f"Failed to create {domain}: {err}") from err

    helper_id = result.get("id")
    entity_id = f"{domain}.{helper_id}" if helper_id else None

    return {
        "id": helper_id,
        "entity_id": entity_id,
        "domain": domain,
        "name": name,
        "message": f"{domain} helper created",
    }


# =============================================================================
# Update Helper Tool
# =============================================================================

@mcp_tool(
    name="ha_update_helper",
    description=(
        "Update an existing helper's configuration. Specify the entity_id and "
        "the fields to update. Only provided fields will be changed."
    ),
    schema={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The helper entity ID to update (e.g., 'input_boolean.my_toggle')",
            },
            "name": {
                "type": "string",
                "description": "New name for the helper",
            },
            "icon": {
                "type": "string",
                "description": "New icon (e.g., 'mdi:toggle-switch')",
            },
            # input_number fields
            "min": {
                "type": "number",
                "description": "New minimum value (input_number)",
            },
            "max": {
                "type": "number",
                "description": "New maximum value (input_number)",
            },
            "step": {
                "type": "number",
                "description": "New step value (input_number, counter)",
            },
            "mode": {
                "type": "string",
                "description": "New display mode (input_number: 'box'/'slider', input_text: 'text'/'password')",
            },
            "unit_of_measurement": {
                "type": "string",
                "description": "New unit of measurement (input_number)",
            },
            # input_text fields
            "pattern": {
                "type": "string",
                "description": "New regex pattern (input_text)",
            },
            # input_select fields
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New options list (input_select)",
            },
            # input_datetime fields
            "has_date": {
                "type": "boolean",
                "description": "Whether to have date component (input_datetime)",
            },
            "has_time": {
                "type": "boolean",
                "description": "Whether to have time component (input_datetime)",
            },
            # counter fields
            "initial": {
                "type": "integer",
                "description": "New initial value (counter)",
            },
            "minimum": {
                "type": "integer",
                "description": "New minimum value (counter)",
            },
            "maximum": {
                "type": "integer",
                "description": "New maximum value (counter)",
            },
            "restore": {
                "type": "boolean",
                "description": "Whether to restore value on restart (counter, timer)",
            },
            # timer fields
            "duration": {
                "type": "string",
                "description": "New default duration (timer)",
            },
        },
        "required": ["entity_id"],
    },
    permission="helpers_update",
)
async def update_helper(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Update an existing helper."""
    entity_id = arguments["entity_id"]

    # Parse domain from entity_id
    if "." not in entity_id:
        raise ValueError(f"Invalid entity_id format: {entity_id}")

    domain = entity_id.split(".")[0]
    helper_id = entity_id.split(".", 1)[1]

    if domain not in HELPER_DOMAINS:
        raise ValueError(
            f"Entity '{entity_id}' is not a helper. "
            f"Supported domains: {', '.join(HELPER_DOMAINS)}"
        )

    # Collect fields to update
    updatable_fields = ["name", "icon"] + HELPER_OPTIONAL_FIELDS.get(domain, [])
    updatable_fields.extend(HELPER_CREATE_FIELDS.get(domain, []))

    update_data: dict[str, Any] = {}
    for field in updatable_fields:
        if field in arguments:
            update_data[field] = arguments[field]

    if not update_data:
        raise ValueError("No update fields provided")

    # Execute the update command
    try:
        await _update_helper(hass, domain, helper_id, update_data)
    except ValueError as err:
        raise ValueError(f"Failed to update {domain}: {err}") from err

    return {
        "id": helper_id,
        "entity_id": entity_id,
        "domain": domain,
        "message": f"{domain} helper updated",
    }


# =============================================================================
# Delete Helper Tool
# =============================================================================

@mcp_tool(
    name="ha_delete_helper",
    description=(
        "Delete a helper entity. This action cannot be undone. "
        "The helper and its entity will be permanently removed."
    ),
    schema={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The helper entity ID to delete (e.g., 'input_boolean.my_toggle')",
            },
        },
        "required": ["entity_id"],
    },
    permission="helpers_delete",
)
async def delete_helper(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Delete a helper."""
    entity_id = arguments["entity_id"]

    # Parse domain from entity_id
    if "." not in entity_id:
        raise ValueError(f"Invalid entity_id format: {entity_id}")

    domain = entity_id.split(".")[0]
    helper_id = entity_id.split(".", 1)[1]

    if domain not in HELPER_DOMAINS:
        raise ValueError(
            f"Entity '{entity_id}' is not a helper. "
            f"Supported domains: {', '.join(HELPER_DOMAINS)}"
        )

    # Verify the helper exists first
    domain_helpers = await _get_helpers_for_domain(hass, domain)
    helper_exists = any(h.get("id") == helper_id for h in domain_helpers)

    if not helper_exists:
        raise ValueError(f"Helper '{entity_id}' not found")

    # Execute the delete command
    try:
        await _delete_helper(hass, domain, helper_id)
    except ValueError as err:
        raise ValueError(f"Failed to delete {domain}: {err}") from err

    return {
        "deleted": entity_id,
        "domain": domain,
        "message": f"{domain} helper deleted",
    }
