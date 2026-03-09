"""HTTP views for helper REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from homeassistant.helpers import entity_registry as er

from ..const import (
    API_BASE_PATH_HELPERS,
    API_BASE_PATH_TEMPLATE_HELPERS,
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

# Storage version for reading helpers via Store API (list/get operations)
STORAGE_VERSION = 1

# Key used by HA's collection.store_entity_registry_items() to store
# StorageCollection instances in hass.data
COLLECTION_INSTANCES_KEY = "collection_instances"


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


def _get_storage_collection(hass: HomeAssistant, domain: str) -> Any:
    """Get Home Assistant's internal StorageCollection for a helper domain.

    This accesses the same collection that HA's WebSocket commands
    ({domain}/create, {domain}/update, {domain}/delete) use, ensuring
    in-memory state and disk storage stay in sync.
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


# Template sub-types available for creation
TEMPLATE_TYPES = [
    "alarm_control_panel", "binary_sensor", "button", "cover",
    "event", "fan", "image", "light", "lock", "number",
    "select", "sensor", "switch", "update", "vacuum", "weather",
]


class TemplateHelperListView(HomeAssistantView):
    """View to list and create template-based helpers."""

    url = API_BASE_PATH_TEMPLATE_HELPERS
    name = "api:config_mcp:template_helpers"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all template helpers.

        Query params:
            template_type: Optional filter (e.g., 'sensor', 'binary_sensor')

        Returns:
            200: JSON array of template helper data
            403: Permission denied
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_HELPERS_READ):
            return self.json_message(
                "Helper read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        type_filter = request.query.get("template_type")
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
        return self.json(results)

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request - create a template helper.

        Request body:
            {
                "template_type": "sensor",  (required)
                "name": "My Sensor",  (required)
                "state": "{{ states('sensor.x') }}",  (required)
                "unit_of_measurement": "°C",  (optional)
                "device_class": "temperature",  (optional, omit if not set)
                "state_class": "measurement",  (optional, omit if not set)
                "availability": "{{ true }}",  (optional)
            }

        Returns:
            201: Template helper created
            400: Invalid request
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

        template_type = body.get("template_type")
        name = body.get("name")
        state = body.get("state")

        if not template_type:
            return self.json_message(
                "Missing required field: template_type",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )

        if not name:
            return self.json_message(
                "Missing required field: name",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )

        if not state:
            return self.json_message(
                "Missing required field: state",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )

        try:
            # Step 1: Initiate config entry flow
            result = await hass.config_entries.flow.async_init(
                "template", context={"source": "user"}
            )
            flow_id = result["flow_id"]

            # Step 2: Select template sub-type
            result = await hass.config_entries.flow.async_configure(
                flow_id, {"next_step_id": template_type}
            )

            # Step 3: Submit configuration
            config_data: dict[str, Any] = {"name": name, "state": state}
            for field in ("unit_of_measurement", "device_class", "state_class",
                          "availability", "device_id"):
                if field in body and body[field]:
                    config_data[field] = body[field]

            result = await hass.config_entries.flow.async_configure(
                flow_id, config_data
            )
        except Exception as err:
            _LOGGER.exception("Error creating template helper: %s", err)
            return self.json_message(
                f"Error creating template helper: {err}",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )

        if result.get("type") != "create_entry":
            return self.json_message(
                f"Unexpected flow result: {result.get('type')}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        entry_result = result.get("result", {})
        entry_id = (
            entry_result.entry_id
            if hasattr(entry_result, "entry_id")
            else entry_result.get("entry_id")
        )

        return self.json(
            {
                "entry_id": entry_id,
                "title": result.get("title", name),
                "domain": "template",
                "template_type": template_type,
                "options": result.get("options", config_data),
                "message": "Template helper created",
            },
            HTTPStatus.CREATED,
        )


class TemplateHelperDetailView(HomeAssistantView):
    """View for single template helper operations."""

    url = API_BASE_PATH_TEMPLATE_HELPERS + "/{entry_id}"
    name = "api:config_mcp:template_helper"
    requires_auth = True

    async def get(
        self, request: web.Request, entry_id: str
    ) -> web.Response:
        """Handle GET request - get a single template helper.

        Returns:
            200: Template helper data with entities
            403: Permission denied
            404: Not found
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_HELPERS_READ):
            return self.json_message(
                "Helper read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != "template":
            return self.json_message(
                f"Template helper '{entry_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_HELPER_NOT_FOUND,
            )

        result: dict[str, Any] = {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "domain": "template",
            "template_type": entry.options.get("template_type", ""),
            "state": entry.state.value if hasattr(entry.state, "value") else str(entry.state),
            "supports_options": entry.supports_options,
            "options": dict(entry.options),
        }

        # Include associated entities with current state
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
                }
                state = hass.states.get(entity_entry.entity_id)
                if state:
                    entity_data["current_state"] = {
                        "state": state.state,
                        "attributes": dict(state.attributes),
                    }
                entity_entries.append(entity_data)
            result["entities"] = entity_entries

        return self.json(result)

    async def patch(
        self, request: web.Request, entry_id: str
    ) -> web.Response:
        """Handle PATCH request - update a template helper via options flow.

        Returns:
            200: Template helper updated
            400: Invalid request
            401: Not authorized
            403: Permission denied
            404: Not found
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

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != "template":
            return self.json_message(
                f"Template helper '{entry_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_HELPER_NOT_FOUND,
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

        try:
            result = await hass.config_entries.options.async_init(entry_id)
            flow_id = result["flow_id"]

            # Merge current options with updates
            current_options = dict(entry.options)
            update_data: dict[str, Any] = {}
            for field in ("name", "state", "unit_of_measurement", "device_class",
                          "state_class", "availability"):
                if field in body:
                    if body[field]:
                        update_data[field] = body[field]
                elif field in current_options:
                    update_data[field] = current_options[field]

            result = await hass.config_entries.options.async_configure(
                flow_id, update_data
            )
        except Exception as err:
            _LOGGER.exception("Error updating template helper: %s", err)
            return self.json_message(
                f"Error updating template helper: {err}",
                HTTPStatus.BAD_REQUEST,
                ERR_HELPER_INVALID_CONFIG,
            )

        return self.json({
            "entry_id": entry_id,
            "title": entry.title,
            "domain": "template",
            "options": update_data,
            "message": "Template helper updated",
        })

    async def delete(
        self, request: web.Request, entry_id: str
    ) -> web.Response:
        """Handle DELETE request - delete a template helper.

        Returns:
            204: Template helper deleted
            401: Not authorized
            403: Permission denied
            404: Not found
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

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != "template":
            return self.json_message(
                f"Template helper '{entry_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_HELPER_NOT_FOUND,
            )

        try:
            await hass.config_entries.async_remove(entry_id)
        except Exception as err:
            _LOGGER.exception("Error deleting template helper: %s", err)
            return self.json_message(
                f"Error deleting template helper: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return web.Response(status=HTTPStatus.NO_CONTENT)
