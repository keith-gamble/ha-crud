"""HTTP views for helper REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import (
    API_BASE_PATH_HELPERS,
    CONF_HELPERS_CREATE,
    CONF_HELPERS_DELETE,
    CONF_HELPERS_READ,
    CONF_HELPERS_UPDATE,
    DEFAULT_OPTIONS,
    DOMAIN,
    ERR_HELPER_INVALID_CONFIG,
    ERR_HELPER_INVALID_DOMAIN,
    ERR_HELPER_NOT_FOUND,
    ERR_INVALID_CONFIG,
    HELPER_DOMAINS,
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


async def _get_helpers_for_domain(hass: HomeAssistant, domain: str) -> list[dict[str, Any]]:
    """Get all helpers for a specific domain using the component's storage.

    Args:
        hass: Home Assistant instance
        domain: The helper domain (e.g., 'input_boolean')

    Returns:
        List of helper configurations
    """
    helpers = []

    # Access the component's storage collection
    component_data = hass.data.get(domain)
    if component_data is None:
        return helpers

    # The storage collection is typically at component.async_get_or_create
    # or accessed via the yaml_collection/storage_collection pattern
    collection = None

    # Try to get the storage collection
    if hasattr(component_data, "storage_collection"):
        collection = component_data.storage_collection
    elif hasattr(component_data, "async_items"):
        # Direct collection access
        collection = component_data
    elif isinstance(component_data, dict):
        # Some components store collection under a key
        collection = component_data.get("collection") or component_data.get("storage_collection")

    if collection is not None and hasattr(collection, "async_items"):
        items = collection.async_items()
        for item in items:
            if isinstance(item, dict):
                helpers.append({
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "domain": domain,
                    **{k: v for k, v in item.items() if k not in ("id", "name")},
                })
            elif hasattr(item, "as_dict"):
                item_dict = item.as_dict()
                helpers.append({
                    "id": item_dict.get("id"),
                    "name": item_dict.get("name"),
                    "domain": domain,
                    **{k: v for k, v in item_dict.items() if k not in ("id", "name")},
                })

    return helpers


async def _get_all_helpers(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Get all helpers across all supported domains.

    Args:
        hass: Home Assistant instance

    Returns:
        List of all helper configurations
    """
    all_helpers = []

    for domain in HELPER_DOMAINS:
        try:
            domain_helpers = await _get_helpers_for_domain(hass, domain)
            all_helpers.extend(domain_helpers)
        except Exception as err:
            _LOGGER.warning("Error getting helpers for domain %s: %s", domain, err)
            continue

    return all_helpers


async def _get_helper_by_id(
    hass: HomeAssistant,
    helper_id: str
) -> tuple[str | None, dict[str, Any] | None]:
    """Get a specific helper by ID.

    Args:
        hass: Home Assistant instance
        helper_id: The helper ID

    Returns:
        Tuple of (domain, helper_config) or (None, None) if not found
    """
    for domain in HELPER_DOMAINS:
        try:
            component_data = hass.data.get(domain)
            if component_data is None:
                continue

            collection = None
            if hasattr(component_data, "storage_collection"):
                collection = component_data.storage_collection
            elif hasattr(component_data, "async_items"):
                collection = component_data
            elif isinstance(component_data, dict):
                collection = component_data.get("collection") or component_data.get("storage_collection")

            if collection is not None and hasattr(collection, "async_items"):
                items = collection.async_items()
                for item in items:
                    item_id = None
                    if isinstance(item, dict):
                        item_id = item.get("id")
                    elif hasattr(item, "id"):
                        item_id = item.id

                    if item_id == helper_id:
                        if isinstance(item, dict):
                            return domain, {
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "domain": domain,
                                **{k: v for k, v in item.items() if k not in ("id", "name")},
                            }
                        elif hasattr(item, "as_dict"):
                            item_dict = item.as_dict()
                            return domain, {
                                "id": item_dict.get("id"),
                                "name": item_dict.get("name"),
                                "domain": domain,
                                **{k: v for k, v in item_dict.items() if k not in ("id", "name")},
                            }
        except Exception as err:
            _LOGGER.warning("Error searching for helper in domain %s: %s", domain, err)
            continue

    return None, None


async def _create_helper(
    hass: HomeAssistant,
    domain: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Create a new helper.

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

    component_data = hass.data.get(domain)
    if component_data is None:
        raise ValueError(f"Helper domain {domain} is not loaded")

    collection = None
    if hasattr(component_data, "storage_collection"):
        collection = component_data.storage_collection
    elif hasattr(component_data, "async_create_item"):
        collection = component_data
    elif isinstance(component_data, dict):
        collection = component_data.get("collection") or component_data.get("storage_collection")

    if collection is None or not hasattr(collection, "async_create_item"):
        raise ValueError(f"Cannot create helpers for domain {domain}")

    # Create the helper
    created = await collection.async_create_item(config)

    if isinstance(created, dict):
        return {
            "id": created.get("id"),
            "name": created.get("name"),
            "domain": domain,
            **{k: v for k, v in created.items() if k not in ("id", "name")},
        }
    elif hasattr(created, "as_dict"):
        item_dict = created.as_dict()
        return {
            "id": item_dict.get("id"),
            "name": item_dict.get("name"),
            "domain": domain,
            **{k: v for k, v in item_dict.items() if k not in ("id", "name")},
        }
    else:
        return {"id": str(created), "domain": domain}


async def _update_helper(
    hass: HomeAssistant,
    domain: str,
    helper_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing helper.

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
    component_data = hass.data.get(domain)
    if component_data is None:
        raise ValueError(f"Helper domain {domain} is not loaded")

    collection = None
    if hasattr(component_data, "storage_collection"):
        collection = component_data.storage_collection
    elif hasattr(component_data, "async_update_item"):
        collection = component_data
    elif isinstance(component_data, dict):
        collection = component_data.get("collection") or component_data.get("storage_collection")

    if collection is None or not hasattr(collection, "async_update_item"):
        raise ValueError(f"Cannot update helpers for domain {domain}")

    # Update the helper
    updated = await collection.async_update_item(helper_id, updates)

    if isinstance(updated, dict):
        return {
            "id": updated.get("id"),
            "name": updated.get("name"),
            "domain": domain,
            **{k: v for k, v in updated.items() if k not in ("id", "name")},
        }
    elif hasattr(updated, "as_dict"):
        item_dict = updated.as_dict()
        return {
            "id": item_dict.get("id"),
            "name": item_dict.get("name"),
            "domain": domain,
            **{k: v for k, v in item_dict.items() if k not in ("id", "name")},
        }
    else:
        return {"id": helper_id, "domain": domain}


async def _delete_helper(
    hass: HomeAssistant,
    domain: str,
    helper_id: str,
) -> None:
    """Delete a helper.

    Args:
        hass: Home Assistant instance
        domain: The helper domain
        helper_id: The helper ID

    Raises:
        ValueError: If deletion fails
    """
    component_data = hass.data.get(domain)
    if component_data is None:
        raise ValueError(f"Helper domain {domain} is not loaded")

    collection = None
    if hasattr(component_data, "storage_collection"):
        collection = component_data.storage_collection
    elif hasattr(component_data, "async_delete_item"):
        collection = component_data
    elif isinstance(component_data, dict):
        collection = component_data.get("collection") or component_data.get("storage_collection")

    if collection is None or not hasattr(collection, "async_delete_item"):
        raise ValueError(f"Cannot delete helpers for domain {domain}")

    await collection.async_delete_item(helper_id)


class HelperListView(HomeAssistantView):
    """View to list all helpers and create new ones."""

    url = API_BASE_PATH_HELPERS
    name = "api:config_mcp:helpers"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all helpers.

        Query params:
            domain: Optional domain filter (e.g., 'input_boolean')

        Returns:
            200: JSON array of helper data
            400: Invalid domain filter
            403: Permission denied
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_HELPERS_READ):
            return self.json_message(
                "Helper read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Check for domain filter
        domain_filter = request.query.get("domain")

        if domain_filter is not None and domain_filter not in HELPER_DOMAINS:
            return self.json_message(
                f"Invalid domain '{domain_filter}'. Valid domains: {', '.join(HELPER_DOMAINS)}",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_DOMAIN,
            )

        try:
            if domain_filter:
                helpers = await _get_helpers_for_domain(hass, domain_filter)
            else:
                helpers = await _get_all_helpers(hass)
        except Exception as err:
            _LOGGER.exception("Error listing helpers: %s", err)
            return self.json_message(
                f"Error listing helpers: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        # Sort by name
        helpers.sort(key=lambda x: (x.get("name") or "").lower())
        return self.json(helpers)

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request - create new helper.

        Request body:
            {
                "domain": "input_boolean",  (required)
                "name": "My Helper",  (required)
                ... domain-specific fields ...
            }

        Domain-specific fields:
            input_boolean: icon (optional)
            input_number: min, max, step, mode, unit_of_measurement, icon (optional)
            input_text: min, max, pattern, mode, icon (optional)
            input_select: options (required), icon (optional)
            input_datetime: has_date, has_time, icon (optional)
            counter: initial, step, minimum, maximum, icon (optional)
            timer: duration, icon (optional)

        Returns:
            201: Helper created
            400: Invalid request or domain
            401: Not authorized
            403: Permission denied
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_HELPERS_CREATE):
            return self.json_message(
                "Helper create permission is disabled",
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

        # Validate required fields
        if "domain" not in body:
            return self.json_message(
                "Missing required field: domain",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )

        if "name" not in body:
            return self.json_message(
                "Missing required field: name",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )

        domain = body["domain"]
        if domain not in HELPER_DOMAINS:
            return self.json_message(
                f"Invalid domain '{domain}'. Valid domains: {', '.join(HELPER_DOMAINS)}",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_DOMAIN,
            )

        # Build config for helper creation (exclude 'domain' which is metadata)
        config = {k: v for k, v in body.items() if k != "domain"}

        try:
            created = await _create_helper(hass, domain, config)
        except ValueError as err:
            return self.json_message(
                str(err),
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )
        except Exception as err:
            _LOGGER.exception("Error creating helper: %s", err)
            return self.json_message(
                f"Error creating helper: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json(
            {
                **created,
                "message": "Helper created",
            },
            HTTPStatus.CREATED,
        )


class HelperDetailView(HomeAssistantView):
    """View for single helper operations."""

    url = API_BASE_PATH_HELPERS + "/{helper_id}"
    name = "api:config_mcp:helper"
    requires_auth = True

    async def get(
        self, request: web.Request, helper_id: str
    ) -> web.Response:
        """Handle GET request - get single helper.

        Path params:
            helper_id: The helper ID

        Returns:
            200: Helper data
            403: Permission denied
            404: Helper not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_HELPERS_READ):
            return self.json_message(
                "Helper read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        try:
            domain, helper = await _get_helper_by_id(hass, helper_id)
        except Exception as err:
            _LOGGER.exception("Error getting helper: %s", err)
            return self.json_message(
                f"Error getting helper: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        if helper is None:
            return self.json_message(
                f"Helper '{helper_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_HELPER_NOT_FOUND,
            )

        return self.json(helper)

    async def patch(
        self, request: web.Request, helper_id: str
    ) -> web.Response:
        """Handle PATCH request - update helper.

        Path params:
            helper_id: The helper ID

        Request body:
            {
                "name": "New Name",  (optional)
                ... domain-specific fields ...
            }

        Returns:
            200: Helper updated
            400: Invalid request
            401: Not authorized
            403: Permission denied
            404: Helper not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_HELPERS_UPDATE):
            return self.json_message(
                "Helper update permission is disabled",
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

        if not body:
            return self.json_message(
                "No updates provided",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        # Find the helper to get its domain
        try:
            domain, existing = await _get_helper_by_id(hass, helper_id)
        except Exception as err:
            _LOGGER.exception("Error finding helper: %s", err)
            return self.json_message(
                f"Error finding helper: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        if existing is None:
            return self.json_message(
                f"Helper '{helper_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_HELPER_NOT_FOUND,
            )

        # Remove domain from updates if present (can't change domain)
        updates = {k: v for k, v in body.items() if k != "domain"}

        try:
            updated = await _update_helper(hass, domain, helper_id, updates)
        except ValueError as err:
            return self.json_message(
                str(err),
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )
        except Exception as err:
            _LOGGER.exception("Error updating helper: %s", err)
            return self.json_message(
                f"Error updating helper: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            **updated,
            "message": "Helper updated",
        })

    async def delete(
        self, request: web.Request, helper_id: str
    ) -> web.Response:
        """Handle DELETE request - delete helper.

        Path params:
            helper_id: The helper ID

        Returns:
            204: Helper deleted
            401: Not authorized
            403: Permission denied
            404: Helper not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_HELPERS_DELETE):
            return self.json_message(
                "Helper delete permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        # Find the helper to get its domain
        try:
            domain, existing = await _get_helper_by_id(hass, helper_id)
        except Exception as err:
            _LOGGER.exception("Error finding helper: %s", err)
            return self.json_message(
                f"Error finding helper: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        if existing is None:
            return self.json_message(
                f"Helper '{helper_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_HELPER_NOT_FOUND,
            )

        try:
            await _delete_helper(hass, domain, helper_id)
        except ValueError as err:
            return self.json_message(
                str(err),
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )
        except Exception as err:
            _LOGGER.exception("Error deleting helper: %s", err)
            return self.json_message(
                f"Error deleting helper: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return web.Response(status=HTTPStatus.NO_CONTENT)
