"""HTTP views for category and label REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    category_registry as cr,
    label_registry as lr,
)

from ..const import (
    API_BASE_PATH_CATEGORIES,
    API_BASE_PATH_LABELS,
    CATEGORY_SCOPES,
    CONF_CATEGORIES_CREATE,
    CONF_CATEGORIES_DELETE,
    CONF_CATEGORIES_READ,
    CONF_CATEGORIES_UPDATE,
    CONF_LABELS_CREATE,
    CONF_LABELS_DELETE,
    CONF_LABELS_READ,
    CONF_LABELS_UPDATE,
    DEFAULT_OPTIONS,
    DOMAIN,
    ERR_CATEGORY_EXISTS,
    ERR_CATEGORY_INVALID_SCOPE,
    ERR_CATEGORY_NOT_FOUND,
    ERR_INVALID_CONFIG,
    ERR_LABEL_EXISTS,
    ERR_LABEL_NOT_FOUND,
)

_LOGGER = logging.getLogger(__name__)


def get_config_options(hass: HomeAssistant) -> dict[str, Any]:
    """Get the current configuration options for config_mcp."""
    options = DEFAULT_OPTIONS.copy()

    if DOMAIN in hass.data:
        for entry_id, entry_data in hass.data[DOMAIN].items():
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.entry_id == entry_id:
                    options.update(entry.options)
                    break

    return options


def check_permission(hass: HomeAssistant, permission: str) -> bool:
    """Check if a specific permission is enabled."""
    options = get_config_options(hass)
    return options.get(permission, False)


# =============================================================================
# Category Views
# =============================================================================

class CategoryScopeListView(HomeAssistantView):
    """View to list categories for a specific scope."""

    url = API_BASE_PATH_CATEGORIES + "/{scope}"
    name = "api:config_mcp:categories:scope"
    requires_auth = True

    async def get(self, request: web.Request, scope: str) -> web.Response:
        """Handle GET request - list all categories for a scope.

        Path params:
            scope: The category scope (automation, script, helper)

        Returns:
            200: JSON array of category data
            400: Invalid scope
            403: Permission denied
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_CATEGORIES_READ):
            return self.json_message(
                "Category read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        if scope not in CATEGORY_SCOPES:
            return self.json_message(
                f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}",
                HTTPStatus.BAD_REQUEST,
                ERR_CATEGORY_INVALID_SCOPE,
            )

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
        return self.json(categories)

    async def post(self, request: web.Request, scope: str) -> web.Response:
        """Handle POST request - create new category.

        Path params:
            scope: The category scope

        Request body:
            {
                "name": "Category Name",
                "icon": "mdi:folder"  (optional)
            }

        Returns:
            201: Category created
            400: Invalid request or scope
            401: Not authorized
            403: Permission denied
            409: Category already exists
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_CATEGORIES_CREATE):
            return self.json_message(
                "Category create permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        if scope not in CATEGORY_SCOPES:
            return self.json_message(
                f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}",
                HTTPStatus.BAD_REQUEST,
                ERR_CATEGORY_INVALID_SCOPE,
            )

        try:
            body = await request.json()
        except ValueError:
            return self.json_message(
                "Invalid JSON in request body",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        if "name" not in body:
            return self.json_message(
                "Missing required field: name",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        name = body["name"]
        icon = body.get("icon")

        category_registry = cr.async_get(hass)

        # Check if name already exists
        for existing in category_registry.async_list_categories(scope=scope):
            if existing.name.lower() == name.lower():
                return self.json_message(
                    f"Category with name '{name}' already exists in scope '{scope}'",
                    HTTPStatus.CONFLICT,
                    ERR_CATEGORY_EXISTS,
                )

        try:
            category = category_registry.async_create(
                scope=scope,
                name=name,
                icon=icon,
            )
        except Exception as err:
            _LOGGER.exception("Error creating category: %s", err)
            return self.json_message(
                f"Error creating category: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json(
            {
                "category_id": category.category_id,
                "name": category.name,
                "icon": category.icon,
                "scope": scope,
                "message": "Category created",
            },
            HTTPStatus.CREATED,
        )


class CategoryDetailView(HomeAssistantView):
    """View for single category operations."""

    url = API_BASE_PATH_CATEGORIES + "/{scope}/{category_id}"
    name = "api:config_mcp:category"
    requires_auth = True

    async def get(
        self, request: web.Request, scope: str, category_id: str
    ) -> web.Response:
        """Handle GET request - get single category.

        Path params:
            scope: The category scope
            category_id: The category ID

        Returns:
            200: Category data
            400: Invalid scope
            403: Permission denied
            404: Category not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_CATEGORIES_READ):
            return self.json_message(
                "Category read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        if scope not in CATEGORY_SCOPES:
            return self.json_message(
                f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}",
                HTTPStatus.BAD_REQUEST,
                ERR_CATEGORY_INVALID_SCOPE,
            )

        category_registry = cr.async_get(hass)
        category = category_registry.async_get_category(scope=scope, category_id=category_id)

        if category is None:
            return self.json_message(
                f"Category '{category_id}' not found in scope '{scope}'",
                HTTPStatus.NOT_FOUND,
                ERR_CATEGORY_NOT_FOUND,
            )

        return self.json({
            "category_id": category.category_id,
            "name": category.name,
            "icon": category.icon,
            "scope": scope,
            "created_at": category.created_at.isoformat() if category.created_at else None,
            "modified_at": category.modified_at.isoformat() if category.modified_at else None,
        })

    async def patch(
        self, request: web.Request, scope: str, category_id: str
    ) -> web.Response:
        """Handle PATCH request - update category.

        Path params:
            scope: The category scope
            category_id: The category ID

        Request body:
            {
                "name": "New Name",  (optional)
                "icon": "mdi:new-icon"  (optional)
            }

        Returns:
            200: Category updated
            400: Invalid request or scope
            401: Not authorized
            403: Permission denied
            404: Category not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_CATEGORIES_UPDATE):
            return self.json_message(
                "Category update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        if scope not in CATEGORY_SCOPES:
            return self.json_message(
                f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}",
                HTTPStatus.BAD_REQUEST,
                ERR_CATEGORY_INVALID_SCOPE,
            )

        try:
            body = await request.json()
        except ValueError:
            return self.json_message(
                "Invalid JSON in request body",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        category_registry = cr.async_get(hass)
        category = category_registry.async_get_category(scope=scope, category_id=category_id)

        if category is None:
            return self.json_message(
                f"Category '{category_id}' not found in scope '{scope}'",
                HTTPStatus.NOT_FOUND,
                ERR_CATEGORY_NOT_FOUND,
            )

        # Build update kwargs
        updates = {}
        if "name" in body:
            updates["name"] = body["name"]
        if "icon" in body:
            updates["icon"] = body["icon"]

        if not updates:
            return self.json_message(
                "No updates provided",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        try:
            updated = category_registry.async_update(scope=scope, category_id=category_id, **updates)
        except Exception as err:
            _LOGGER.exception("Error updating category: %s", err)
            return self.json_message(
                f"Error updating category: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "category_id": updated.category_id,
            "name": updated.name,
            "icon": updated.icon,
            "scope": scope,
            "message": "Category updated",
        })

    async def delete(
        self, request: web.Request, scope: str, category_id: str
    ) -> web.Response:
        """Handle DELETE request - delete category.

        Path params:
            scope: The category scope
            category_id: The category ID

        Returns:
            204: Category deleted
            400: Invalid scope
            401: Not authorized
            403: Permission denied
            404: Category not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_CATEGORIES_DELETE):
            return self.json_message(
                "Category delete permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        if scope not in CATEGORY_SCOPES:
            return self.json_message(
                f"Invalid scope '{scope}'. Valid scopes: {', '.join(CATEGORY_SCOPES)}",
                HTTPStatus.BAD_REQUEST,
                ERR_CATEGORY_INVALID_SCOPE,
            )

        category_registry = cr.async_get(hass)
        category = category_registry.async_get_category(scope=scope, category_id=category_id)

        if category is None:
            return self.json_message(
                f"Category '{category_id}' not found in scope '{scope}'",
                HTTPStatus.NOT_FOUND,
                ERR_CATEGORY_NOT_FOUND,
            )

        try:
            category_registry.async_delete(scope=scope, category_id=category_id)
        except Exception as err:
            _LOGGER.exception("Error deleting category: %s", err)
            return self.json_message(
                f"Error deleting category: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return web.Response(status=HTTPStatus.NO_CONTENT)


# =============================================================================
# Label Views
# =============================================================================

class LabelListView(HomeAssistantView):
    """View to list all labels."""

    url = API_BASE_PATH_LABELS
    name = "api:config_mcp:labels"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all labels.

        Returns:
            200: JSON array of label data
            403: Permission denied
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_LABELS_READ):
            return self.json_message(
                "Label read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

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
        return self.json(labels)

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request - create new label.

        Request body:
            {
                "name": "Label Name",
                "icon": "mdi:tag",  (optional)
                "color": "red",  (optional)
                "description": "Description"  (optional)
            }

        Returns:
            201: Label created
            400: Invalid request
            401: Not authorized
            403: Permission denied
            409: Label already exists
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_LABELS_CREATE):
            return self.json_message(
                "Label create permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        try:
            body = await request.json()
        except ValueError:
            return self.json_message(
                "Invalid JSON in request body",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        if "name" not in body:
            return self.json_message(
                "Missing required field: name",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        name = body["name"]
        icon = body.get("icon")
        color = body.get("color")
        description = body.get("description")

        label_registry = lr.async_get(hass)

        # Check if name already exists
        for existing in label_registry.async_list_labels():
            if existing.name.lower() == name.lower():
                return self.json_message(
                    f"Label with name '{name}' already exists",
                    HTTPStatus.CONFLICT,
                    ERR_LABEL_EXISTS,
                )

        try:
            label = label_registry.async_create(
                name=name,
                icon=icon,
                color=color,
                description=description,
            )
        except Exception as err:
            _LOGGER.exception("Error creating label: %s", err)
            return self.json_message(
                f"Error creating label: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json(
            {
                "label_id": label.label_id,
                "name": label.name,
                "icon": label.icon,
                "color": label.color,
                "description": label.description,
                "message": "Label created",
            },
            HTTPStatus.CREATED,
        )


class LabelDetailView(HomeAssistantView):
    """View for single label operations."""

    url = API_BASE_PATH_LABELS + "/{label_id}"
    name = "api:config_mcp:label"
    requires_auth = True

    async def get(self, request: web.Request, label_id: str) -> web.Response:
        """Handle GET request - get single label.

        Path params:
            label_id: The label ID

        Returns:
            200: Label data
            403: Permission denied
            404: Label not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_LABELS_READ):
            return self.json_message(
                "Label read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        label_registry = lr.async_get(hass)
        label = label_registry.async_get_label(label_id)

        if label is None:
            return self.json_message(
                f"Label '{label_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_LABEL_NOT_FOUND,
            )

        return self.json({
            "label_id": label.label_id,
            "name": label.name,
            "icon": label.icon,
            "color": label.color,
            "description": label.description,
            "created_at": label.created_at.isoformat() if label.created_at else None,
            "modified_at": label.modified_at.isoformat() if label.modified_at else None,
        })

    async def patch(self, request: web.Request, label_id: str) -> web.Response:
        """Handle PATCH request - update label.

        Path params:
            label_id: The label ID

        Request body:
            {
                "name": "New Name",  (optional)
                "icon": "mdi:new-icon",  (optional)
                "color": "blue",  (optional)
                "description": "New description"  (optional)
            }

        Returns:
            200: Label updated
            400: Invalid request
            401: Not authorized
            403: Permission denied
            404: Label not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_LABELS_UPDATE):
            return self.json_message(
                "Label update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        try:
            body = await request.json()
        except ValueError:
            return self.json_message(
                "Invalid JSON in request body",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        label_registry = lr.async_get(hass)
        label = label_registry.async_get_label(label_id)

        if label is None:
            return self.json_message(
                f"Label '{label_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_LABEL_NOT_FOUND,
            )

        # Build update kwargs
        updates = {}
        if "name" in body:
            updates["name"] = body["name"]
        if "icon" in body:
            updates["icon"] = body["icon"]
        if "color" in body:
            updates["color"] = body["color"]
        if "description" in body:
            updates["description"] = body["description"]

        if not updates:
            return self.json_message(
                "No updates provided",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        try:
            updated = label_registry.async_update(label_id, **updates)
        except Exception as err:
            _LOGGER.exception("Error updating label: %s", err)
            return self.json_message(
                f"Error updating label: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "label_id": updated.label_id,
            "name": updated.name,
            "icon": updated.icon,
            "color": updated.color,
            "description": updated.description,
            "message": "Label updated",
        })

    async def delete(self, request: web.Request, label_id: str) -> web.Response:
        """Handle DELETE request - delete label.

        Path params:
            label_id: The label ID

        Returns:
            204: Label deleted
            401: Not authorized
            403: Permission denied
            404: Label not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_LABELS_DELETE):
            return self.json_message(
                "Label delete permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        label_registry = lr.async_get(hass)
        label = label_registry.async_get_label(label_id)

        if label is None:
            return self.json_message(
                f"Label '{label_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_LABEL_NOT_FOUND,
            )

        try:
            label_registry.async_delete(label_id)
        except Exception as err:
            _LOGGER.exception("Error deleting label: %s", err)
            return self.json_message(
                f"Error deleting label: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return web.Response(status=HTTPStatus.NO_CONTENT)
