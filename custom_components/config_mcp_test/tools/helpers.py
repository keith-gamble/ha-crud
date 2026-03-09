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
from ..const import HELPER_DOMAINS

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


def _get_storage_collection(hass: HomeAssistant, domain: str) -> Any:
    """Get Home Assistant's internal StorageCollection for a helper domain.

    This accesses the same collection that HA's WebSocket commands
    ({domain}/create, {domain}/update, {domain}/delete) use, ensuring
    in-memory state and disk storage stay in sync.

    Args:
        hass: Home Assistant instance
        domain: The helper domain (e.g., 'input_boolean')

    Returns:
        The StorageCollection instance for the domain

    Raises:
        ValueError: If the collection is not found
    """
    instances = hass.data.get(COLLECTION_INSTANCES_KEY)
    if instances is None:
        raise ValueError(
            f"No storage collections found in hass.data. "
            f"Ensure the {domain} integration is loaded."
        )

    collection = instances.get(domain)
    if collection is None:
        raise ValueError(
            f"No storage collection found for domain '{domain}'. "
            f"Ensure the {domain} integration is loaded."
        )

    return collection


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
# Template Helper Tools (Config Entry Flow API)
# =============================================================================

# Template sub-types available for creation
TEMPLATE_TYPES = [
    "alarm_control_panel", "binary_sensor", "button", "cover",
    "event", "fan", "image", "light", "lock", "number",
    "select", "sensor", "switch", "update", "vacuum", "weather",
]


@mcp_tool(
    name="ha_list_template_helpers",
    description=(
        "List all template-based helpers (template sensors, binary sensors, "
        "switches, etc.) that are created via Config Entry flows. These are "
        "distinct from input_* helpers. Returns entry_id, title, template_type, "
        "and configuration for each template helper."
    ),
    schema={
        "type": "object",
        "properties": {
            "template_type": {
                "type": "string",
                "description": (
                    "Filter by template sub-type (e.g., 'sensor', 'binary_sensor', "
                    "'switch'). If omitted, returns all template helpers."
                ),
                "enum": TEMPLATE_TYPES,
            },
        },
    },
    permission="helpers_read",
)
async def list_template_helpers(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """List all template-based helpers."""
    type_filter = arguments.get("template_type")
    entries = hass.config_entries.async_entries("template")

    results = []
    for entry in entries:
        template_type = entry.options.get("template_type", "")
        if type_filter and template_type != type_filter:
            continue

        results.append({
            "entry_id": entry.entry_id,
            "title": entry.title,
            "domain": "template",
            "template_type": template_type,
            "state": entry.state.value if hasattr(entry.state, "value") else str(entry.state),
            "options": dict(entry.options),
        })

    results.sort(key=lambda x: (x.get("template_type", ""), x.get("title", "").lower()))
    return results


@mcp_tool(
    name="ha_get_template_helper",
    description=(
        "Get full details for a specific template-based helper by its config "
        "entry ID. Returns the entry configuration, options, template type, "
        "and current state."
    ),
    schema={
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": (
                    "The config entry ID of the template helper. "
                    "Get this from ha_list_template_helpers."
                ),
            },
        },
        "required": ["entry_id"],
    },
    permission="helpers_read",
)
async def get_template_helper(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Get a specific template-based helper by config entry ID."""
    entry_id = arguments["entry_id"]

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError(f"Config entry '{entry_id}' not found")

    if entry.domain != "template":
        raise ValueError(
            f"Config entry '{entry_id}' is not a template helper "
            f"(domain: {entry.domain})"
        )

    template_type = entry.options.get("template_type", "")

    result: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "domain": "template",
        "template_type": template_type,
        "state": entry.state.value if hasattr(entry.state, "value") else str(entry.state),
        "supports_options": entry.supports_options,
        "supports_unload": entry.supports_unload,
        "options": dict(entry.options),
    }

    # Find the entity associated with this config entry
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
                "labels": list(entity_entry.labels) if entity_entry.labels else [],
            }
            # Add current state
            state = hass.states.get(entity_entry.entity_id)
            if state:
                entity_data["current_state"] = {
                    "state": state.state,
                    "attributes": dict(state.attributes),
                    "last_changed": state.last_changed.isoformat() if state.last_changed else None,
                }
            entity_entries.append(entity_data)
        result["entities"] = entity_entries

    return result


@mcp_tool(
    name="ha_create_template_helper",
    description=(
        "Create a template-based helper (template sensor, binary sensor, switch, "
        "etc.) using Home Assistant's Config Entry Flow API. This is a 3-step "
        "process handled automatically.\n\n"
        "Common template_type values: sensor, binary_sensor, switch, number, "
        "select, button, light, cover, fan, lock, vacuum, weather.\n\n"
        "The 'state' field is a Jinja2 template string, e.g.:\n"
        "  '{{ states(\"sensor.temperature\") }}'\n"
        "  '{{ is_state(\"binary_sensor.door\", \"on\") }}'\n\n"
        "IMPORTANT: Optional enum fields (device_class, state_class) must be "
        "omitted entirely if not needed — empty strings cause validation errors."
    ),
    schema={
        "type": "object",
        "properties": {
            "template_type": {
                "type": "string",
                "description": (
                    "The type of template helper to create. Common values: "
                    "sensor, binary_sensor, switch, number, select, button, "
                    "light, cover, fan, lock, vacuum, weather"
                ),
                "enum": TEMPLATE_TYPES,
            },
            "name": {
                "type": "string",
                "description": "Human-readable name for the template helper (required)",
            },
            "state": {
                "type": "string",
                "description": (
                    "Jinja2 template for the entity state (required). "
                    "Example: '{{ states(\"sensor.time\") }}'"
                ),
            },
            "unit_of_measurement": {
                "type": "string",
                "description": "Unit of measurement (sensor only, optional)",
            },
            "device_class": {
                "type": "string",
                "description": (
                    "Device class for the entity (optional). Must be a valid "
                    "value for the template_type — omit if not needed."
                ),
            },
            "state_class": {
                "type": "string",
                "description": (
                    "State class (sensor only, optional). Valid values: "
                    "measurement, measurement_angle, total, total_increasing. "
                    "Omit if not needed."
                ),
            },
            "availability": {
                "type": "string",
                "description": (
                    "Jinja2 template for availability (optional). "
                    "Should evaluate to true/false."
                ),
            },
            "device_id": {
                "type": "string",
                "description": "Device to associate the helper with (optional)",
            },
        },
        "required": ["template_type", "name", "state"],
    },
    permission="helpers_create",
)
async def create_template_helper(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Create a template-based helper via Config Entry Flow."""
    template_type = arguments["template_type"]
    name = arguments["name"]
    state = arguments["state"]

    # Step 1: Initiate the config entry flow
    try:
        result = await hass.config_entries.flow.async_init(
            "template", context={"source": "user"}
        )
    except Exception as err:
        raise ValueError(
            f"Failed to initiate template config flow: {err}. "
            f"Ensure the 'template' integration is loaded."
        ) from err

    flow_id = result["flow_id"]

    # Step 2: Select the template sub-type
    try:
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"next_step_id": template_type}
        )
    except Exception as err:
        raise ValueError(
            f"Failed to select template type '{template_type}': {err}"
        ) from err

    # Step 3: Submit the configuration
    config_data: dict[str, Any] = {
        "name": name,
        "state": state,
    }

    # Add optional fields only if provided (empty strings cause validation errors)
    for field in ("unit_of_measurement", "device_class", "state_class",
                  "availability", "device_id"):
        if field in arguments and arguments[field]:
            config_data[field] = arguments[field]

    try:
        result = await hass.config_entries.flow.async_configure(
            flow_id, config_data
        )
    except Exception as err:
        raise ValueError(
            f"Failed to create template helper: {err}"
        ) from err

    if result.get("type") != "create_entry":
        raise ValueError(
            f"Unexpected flow result type: {result.get('type')}. "
            f"Expected 'create_entry'. Result: {result}"
        )

    entry_result = result.get("result", {})
    entry_id = (
        entry_result.entry_id
        if hasattr(entry_result, "entry_id")
        else entry_result.get("entry_id")
    )

    return {
        "entry_id": entry_id,
        "title": result.get("title", name),
        "domain": "template",
        "template_type": template_type,
        "options": result.get("options", config_data),
        "message": f"Template {template_type} helper '{name}' created",
    }


@mcp_tool(
    name="ha_update_template_helper",
    description=(
        "Update a template-based helper's configuration via the Options Flow API. "
        "Use ha_list_template_helpers to find entry IDs and current options.\n\n"
        "IMPORTANT: Optional enum fields (device_class, state_class) must be "
        "omitted entirely if not needed — empty strings cause validation errors."
    ),
    schema={
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": (
                    "The config entry ID of the template helper to update. "
                    "Get this from ha_list_template_helpers."
                ),
            },
            "name": {
                "type": "string",
                "description": "New name for the template helper",
            },
            "state": {
                "type": "string",
                "description": (
                    "New Jinja2 template for the entity state. "
                    "Example: '{{ states(\"sensor.temperature\") }}'"
                ),
            },
            "unit_of_measurement": {
                "type": "string",
                "description": "New unit of measurement (sensor only, optional)",
            },
            "device_class": {
                "type": "string",
                "description": "New device class (optional, omit to clear)",
            },
            "state_class": {
                "type": "string",
                "description": (
                    "New state class (sensor only, optional). Valid values: "
                    "measurement, measurement_angle, total, total_increasing"
                ),
            },
            "availability": {
                "type": "string",
                "description": "New Jinja2 availability template (optional)",
            },
        },
        "required": ["entry_id"],
    },
    permission="helpers_update",
)
async def update_template_helper(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Update a template-based helper via Options Flow."""
    entry_id = arguments["entry_id"]

    # Verify the entry exists and is a template helper
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError(f"Config entry '{entry_id}' not found")

    if entry.domain != "template":
        raise ValueError(
            f"Config entry '{entry_id}' is not a template helper "
            f"(domain: {entry.domain})"
        )

    if not entry.supports_options:
        raise ValueError(
            f"Template helper '{entry.title}' does not support options updates"
        )

    # Start the options flow
    try:
        result = await hass.config_entries.options.async_init(entry_id)
    except Exception as err:
        raise ValueError(
            f"Failed to start options flow for '{entry.title}': {err}"
        ) from err

    flow_id = result["flow_id"]

    # Build update data from current options merged with provided updates
    current_options = dict(entry.options)
    update_data: dict[str, Any] = {}

    # Carry forward existing values, override with provided ones
    for field in ("name", "state", "unit_of_measurement", "device_class",
                  "state_class", "availability"):
        if field in arguments:
            # Only include non-empty values for enum fields
            if arguments[field]:
                update_data[field] = arguments[field]
        elif field in current_options:
            update_data[field] = current_options[field]

    try:
        result = await hass.config_entries.options.async_configure(
            flow_id, update_data
        )
    except Exception as err:
        raise ValueError(
            f"Failed to update template helper: {err}"
        ) from err

    return {
        "entry_id": entry_id,
        "title": entry.title,
        "domain": "template",
        "template_type": entry.options.get("template_type", ""),
        "options": update_data,
        "message": f"Template helper '{entry.title}' updated",
    }


@mcp_tool(
    name="ha_delete_template_helper",
    description=(
        "Delete a template-based helper by its config entry ID. Use "
        "ha_list_template_helpers to find entry IDs. This action cannot be undone."
    ),
    schema={
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": (
                    "The config entry ID of the template helper to delete. "
                    "Get this from ha_list_template_helpers."
                ),
            },
        },
        "required": ["entry_id"],
    },
    permission="helpers_delete",
)
async def delete_template_helper(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Delete a template-based helper by config entry ID."""
    entry_id = arguments["entry_id"]

    # Verify the entry exists and is a template helper
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError(f"Config entry '{entry_id}' not found")

    if entry.domain != "template":
        raise ValueError(
            f"Config entry '{entry_id}' is not a template helper "
            f"(domain: {entry.domain})"
        )

    title = entry.title

    try:
        result = await hass.config_entries.async_remove(entry_id)
    except Exception as err:
        raise ValueError(f"Failed to delete template helper: {err}") from err

    return {
        "deleted": entry_id,
        "title": title,
        "domain": "template",
        "require_restart": result.get("require_restart", False),
        "message": f"Template helper '{title}' deleted",
    }
