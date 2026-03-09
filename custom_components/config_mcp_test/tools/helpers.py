"""MCP Tools for Home Assistant Helpers.

Provides tools for managing Home Assistant helpers (input_boolean, input_number,
input_text, input_select, input_datetime, counter, timer) via Home Assistant's
internal StorageCollection API, which keeps in-memory state and .storage files
in sync (fixing BUG 3 — Store API cache bypass).

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from ..mcp_registry import mcp_tool
import voluptuous as vol

from ..const import CONFIG_ENTRY_HELPER_DOMAINS, HELPER_DOMAINS

_LOGGER = logging.getLogger(__name__)

# Storage version for reading helpers via Store API (list/get operations)
STORAGE_VERSION = 1

# Key used by HA's collection.store_entity_registry_items() to store
# StorageCollection instances in hass.data
COLLECTION_INSTANCES_KEY = "collection_instances"


# Domain-specific required fields for creation
HELPER_CREATE_FIELDS: dict[str, list[str]] = {
    "input_boolean": [],  # Only name required
    "input_button": [],  # Only name required
    "input_number": ["min", "max"],  # min and max are required
    "input_text": [],  # Only name required
    "input_select": ["options"],  # options list is required
    "input_datetime": [],  # Only name required
    "counter": [],  # Only name required
    "timer": [],  # Only name required
    "schedule": [],  # Only name required; schedule blocks added separately
}

# Domain-specific optional fields
HELPER_OPTIONAL_FIELDS: dict[str, list[str]] = {
    "input_boolean": ["icon"],
    "input_button": ["icon"],
    "input_number": ["icon", "mode", "step", "unit_of_measurement"],
    "input_text": ["icon", "min", "max", "pattern", "mode"],
    "input_select": ["icon"],
    "input_datetime": ["icon", "has_date", "has_time"],
    "counter": ["icon", "initial", "minimum", "maximum", "step", "restore"],
    "timer": ["icon", "duration", "restore"],
    "schedule": ["icon", "monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"],
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

    # Use Store API to read from .storage/{domain}
    # HA helper integrations use STORAGE_KEY = DOMAIN (no 'core.' prefix)
    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, domain)
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
            store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, domain)
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


def _get_storage_collection(hass: HomeAssistant, domain: str) -> Any:
    """Get Home Assistant's internal StorageCollection for a helper domain.

    Retrieves the StorageCollection by looking up the registered WebSocket
    handler for '{domain}/create', which is a bound method on the
    StorageCollectionWebsocket instance that holds a reference to the collection.

    Args:
        hass: Home Assistant instance
        domain: The helper domain (e.g., 'input_boolean')

    Returns:
        The StorageCollection instance for the domain

    Raises:
        ValueError: If the collection is not found
    """
    # WS commands are stored in hass.data["websocket_api"][command_type]
    ws_handlers = hass.data.get("websocket_api")
    if ws_handlers is None:
        raise ValueError(
            f"WebSocket API not initialized. Cannot access {domain} collection."
        )

    # The handler for '{domain}/create' is a bound method on the
    # StorageCollectionWebsocket instance which exposes .storage_collection
    handler_info = ws_handlers.get(f"{domain}/create")
    if handler_info is None:
        raise ValueError(
            f"No WebSocket handler for '{domain}/create'. "
            f"Ensure the {domain} integration is loaded."
        )

    # handler_info may be the handler directly or a tuple (handler, schema)
    handler = handler_info[0] if isinstance(handler_info, tuple) else handler_info

    # Unwrap require_admin / async_response decorators to get the bound method
    while hasattr(handler, "__wrapped__") or hasattr(handler, "func"):
        handler = getattr(handler, "__wrapped__", None) or handler.func

    ws_instance = getattr(handler, "__self__", None)
    if ws_instance is None:
        raise ValueError(
            f"Could not extract StorageCollectionWebsocket instance for {domain}."
        )

    storage_collection = getattr(ws_instance, "storage_collection", None)
    if storage_collection is None:
        raise ValueError(
            f"StorageCollectionWebsocket for {domain} has no storage_collection."
        )

    return storage_collection


async def _create_helper(
    hass: HomeAssistant,
    domain: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Create a new helper using HA's internal StorageCollection.

    Uses the same collection that WebSocket commands ({domain}/create) use,
    keeping in-memory state and .storage files in sync.

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

    collection = _get_storage_collection(hass, domain)

    # Remove 'id' if present — the collection generates IDs automatically
    create_data = {k: v for k, v in config.items() if k != "id"}

    try:
        item = await collection.async_create_item(create_data)
    except ValueError as err:
        raise ValueError(f"Failed to create helper: {err}") from err

    # The collection returns the created item (dict or object with as_dict())
    if hasattr(item, "as_dict"):
        item_data = item.as_dict()
    elif isinstance(item, dict):
        item_data = item
    else:
        item_data = {"id": str(item)}

    return {
        "domain": domain,
        **item_data,
    }


async def _update_helper(
    hass: HomeAssistant,
    domain: str,
    helper_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing helper using HA's internal StorageCollection.

    Uses the same collection that WebSocket commands ({domain}/update) use,
    keeping in-memory state and .storage files in sync.

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
    collection = _get_storage_collection(hass, domain)

    # Remove 'id' and 'domain' from updates — these can't be changed
    update_data = {k: v for k, v in updates.items() if k not in ("id", "domain")}

    try:
        item = await collection.async_update_item(helper_id, update_data)
    except KeyError:
        raise ValueError(f"Helper '{helper_id}' not found in {domain}")
    except ValueError as err:
        raise ValueError(f"Failed to update helper: {err}") from err

    if hasattr(item, "as_dict"):
        item_data = item.as_dict()
    elif isinstance(item, dict):
        item_data = item
    else:
        item_data = {"id": helper_id}

    return {
        "domain": domain,
        **item_data,
    }


async def _delete_helper(
    hass: HomeAssistant,
    domain: str,
    helper_id: str,
) -> None:
    """Delete a helper using HA's internal StorageCollection.

    Uses the same collection that WebSocket commands ({domain}/delete) use,
    keeping in-memory state and .storage files in sync.

    Args:
        hass: Home Assistant instance
        domain: The helper domain
        helper_id: The helper ID

    Raises:
        ValueError: If deletion fails
    """
    collection = _get_storage_collection(hass, domain)

    try:
        await collection.async_delete_item(helper_id)
    except KeyError:
        raise ValueError(f"Helper '{helper_id}' not found in {domain}")


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
    elif domain == "schedule":
        for day in ("monday", "tuesday", "wednesday", "thursday",
                    "friday", "saturday", "sunday"):
            if day in helper_config:
                data[day] = helper_config[day]

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
        "- input_button: icon\n"
        "- input_number: min (required), max (required), step, mode, unit_of_measurement, icon\n"
        "- input_text: min, max, pattern, mode, icon\n"
        "- input_select: options (required), icon\n"
        "- input_datetime: has_date, has_time, icon\n"
        "- counter: initial, minimum, maximum, step, restore, icon\n"
        "- timer: duration, restore, icon\n"
        "- schedule: icon, monday..sunday (each an array of {from, to, data} blocks)"
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
            # schedule fields (each day is an array of time blocks)
            "monday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Monday schedule blocks: [{from: '08:00:00', to: '17:00:00'}]",
            },
            "tuesday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Tuesday schedule blocks",
            },
            "wednesday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Wednesday schedule blocks",
            },
            "thursday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Thursday schedule blocks",
            },
            "friday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Friday schedule blocks",
            },
            "saturday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Saturday schedule blocks",
            },
            "sunday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Sunday schedule blocks",
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
            # schedule fields
            "monday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "New Monday schedule blocks",
            },
            "tuesday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "New Tuesday schedule blocks",
            },
            "wednesday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "New Wednesday schedule blocks",
            },
            "thursday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "New Thursday schedule blocks",
            },
            "friday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "New Friday schedule blocks",
            },
            "saturday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "New Saturday schedule blocks",
            },
            "sunday": {
                "type": "array",
                "items": {"type": "object"},
                "description": "New Sunday schedule blocks",
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


# =============================================================================
# Config Entry Helper Tools (Config Entry Flow API)
# =============================================================================
# These helpers use HA's Config Entry Flow for creation/management, unlike
# StorageCollection helpers (input_boolean, counter, etc.). Includes template
# sensors, groups, utility meters, derivatives, thermostats, and more.
#
# The flow follower dynamically inspects each flow step's voluptuous schema
# and submits matching fields from the user's config dict, making it work
# with any current or future config-entry-flow helper integration.

# Domains that present a menu step requiring sub_type selection
MENU_FLOW_DOMAINS = {"group", "template", "random"}


def _extract_form_data(schema, config_data):
    """Extract fields from config_data that match a voluptuous schema."""
    if schema is None:
        return {}

    submit_data = {}
    for key in schema.schema:
        if isinstance(key, vol.Marker):
            field_name = key.schema
        else:
            field_name = str(key)

        if field_name in config_data:
            submit_data[field_name] = config_data[field_name]

    return submit_data


async def _follow_config_flow(hass, domain, config_data, sub_type=None):
    """Follow a config entry flow to create a helper, submitting matching fields.

    Handles all flow patterns automatically:
    - Direct form: init -> form -> create_entry
    - Multi-step form: init -> form -> form -> ... -> create_entry
    - Menu-first: init -> menu -> form -> create_entry
    """
    try:
        result = await hass.config_entries.flow.async_init(
            domain, context={"source": "user"}
        )
    except Exception as err:
        raise ValueError(
            f"Failed to initiate config flow for '{domain}': {err}. "
            f"Ensure the '{domain}' integration is loaded."
        ) from err

    flow_id = result["flow_id"]

    for _ in range(10):  # safety limit for multi-step flows
        flow_type = result.get("type")

        if flow_type == "create_entry":
            return result

        if flow_type == "abort":
            raise ValueError(
                f"Config flow aborted: {result.get('reason', 'unknown')}"
            )

        if flow_type == "menu":
            if not sub_type:
                menu_options = result.get("menu_options", [])
                raise ValueError(
                    f"Domain '{domain}' requires sub_type. "
                    f"Available: {', '.join(menu_options)}"
                )
            result = await hass.config_entries.flow.async_configure(
                flow_id, {"next_step_id": sub_type}
            )
            sub_type = None  # Only use for first menu
            continue

        if flow_type == "form":
            schema = result.get("data_schema")
            submit_data = _extract_form_data(schema, config_data)
            try:
                result = await hass.config_entries.flow.async_configure(
                    flow_id, submit_data
                )
            except Exception as err:
                step_id = result.get("step_id", "unknown")
                raise ValueError(
                    f"Failed at flow step '{step_id}': {err}"
                ) from err
            continue

        raise ValueError(f"Unexpected flow step type: {flow_type}")

    raise ValueError("Config flow did not complete within expected steps")


async def _follow_options_flow(hass, entry_id, update_data):
    """Follow an options flow, merging current options with updates."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError(f"Config entry '{entry_id}' not found")

    merged = {**dict(entry.options), **update_data}

    try:
        result = await hass.config_entries.options.async_init(entry_id)
    except Exception as err:
        raise ValueError(
            f"Failed to start options flow for '{entry.title}': {err}"
        ) from err

    flow_id = result["flow_id"]

    for _ in range(10):
        flow_type = result.get("type")

        if flow_type == "create_entry":
            return result

        if flow_type == "abort":
            raise ValueError(
                f"Options flow aborted: {result.get('reason', 'unknown')}"
            )

        if flow_type == "form":
            schema = result.get("data_schema")
            submit_data = _extract_form_data(schema, merged)
            try:
                result = await hass.config_entries.options.async_configure(
                    flow_id, submit_data
                )
            except Exception as err:
                step_id = result.get("step_id", "unknown")
                raise ValueError(
                    f"Failed at options step '{step_id}': {err}"
                ) from err
            continue

        raise ValueError(f"Unexpected options flow type: {flow_type}")

    raise ValueError("Options flow did not complete within expected steps")


# =============================================================================
# List Config Entry Helpers
# =============================================================================

@mcp_tool(
    name="ha_list_config_entry_helpers",
    description=(
        "List config-entry-flow-based helpers (template sensors, groups, utility "
        "meters, derivatives, thermostats, etc.). These are distinct from "
        "StorageCollection helpers (input_boolean, counter, timer, etc.).\n\n"
        "Optionally filter by domain and/or sub_type. Returns entry_id, title, "
        "domain, state, and configuration for each helper."
    ),
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Filter by integration domain. If omitted, lists helpers "
                    "from all config-entry-flow domains."
                ),
                "enum": CONFIG_ENTRY_HELPER_DOMAINS,
            },
            "sub_type": {
                "type": "string",
                "description": (
                    "Filter by sub-type within a domain (e.g., 'sensor' for "
                    "template sensors, 'light' for light groups)"
                ),
            },
        },
    },
    permission="helpers_read",
)
async def list_config_entry_helpers(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """List all config-entry-flow-based helpers."""
    domain_filter = arguments.get("domain")
    sub_type_filter = arguments.get("sub_type")

    domains = [domain_filter] if domain_filter else CONFIG_ENTRY_HELPER_DOMAINS

    results = []
    for domain in domains:
        try:
            entries = hass.config_entries.async_entries(domain)
        except Exception:
            continue

        for entry in entries:
            if sub_type_filter:
                entry_options = entry.options or {}
                entry_sub_type = (
                    entry_options.get("template_type")
                    or entry_options.get("group_type")
                    or entry_options.get("type")
                    or ""
                )
                if entry_sub_type != sub_type_filter:
                    continue

            results.append({
                "entry_id": entry.entry_id,
                "title": entry.title,
                "domain": entry.domain,
                "state": (
                    entry.state.value
                    if hasattr(entry.state, "value")
                    else str(entry.state)
                ),
                "options": dict(entry.options) if entry.options else {},
            })

    results.sort(key=lambda x: (x["domain"], x.get("title", "").lower()))
    return results


# =============================================================================
# Get Config Entry Helper
# =============================================================================

@mcp_tool(
    name="ha_get_config_entry_helper",
    description=(
        "Get full details for a specific config-entry-flow helper by its config "
        "entry ID. Returns configuration, options, associated entities, and "
        "current state."
    ),
    schema={
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": (
                    "The config entry ID. Get this from "
                    "ha_list_config_entry_helpers."
                ),
            },
        },
        "required": ["entry_id"],
    },
    permission="helpers_read",
)
async def get_config_entry_helper(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Get a specific config-entry-flow helper."""
    entry_id = arguments["entry_id"]

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError(f"Config entry '{entry_id}' not found")

    if entry.domain not in CONFIG_ENTRY_HELPER_DOMAINS:
        raise ValueError(
            f"Config entry '{entry_id}' is not a config-entry helper "
            f"(domain: {entry.domain})"
        )

    result: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "domain": entry.domain,
        "state": (
            entry.state.value
            if hasattr(entry.state, "value")
            else str(entry.state)
        ),
        "supports_options": entry.supports_options,
        "supports_unload": entry.supports_unload,
        "options": dict(entry.options) if entry.options else {},
    }

    # Find associated entities
    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry_id)
    if entities:
        entity_entries = []
        for entity_entry in entities:
            entity_data: dict[str, Any] = {
                "entity_id": entity_entry.entity_id,
                "name": entity_entry.name or entity_entry.original_name,
                "area_id": entity_entry.area_id,
                "disabled": entity_entry.disabled_by is not None,
                "labels": (
                    list(entity_entry.labels) if entity_entry.labels else []
                ),
            }
            state = hass.states.get(entity_entry.entity_id)
            if state:
                entity_data["current_state"] = {
                    "state": state.state,
                    "attributes": dict(state.attributes),
                    "last_changed": (
                        state.last_changed.isoformat()
                        if state.last_changed
                        else None
                    ),
                }
            entity_entries.append(entity_data)
        result["entities"] = entity_entries

    return result


# =============================================================================
# Create Config Entry Helper
# =============================================================================

_CREATE_DESCRIPTION = (
    "Create a config-entry-flow helper. The flow is followed automatically - "
    "just provide domain, config fields, and sub_type if needed.\n\n"
    "For menu-based domains (group, template, random), sub_type is required.\n\n"
    "DOMAIN REFERENCE (* = required):\n\n"
    "DIRECT FORM DOMAINS:\n"
    "- derivative: name*, source* (entity_id), round_digits, "
    "time_window (dict {hours/minutes/seconds}), unit_prefix (n|u|m|k|M|G|T|P), "
    "unit_time (s|min|h|d)\n"
    "- generic_hygrostat: name*, device_class* (humidifier|dehumidifier), "
    "sensor* (humidity entity_id), humidifier* (switch/fan entity_id), "
    "dry_tolerance*, wet_tolerance*\n"
    "- integration: name*, source_sensor* (entity_id), "
    "method (trapezoidal|left|right), round_digits, unit_prefix (k|M|G|T), "
    "unit_time (s|min|h|d)\n"
    "- min_max: name*, entity_ids* (list of entity_ids), "
    "type* (min|max|mean|median|last|range|sum), round_digits\n"
    "- mold_indicator: name*, indoor_temp* (entity_id), "
    "indoor_humidity* (entity_id), outdoor_temp* (entity_id), "
    "calibration_factor*\n"
    "- switch_as_x: entity_id* (switch entity), "
    "target_domain* (cover|fan|light|lock|siren|valve), invert\n"
    "- threshold: name*, entity_id* (sensor), lower and/or upper "
    "(at least one required), hysteresis\n"
    "- tod: name*, after_time* (HH:MM:SS), before_time* (HH:MM:SS)\n"
    "- utility_meter: name*, source_sensor* (entity_id), "
    "meter_type* (none|quarter-hourly|hourly|daily|weekly|monthly|"
    "bimonthly|quarterly|yearly), tariffs (list), net_consumption, "
    "delta_values, periodically_resetting\n\n"
    "MULTI-STEP FORM DOMAINS:\n"
    "- filter: name*, entity_id*, filter_name* (lowpass|outlier|range|"
    "throttle|time_sma|time_throttle), filter_window_size, filter_radius, "
    "filter_precision\n"
    "- generic_thermostat: name*, ac_mode* (bool), sensor* (temp entity_id), "
    "heater* (switch/fan entity_id), cold_tolerance*, hot_tolerance*, "
    "min_temp, max_temp\n"
    "- history_stats: name*, entity_id*, type* (time|ratio|count), "
    "state* (list of state strings)\n"
    "- statistics: name*, entity_id*, state_characteristic* "
    "(average_linear|count|mean|median|standard_deviation|sum|value_max|"
    "value_min|variance|etc.)\n"
    "- trend: name*, entity_id* (sensor), attribute, invert, max_samples, "
    "min_samples, min_gradient, sample_duration\n\n"
    "MENU DOMAINS (sub_type required):\n"
    "- group: sub_type* (binary_sensor|cover|fan|light|lock|media_player|"
    "sensor|switch|etc.), name*, entities* (list), hide_members, "
    "all (bool, for binary_sensor/light/switch), "
    "type (sensor: min|max|mean|median|sum)\n"
    "- random: sub_type* (binary_sensor|sensor), name*, minimum, maximum, "
    "device_class\n"
    "- template: sub_type* (sensor|binary_sensor|switch|number|select|"
    "button|cover|fan|light|lock|etc.), name*, state* (Jinja2), "
    "unit_of_measurement, device_class, state_class, availability"
)


@mcp_tool(
    name="ha_create_config_entry_helper",
    description=_CREATE_DESCRIPTION,
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The helper integration domain",
                "enum": CONFIG_ENTRY_HELPER_DOMAINS,
            },
            "sub_type": {
                "type": "string",
                "description": (
                    "Sub-type for menu domains. Required for group "
                    "(binary_sensor, cover, fan, light, lock, media_player, "
                    "sensor, switch), template (sensor, binary_sensor, switch, "
                    "number, etc.), and random (binary_sensor, sensor)."
                ),
            },
            "config": {
                "type": "object",
                "description": (
                    "Configuration fields as key-value pairs. Required and "
                    "optional fields depend on the domain - see tool description."
                ),
            },
        },
        "required": ["domain", "config"],
    },
    permission="helpers_create",
)
async def create_config_entry_helper(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Create a config-entry-flow helper."""
    domain = arguments["domain"]
    sub_type = arguments.get("sub_type")
    config_data = arguments.get("config", {})

    if domain not in CONFIG_ENTRY_HELPER_DOMAINS:
        raise ValueError(
            f"Invalid domain '{domain}'. Valid domains: "
            f"{', '.join(CONFIG_ENTRY_HELPER_DOMAINS)}"
        )

    if domain in MENU_FLOW_DOMAINS and not sub_type:
        raise ValueError(
            f"Domain '{domain}' requires sub_type parameter"
        )

    result = await _follow_config_flow(hass, domain, config_data, sub_type)

    entry_result = result.get("result", {})
    entry_id = (
        entry_result.entry_id
        if hasattr(entry_result, "entry_id")
        else entry_result.get("entry_id") if isinstance(entry_result, dict)
        else str(entry_result)
    )

    return {
        "entry_id": entry_id,
        "title": result.get("title", config_data.get("name", "")),
        "domain": domain,
        "sub_type": sub_type,
        "options": result.get("options", config_data),
        "message": f"{domain} helper created",
    }


# =============================================================================
# Update Config Entry Helper
# =============================================================================

@mcp_tool(
    name="ha_update_config_entry_helper",
    description=(
        "Update a config-entry-flow helper via its Options Flow. Provide the "
        "entry_id and the fields to update. Current options are merged with "
        "updates automatically.\n\n"
        "Use ha_list_config_entry_helpers to find entry IDs and current options.\n\n"
        "IMPORTANT: Optional enum fields (device_class, state_class) must be "
        "omitted entirely if not needed - empty strings may cause validation errors."
    ),
    schema={
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": (
                    "The config entry ID to update. Get this from "
                    "ha_list_config_entry_helpers."
                ),
            },
            "updates": {
                "type": "object",
                "description": (
                    "Fields to update as key-value pairs. Only provided fields "
                    "are changed; existing options are preserved."
                ),
            },
        },
        "required": ["entry_id", "updates"],
    },
    permission="helpers_update",
)
async def update_config_entry_helper(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Update a config-entry-flow helper via Options Flow."""
    entry_id = arguments["entry_id"]
    updates = arguments.get("updates", {})

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError(f"Config entry '{entry_id}' not found")

    if entry.domain not in CONFIG_ENTRY_HELPER_DOMAINS:
        raise ValueError(
            f"Config entry '{entry_id}' is not a config-entry helper "
            f"(domain: {entry.domain})"
        )

    if not entry.supports_options:
        raise ValueError(
            f"Helper '{entry.title}' ({entry.domain}) does not support "
            f"options updates"
        )

    if not updates:
        raise ValueError("No update fields provided")

    # Remove empty string values that could cause enum validation errors
    clean_updates = {
        k: v for k, v in updates.items() if v is not None and v != ""
    }

    await _follow_options_flow(hass, entry_id, clean_updates)

    return {
        "entry_id": entry_id,
        "title": entry.title,
        "domain": entry.domain,
        "updates": clean_updates,
        "message": f"{entry.domain} helper '{entry.title}' updated",
    }


# =============================================================================
# Delete Config Entry Helper
# =============================================================================

@mcp_tool(
    name="ha_delete_config_entry_helper",
    description=(
        "Delete a config-entry-flow helper by its config entry ID. This action "
        "cannot be undone. Use ha_list_config_entry_helpers to find entry IDs."
    ),
    schema={
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": (
                    "The config entry ID to delete. Get this from "
                    "ha_list_config_entry_helpers."
                ),
            },
        },
        "required": ["entry_id"],
    },
    permission="helpers_delete",
)
async def delete_config_entry_helper(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Delete a config-entry-flow helper."""
    entry_id = arguments["entry_id"]

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError(f"Config entry '{entry_id}' not found")

    if entry.domain not in CONFIG_ENTRY_HELPER_DOMAINS:
        raise ValueError(
            f"Config entry '{entry_id}' is not a config-entry helper "
            f"(domain: {entry.domain})"
        )

    title = entry.title
    domain = entry.domain

    try:
        result = await hass.config_entries.async_remove(entry_id)
    except Exception as err:
        raise ValueError(f"Failed to delete helper: {err}") from err

    return {
        "deleted": entry_id,
        "title": title,
        "domain": domain,
        "require_restart": result.get("require_restart", False),
        "message": f"{domain} helper '{title}' deleted",
    }
