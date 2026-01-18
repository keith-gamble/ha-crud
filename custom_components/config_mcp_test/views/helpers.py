"""HTTP views for helper REST API."""

from __future__ import annotations

import logging
import uuid
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

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

# Storage version must match Home Assistant's internal version for these domains
STORAGE_VERSION = 1


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
