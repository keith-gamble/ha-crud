"""MCP Tools for Categories and Labels.

Categories provide scope-specific organization (e.g., automation categories, script categories).
Labels provide cross-scope tagging for entities, automations, scripts, etc.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    category_registry as cr,
    label_registry as lr,
)

from ..mcp_registry import mcp_tool
from ..const import CATEGORY_SCOPES

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Category Tools
# =============================================================================

@mcp_tool(
    name="ha_list_categories",
    description=(
        "List all categories for a given scope. Categories provide organization "
        "within a specific scope like 'automation', 'script', or 'helper'. "
        "Returns category info including id, name, icon, and timestamps."
    ),
    schema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": f"The category scope. Valid values: {', '.join(CATEGORY_SCOPES)}",
                "enum": CATEGORY_SCOPES,
            }
        },
        "required": ["scope"],
    },
    permission="categories_read",
)
async def list_categories(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all categories for a scope."""
    scope = arguments["scope"]

    if scope not in CATEGORY_SCOPES:
        raise ValueError(f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}")

    category_registry = cr.async_get(hass)

    categories = []
    for category in category_registry.async_list_categories(scope=scope):
        categories.append({
            "category_id": category.category_id,
            "name": category.name,
            "icon": category.icon,
            "scope": scope,
            "created_at": category.created_at.isoformat() if category.created_at else None,
            "modified_at": category.modified_at.isoformat() if category.modified_at else None,
        })

    categories.sort(key=lambda x: x["name"].lower())
    return categories


@mcp_tool(
    name="ha_get_category",
    description=(
        "Get full details for a specific category including its ID, name, icon, "
        "and timestamps."
    ),
    schema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": f"The category scope. Valid values: {', '.join(CATEGORY_SCOPES)}",
                "enum": CATEGORY_SCOPES,
            },
            "category_id": {
                "type": "string",
                "description": "The category ID (ULID format)",
            }
        },
        "required": ["scope", "category_id"],
    },
    permission="categories_read",
)
async def get_category(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get a single category by ID."""
    scope = arguments["scope"]
    category_id = arguments["category_id"]

    if scope not in CATEGORY_SCOPES:
        raise ValueError(f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}")

    category_registry = cr.async_get(hass)
    category = category_registry.async_get_category(scope=scope, category_id=category_id)

    if category is None:
        raise ValueError(f"Category '{category_id}' not found in scope '{scope}'")

    return {
        "category_id": category.category_id,
        "name": category.name,
        "icon": category.icon,
        "scope": scope,
        "created_at": category.created_at.isoformat() if category.created_at else None,
        "modified_at": category.modified_at.isoformat() if category.modified_at else None,
    }


@mcp_tool(
    name="ha_create_category",
    description=(
        "Create a new category for a given scope. Categories help organize "
        "automations, scripts, or helpers into logical groups."
    ),
    schema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": f"The category scope. Valid values: {', '.join(CATEGORY_SCOPES)}",
                "enum": CATEGORY_SCOPES,
            },
            "name": {
                "type": "string",
                "description": "The category name (must be unique within the scope)",
            },
            "icon": {
                "type": "string",
                "description": "Material Design Icon (e.g., 'mdi:folder')",
            },
        },
        "required": ["scope", "name"],
    },
    permission="categories_create",
)
async def create_category(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a new category."""
    scope = arguments["scope"]
    name = arguments["name"]
    icon = arguments.get("icon")

    if scope not in CATEGORY_SCOPES:
        raise ValueError(f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}")

    category_registry = cr.async_get(hass)

    # Check if name already exists in scope
    for existing in category_registry.async_list_categories(scope=scope):
        if existing.name.lower() == name.lower():
            raise ValueError(f"Category with name '{name}' already exists in scope '{scope}'")

    try:
        category = category_registry.async_create(
            scope=scope,
            name=name,
            icon=icon,
        )
    except Exception as err:
        raise ValueError(f"Failed to create category: {err}")

    return {
        "category_id": category.category_id,
        "name": category.name,
        "icon": category.icon,
        "scope": scope,
        "message": "Category created",
    }


@mcp_tool(
    name="ha_update_category",
    description=(
        "Update an existing category's name or icon."
    ),
    schema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": f"The category scope. Valid values: {', '.join(CATEGORY_SCOPES)}",
                "enum": CATEGORY_SCOPES,
            },
            "category_id": {
                "type": "string",
                "description": "The category ID to update",
            },
            "name": {
                "type": "string",
                "description": "New name for the category",
            },
            "icon": {
                "type": "string",
                "description": "New icon for the category (e.g., 'mdi:folder')",
            },
        },
        "required": ["scope", "category_id"],
    },
    permission="categories_update",
)
async def update_category(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Update an existing category."""
    scope = arguments["scope"]
    category_id = arguments["category_id"]

    if scope not in CATEGORY_SCOPES:
        raise ValueError(f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}")

    category_registry = cr.async_get(hass)
    category = category_registry.async_get_category(scope=scope, category_id=category_id)

    if category is None:
        raise ValueError(f"Category '{category_id}' not found in scope '{scope}'")

    # Build update kwargs
    updates = {}
    if "name" in arguments:
        updates["name"] = arguments["name"]
    if "icon" in arguments:
        updates["icon"] = arguments["icon"]

    if not updates:
        raise ValueError("No updates provided. Specify 'name' or 'icon' to update.")

    try:
        updated = category_registry.async_update(scope=scope, category_id=category_id, **updates)
    except Exception as err:
        raise ValueError(f"Failed to update category: {err}")

    return {
        "category_id": updated.category_id,
        "name": updated.name,
        "icon": updated.icon,
        "scope": scope,
        "message": "Category updated",
    }


@mcp_tool(
    name="ha_delete_category",
    description=(
        "Delete a category. Items using this category will have their category "
        "assignment cleared. This action cannot be undone."
    ),
    schema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": f"The category scope. Valid values: {', '.join(CATEGORY_SCOPES)}",
                "enum": CATEGORY_SCOPES,
            },
            "category_id": {
                "type": "string",
                "description": "The category ID to delete",
            },
        },
        "required": ["scope", "category_id"],
    },
    permission="categories_delete",
)
async def delete_category(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Delete a category."""
    scope = arguments["scope"]
    category_id = arguments["category_id"]

    if scope not in CATEGORY_SCOPES:
        raise ValueError(f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}")

    category_registry = cr.async_get(hass)
    category = category_registry.async_get_category(scope=scope, category_id=category_id)

    if category is None:
        raise ValueError(f"Category '{category_id}' not found in scope '{scope}'")

    try:
        category_registry.async_delete(scope=scope, category_id=category_id)
    except Exception as err:
        raise ValueError(f"Failed to delete category: {err}")

    return {"deleted": category_id, "scope": scope}


# =============================================================================
# Label Tools
# =============================================================================

@mcp_tool(
    name="ha_list_labels",
    description=(
        "List all labels in Home Assistant. Labels are cross-scope tags that can "
        "be applied to entities, automations, scripts, devices, and areas. "
        "Returns label info including id, name, color, icon, and description."
    ),
    permission="labels_read",
)
async def list_labels(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all labels."""
    label_registry = lr.async_get(hass)

    labels = []
    for label in label_registry.async_list_labels():
        labels.append({
            "label_id": label.label_id,
            "name": label.name,
            "icon": label.icon,
            "color": label.color,
            "description": label.description,
            "created_at": label.created_at.isoformat() if label.created_at else None,
            "modified_at": label.modified_at.isoformat() if label.modified_at else None,
        })

    labels.sort(key=lambda x: x["name"].lower())
    return labels


@mcp_tool(
    name="ha_get_label",
    description=(
        "Get full details for a specific label including its ID, name, icon, "
        "color, description, and timestamps."
    ),
    schema={
        "type": "object",
        "properties": {
            "label_id": {
                "type": "string",
                "description": "The label ID",
            }
        },
        "required": ["label_id"],
    },
    permission="labels_read",
)
async def get_label(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get a single label by ID."""
    label_id = arguments["label_id"]

    label_registry = lr.async_get(hass)
    label = label_registry.async_get_label(label_id)

    if label is None:
        raise ValueError(f"Label '{label_id}' not found")

    return {
        "label_id": label.label_id,
        "name": label.name,
        "icon": label.icon,
        "color": label.color,
        "description": label.description,
        "created_at": label.created_at.isoformat() if label.created_at else None,
        "modified_at": label.modified_at.isoformat() if label.modified_at else None,
    }


@mcp_tool(
    name="ha_create_label",
    description=(
        "Create a new label. Labels can be applied to entities, automations, "
        "scripts, devices, and areas for cross-scope organization."
    ),
    schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The label name (must be unique)",
            },
            "icon": {
                "type": "string",
                "description": "Material Design Icon (e.g., 'mdi:tag')",
            },
            "color": {
                "type": "string",
                "description": "Color for the label (e.g., 'red', 'blue', 'green', or hex like '#FF5733')",
            },
            "description": {
                "type": "string",
                "description": "Description of the label",
            },
        },
        "required": ["name"],
    },
    permission="labels_create",
)
async def create_label(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a new label."""
    name = arguments["name"]
    icon = arguments.get("icon")
    color = arguments.get("color")
    description = arguments.get("description")

    label_registry = lr.async_get(hass)

    # Check if name already exists
    for existing in label_registry.async_list_labels():
        if existing.name.lower() == name.lower():
            raise ValueError(f"Label with name '{name}' already exists")

    try:
        label = label_registry.async_create(
            name=name,
            icon=icon,
            color=color,
            description=description,
        )
    except Exception as err:
        raise ValueError(f"Failed to create label: {err}")

    return {
        "label_id": label.label_id,
        "name": label.name,
        "icon": label.icon,
        "color": label.color,
        "description": label.description,
        "message": "Label created",
    }


@mcp_tool(
    name="ha_update_label",
    description=(
        "Update an existing label's name, icon, color, or description."
    ),
    schema={
        "type": "object",
        "properties": {
            "label_id": {
                "type": "string",
                "description": "The label ID to update",
            },
            "name": {
                "type": "string",
                "description": "New name for the label",
            },
            "icon": {
                "type": "string",
                "description": "New icon for the label (e.g., 'mdi:tag')",
            },
            "color": {
                "type": "string",
                "description": "New color for the label",
            },
            "description": {
                "type": "string",
                "description": "New description for the label",
            },
        },
        "required": ["label_id"],
    },
    permission="labels_update",
)
async def update_label(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Update an existing label."""
    label_id = arguments["label_id"]

    label_registry = lr.async_get(hass)
    label = label_registry.async_get_label(label_id)

    if label is None:
        raise ValueError(f"Label '{label_id}' not found")

    # Build update kwargs
    updates = {}
    if "name" in arguments:
        updates["name"] = arguments["name"]
    if "icon" in arguments:
        updates["icon"] = arguments["icon"]
    if "color" in arguments:
        updates["color"] = arguments["color"]
    if "description" in arguments:
        updates["description"] = arguments["description"]

    if not updates:
        raise ValueError("No updates provided. Specify 'name', 'icon', 'color', or 'description' to update.")

    try:
        updated = label_registry.async_update(label_id, **updates)
    except Exception as err:
        raise ValueError(f"Failed to update label: {err}")

    return {
        "label_id": updated.label_id,
        "name": updated.name,
        "icon": updated.icon,
        "color": updated.color,
        "description": updated.description,
        "message": "Label updated",
    }


@mcp_tool(
    name="ha_delete_label",
    description=(
        "Delete a label. Items using this label will have the label removed from "
        "their label list. This action cannot be undone."
    ),
    schema={
        "type": "object",
        "properties": {
            "label_id": {
                "type": "string",
                "description": "The label ID to delete",
            },
        },
        "required": ["label_id"],
    },
    permission="labels_delete",
)
async def delete_label(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Delete a label."""
    label_id = arguments["label_id"]

    label_registry = lr.async_get(hass)
    label = label_registry.async_get_label(label_id)

    if label is None:
        raise ValueError(f"Label '{label_id}' not found")

    try:
        label_registry.async_delete(label_id)
    except Exception as err:
        raise ValueError(f"Failed to delete label: {err}")

    return {"deleted": label_id}
