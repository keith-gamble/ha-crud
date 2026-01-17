"""HTTP views for dashboard REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import (
    API_BASE_PATH_DASHBOARDS,
    CONF_DASHBOARDS_CREATE,
    CONF_DASHBOARDS_DELETE,
    CONF_DASHBOARDS_READ,
    CONF_DASHBOARDS_UPDATE,
    CONF_DASHBOARDS_VALIDATE,
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
    DATA_DASHBOARDS_COLLECTION,
    DEFAULT_OPTIONS,
    DOMAIN,
    ERR_DASHBOARD_EXISTS,
    ERR_DASHBOARD_NOT_FOUND,
    ERR_INVALID_CONFIG,
    ERR_INVALID_ENTITIES,
    ERR_YAML_DASHBOARD,
    LOVELACE_DATA,
    MODE_STORAGE,
    MODE_YAML,
    VALIDATE_NONE,
    VALIDATE_STRICT,
    VALIDATE_WARN,
)
from ..validation import (
    validate_create_data,
    validate_dashboard_config,
    validate_dashboard_entities,
    validate_patch_data,
    validate_update_data,
)

if TYPE_CHECKING:
    from homeassistant.components.lovelace import LovelaceData

_LOGGER = logging.getLogger(__name__)


def get_config_options(hass: HomeAssistant) -> dict[str, Any]:
    """Get the current configuration options for config_mcp.

    Args:
        hass: Home Assistant instance

    Returns:
        Configuration options dict, merged with defaults
    """
    options = DEFAULT_OPTIONS.copy()

    # Get options from config entry
    if DOMAIN in hass.data:
        for entry_id, entry_data in hass.data[DOMAIN].items():
            # entry_data is the config entry data, we need the options
            # Find the config entry by entry_id
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.entry_id == entry_id:
                    options.update(entry.options)
                    break

    return options


def check_permission(hass: HomeAssistant, permission: str) -> bool:
    """Check if a specific permission is enabled.

    Args:
        hass: Home Assistant instance
        permission: The permission key to check

    Returns:
        True if permitted, False otherwise
    """
    options = get_config_options(hass)
    return options.get(permission, False)


def get_lovelace_data(hass: HomeAssistant):
    """Get lovelace data from hass.data."""
    return hass.data.get(LOVELACE_DATA)


def get_dashboards_collection(hass: HomeAssistant):
    """Get the dashboards collection for storage dashboards."""
    from ..const import DOMAIN

    # First try our component's stored collection
    collection = hass.data.get(DATA_DASHBOARDS_COLLECTION)
    if collection is not None:
        return collection

    # Log available keys for debugging
    lovelace_keys = [k for k in hass.data.keys() if "lovelace" in str(k).lower()]
    _LOGGER.debug("DashboardsCollection not found. Lovelace-related keys: %s", lovelace_keys)

    return None


async def _register_dashboard_with_lovelace(
    hass: HomeAssistant, url_path: str, data: dict[str, Any]
) -> None:
    """Register a newly created dashboard with lovelace and frontend.

    This makes the dashboard immediately visible without requiring a restart.
    """
    try:
        from homeassistant.components.lovelace.dashboard import LovelaceStorage
        from homeassistant.components.frontend import async_register_built_in_panel

        lovelace_data = get_lovelace_data(hass)
        if lovelace_data is None:
            _LOGGER.warning("Cannot register dashboard - lovelace data not available")
            return

        # Create LovelaceStorage instance for the new dashboard
        config = {
            "id": url_path,
            "url_path": url_path,
            "title": data.get(CONF_TITLE),
            "icon": data.get(CONF_ICON, "mdi:view-dashboard"),
            "show_in_sidebar": data.get(CONF_SHOW_IN_SIDEBAR, True),
            "require_admin": data.get(CONF_REQUIRE_ADMIN, False),
        }

        # Add to lovelace dashboards
        lovelace_data.dashboards[url_path] = LovelaceStorage(hass, config)

        # Register frontend panel using proper import
        async_register_built_in_panel(
            hass,
            "lovelace",
            config_panel_domain="lovelace",
            sidebar_title=data.get(CONF_TITLE),
            sidebar_icon=data.get(CONF_ICON, "mdi:view-dashboard"),
            frontend_url_path=url_path,
            config={"mode": "storage"},
            require_admin=data.get(CONF_REQUIRE_ADMIN, False),
        )

        _LOGGER.debug("Registered dashboard '%s' with lovelace and frontend", url_path)

    except Exception as err:
        _LOGGER.warning(
            "Could not register dashboard with frontend (may require restart): %s", err
        )


async def _unregister_dashboard_from_lovelace(
    hass: HomeAssistant, url_path: str
) -> None:
    """Unregister a dashboard from lovelace and frontend."""
    try:
        from homeassistant.components.frontend import async_remove_panel

        lovelace_data = get_lovelace_data(hass)
        if lovelace_data and url_path in lovelace_data.dashboards:
            del lovelace_data.dashboards[url_path]

        # Remove frontend panel
        async_remove_panel(hass, url_path)

        _LOGGER.debug("Unregistered dashboard '%s' from lovelace and frontend", url_path)

    except Exception as err:
        _LOGGER.warning(
            "Could not unregister dashboard from frontend (may require restart): %s", err
        )


async def _ensure_collection_loaded(hass: HomeAssistant):
    """Ensure the dashboards collection is loaded with latest data."""
    collection = hass.data.get(DATA_DASHBOARDS_COLLECTION)
    if collection is not None:
        await collection.async_load()
    return collection


def _url_path_to_item_id(url_path: str) -> str:
    """Convert url_path to collection item ID.

    Home Assistant sanitizes the ID by replacing hyphens with underscores.
    """
    return url_path.replace("-", "_")


def _find_item_id_by_url_path(collection, url_path: str) -> str | None:
    """Find the collection item ID for a given url_path.

    Returns the item ID if found, None otherwise.
    """
    for item_id, item in collection.data.items():
        if item.get("url_path") == url_path:
            return item_id
    # Fallback: try the sanitized version
    return _url_path_to_item_id(url_path)


class DashboardListView(HomeAssistantView):
    """View to list all dashboards and create new ones."""

    url = API_BASE_PATH_DASHBOARDS
    name = "api:config_mcp:dashboards"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all dashboards.

        Returns:
            200: JSON array of dashboard metadata
            403: Permission denied
        """
        hass: HomeAssistant = request.app["hass"]

        # Check read permission
        if not check_permission(hass, CONF_DASHBOARDS_READ):
            return self.json_message(
                "Dashboard read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        lovelace_data = get_lovelace_data(hass)

        if not lovelace_data:
            return self.json([])

        dashboards = []

        for url_path, config in lovelace_data.dashboards.items():
            try:
                info = await config.async_get_info()
                dashboard_data = {
                    "id": url_path if url_path else "lovelace",
                    "url_path": url_path,
                    "mode": info.get("mode", MODE_STORAGE),
                    "title": info.get("title"),
                    "icon": info.get("icon"),
                    "show_in_sidebar": info.get("show_in_sidebar", True),
                    "require_admin": info.get("require_admin", False),
                }
                dashboards.append(dashboard_data)
            except Exception as err:
                _LOGGER.warning(
                    "Error getting info for dashboard %s: %s",
                    url_path,
                    err,
                )
                continue

        return self.json(dashboards)

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request - create new dashboard.

        Request body:
            {
                "url_path": "my-dashboard",
                "title": "My Dashboard",
                "icon": "mdi:view-dashboard",
                "show_in_sidebar": true,
                "require_admin": false
            }

        Returns:
            201: Dashboard created successfully
            400: Invalid request data
            401: Not authorized (non-admin)
            403: Permission denied
            409: Dashboard already exists
        """
        hass: HomeAssistant = request.app["hass"]

        # Check create permission
        if not check_permission(hass, CONF_DASHBOARDS_CREATE):
            return self.json_message(
                "Dashboard create permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Check admin permission
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

        # Validate request data
        try:
            validated_data = validate_create_data(body)
        except vol.Invalid as err:
            return self.json_message(
                f"Invalid configuration: {err}",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        url_path = validated_data[CONF_URL_PATH]
        lovelace_data = get_lovelace_data(hass)
        dashboard_configs = lovelace_data.dashboards

        # Check if dashboard already exists
        if url_path in dashboard_configs:
            return self.json_message(
                f"Dashboard '{url_path}' already exists",
                HTTPStatus.CONFLICT,
                ERR_DASHBOARD_EXISTS,
            )

        # Check if URL path conflicts with existing panels
        if url_path in hass.data.get("frontend_panels", {}):
            return self.json_message(
                f"URL path '{url_path}' conflicts with existing panel",
                HTTPStatus.CONFLICT,
                ERR_DASHBOARD_EXISTS,
            )

        # Create the dashboard via the collection
        try:
            collection = get_dashboards_collection(hass)
            if collection is None:
                return self.json_message(
                    "Dashboard collection not available. Ensure lovelace is in storage mode.",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

            await collection.async_create_item(validated_data)

            # Also register the dashboard with lovelace and frontend for immediate visibility
            await _register_dashboard_with_lovelace(hass, url_path, validated_data)

            return self.json(
                {
                    "id": url_path,
                    "url_path": url_path,
                    "title": validated_data[CONF_TITLE],
                    "icon": validated_data.get(CONF_ICON, "mdi:view-dashboard"),
                    "show_in_sidebar": validated_data.get(CONF_SHOW_IN_SIDEBAR, True),
                    "require_admin": validated_data.get(CONF_REQUIRE_ADMIN, False),
                    "mode": MODE_STORAGE,
                },
                HTTPStatus.CREATED,
            )
        except Exception as err:
            _LOGGER.exception("Error creating dashboard: %s", err)
            return self.json_message(
                f"Error creating dashboard: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


class DashboardDetailView(HomeAssistantView):
    """View for single dashboard operations."""

    url = API_BASE_PATH_DASHBOARDS + "/{dashboard_id}"
    name = "api:config_mcp:dashboard"
    requires_auth = True

    async def get(
        self, request: web.Request, dashboard_id: str
    ) -> web.Response:
        """Handle GET request - get single dashboard metadata.

        Path params:
            dashboard_id: The dashboard URL path (or "lovelace" for default)

        Returns:
            200: Dashboard metadata
            403: Permission denied
            404: Dashboard not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Check read permission
        if not check_permission(hass, CONF_DASHBOARDS_READ):
            return self.json_message(
                "Dashboard read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        lovelace_data = get_lovelace_data(hass)

        if not lovelace_data:
            return self.json_message(
                f"Dashboard '{dashboard_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

        # Handle default dashboard
        url_path = None if dashboard_id == "lovelace" else dashboard_id
        dashboard_configs = lovelace_data.dashboards

        config = dashboard_configs.get(url_path)
        if config is None:
            return self.json_message(
                f"Dashboard '{dashboard_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

        try:
            info = await config.async_get_info()
        except Exception as err:
            _LOGGER.error("Error getting dashboard info: %s", err)
            return self.json_message(
                f"Error retrieving dashboard: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        result = {
            "id": dashboard_id,
            "url_path": url_path,
            "mode": info.get("mode", MODE_STORAGE),
            "title": info.get("title"),
            "icon": info.get("icon"),
            "show_in_sidebar": info.get("show_in_sidebar", True),
            "require_admin": info.get("require_admin", False),
        }

        return self.json(result)

    async def put(
        self, request: web.Request, dashboard_id: str
    ) -> web.Response:
        """Handle PUT request - full update of dashboard metadata.

        Path params:
            dashboard_id: The dashboard URL path

        Request body:
            {
                "title": "New Title",
                "icon": "mdi:new-icon",
                "show_in_sidebar": true,
                "require_admin": false
            }

        Returns:
            200: Dashboard updated
            400: Invalid request data
            401: Not authorized (non-admin)
            403: Permission denied
            404: Dashboard not found
            409: Cannot modify YAML dashboard
        """
        hass: HomeAssistant = request.app["hass"]

        # Check update permission
        if not check_permission(hass, CONF_DASHBOARDS_UPDATE):
            return self.json_message(
                "Dashboard update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Check admin permission
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        lovelace_data = get_lovelace_data(hass)
        url_path = None if dashboard_id == "lovelace" else dashboard_id
        dashboard_configs = lovelace_data.dashboards

        config = dashboard_configs.get(url_path)
        if config is None:
            return self.json_message(
                f"Dashboard '{dashboard_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

        # Check if YAML dashboard (read-only)
        info = await config.async_get_info()
        if info.get("mode") == MODE_YAML:
            return self.json_message(
                f"Dashboard '{dashboard_id}' is YAML-based and read-only",
                HTTPStatus.CONFLICT,
                ERR_YAML_DASHBOARD,
            )

        try:
            body = await request.json()
        except ValueError:
            return self.json_message(
                "Invalid JSON in request body",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        try:
            validated_data = validate_update_data(body)
        except vol.Invalid as err:
            return self.json_message(
                f"Invalid configuration: {err}",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        try:
            # Reload collection to ensure we have latest data
            collection = await _ensure_collection_loaded(hass)
            if collection is None:
                return self.json_message(
                    "Dashboard collection not available",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

            # Find the correct item ID (may differ from url_path due to sanitization)
            item_id = _find_item_id_by_url_path(collection, url_path)
            await collection.async_update_item(item_id, validated_data)

            return self.json({
                "id": dashboard_id,
                "url_path": url_path,
                "mode": MODE_STORAGE,
                **validated_data,
            })
        except Exception as err:
            _LOGGER.exception("Error updating dashboard: %s", err)
            return self.json_message(
                f"Error updating dashboard: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    async def patch(
        self, request: web.Request, dashboard_id: str
    ) -> web.Response:
        """Handle PATCH request - partial update of dashboard metadata.

        Path params:
            dashboard_id: The dashboard URL path

        Request body (all fields optional):
            {
                "title": "New Title",
                "icon": "mdi:new-icon",
                "show_in_sidebar": false,
                "require_admin": true
            }

        Returns:
            200: Dashboard updated
            400: Invalid request data
            401: Not authorized (non-admin)
            403: Permission denied
            404: Dashboard not found
            409: Cannot modify YAML dashboard
        """
        hass: HomeAssistant = request.app["hass"]

        # Check update permission
        if not check_permission(hass, CONF_DASHBOARDS_UPDATE):
            return self.json_message(
                "Dashboard update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Check admin permission
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        lovelace_data = get_lovelace_data(hass)
        url_path = None if dashboard_id == "lovelace" else dashboard_id
        dashboard_configs = lovelace_data.dashboards

        config = dashboard_configs.get(url_path)
        if config is None:
            return self.json_message(
                f"Dashboard '{dashboard_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

        # Check if YAML dashboard (read-only)
        info = await config.async_get_info()
        if info.get("mode") == MODE_YAML:
            return self.json_message(
                f"Dashboard '{dashboard_id}' is YAML-based and read-only",
                HTTPStatus.CONFLICT,
                ERR_YAML_DASHBOARD,
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
                "Request body cannot be empty",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        try:
            validated_data = validate_patch_data(body)
        except vol.Invalid as err:
            return self.json_message(
                f"Invalid configuration: {err}",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        try:
            # Reload collection to ensure we have latest data
            collection = await _ensure_collection_loaded(hass)
            if collection is None:
                return self.json_message(
                    "Dashboard collection not available",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

            # Find the correct item ID (may differ from url_path due to sanitization)
            item_id = _find_item_id_by_url_path(collection, url_path)

            # Get existing item data and merge with updates
            existing_item = collection.data.get(item_id, {})

            # Only include fields that are allowed in updates (not id, url_path, mode)
            allowed_fields = ["title", "icon", "show_in_sidebar", "require_admin"]
            merged_data = {}
            for field in allowed_fields:
                if field in validated_data:
                    merged_data[field] = validated_data[field]
                elif field in existing_item:
                    merged_data[field] = existing_item[field]

            _LOGGER.debug("PATCH: item_id=%s, merged_data=%s", item_id, merged_data)

            await collection.async_update_item(item_id, merged_data)

            # Return the merged data since lovelace object may not reflect changes immediately
            return self.json({
                "id": dashboard_id,
                "url_path": url_path,
                "mode": MODE_STORAGE,
                "title": merged_data.get("title"),
                "icon": merged_data.get("icon"),
                "show_in_sidebar": merged_data.get("show_in_sidebar", True),
                "require_admin": merged_data.get("require_admin", False),
            })
        except Exception as err:
            _LOGGER.exception("Error updating dashboard: %s", err)
            return self.json_message(
                f"Error updating dashboard: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    async def delete(
        self, request: web.Request, dashboard_id: str
    ) -> web.Response:
        """Handle DELETE request - delete a dashboard.

        Path params:
            dashboard_id: The dashboard URL path

        Returns:
            204: Dashboard deleted (no content)
            401: Not authorized (non-admin)
            403: Permission denied
            404: Dashboard not found
            409: Cannot delete YAML or default dashboard
        """
        hass: HomeAssistant = request.app["hass"]

        # Check delete permission
        if not check_permission(hass, CONF_DASHBOARDS_DELETE):
            return self.json_message(
                "Dashboard delete permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Check admin permission
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        # Cannot delete default dashboard
        if dashboard_id == "lovelace":
            return self.json_message(
                "Cannot delete the default dashboard",
                HTTPStatus.CONFLICT,
                "default_dashboard_protected",
            )

        lovelace_data = get_lovelace_data(hass)
        url_path = dashboard_id
        dashboard_configs = lovelace_data.dashboards

        config = dashboard_configs.get(url_path)
        if config is None:
            return self.json_message(
                f"Dashboard '{dashboard_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

        # Check if YAML dashboard (cannot delete via API)
        info = await config.async_get_info()
        if info.get("mode") == MODE_YAML:
            return self.json_message(
                f"Dashboard '{dashboard_id}' is YAML-based and cannot be deleted via API",
                HTTPStatus.CONFLICT,
                ERR_YAML_DASHBOARD,
            )

        try:
            # Reload collection to ensure we have latest data
            collection = await _ensure_collection_loaded(hass)
            if collection is None:
                return self.json_message(
                    "Dashboard collection not available",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

            # Find the correct item ID (may differ from url_path due to sanitization)
            item_id = _find_item_id_by_url_path(collection, url_path)
            await collection.async_delete_item(item_id)

            # Also unregister from lovelace and frontend for immediate effect
            await _unregister_dashboard_from_lovelace(hass, url_path)

            return web.Response(status=HTTPStatus.NO_CONTENT)
        except Exception as err:
            _LOGGER.exception("Error deleting dashboard: %s", err)
            return self.json_message(
                f"Error deleting dashboard: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


class DashboardConfigView(HomeAssistantView):
    """View for dashboard configuration (views/cards) operations."""

    url = API_BASE_PATH_DASHBOARDS + "/{dashboard_id}/config"
    name = "api:config_mcp:dashboard:config"
    requires_auth = True

    async def get(
        self, request: web.Request, dashboard_id: str
    ) -> web.Response:
        """Get the full configuration (views/cards) of a dashboard.

        Path params:
            dashboard_id: The dashboard URL path (or "lovelace" for default)

        Returns:
            200: Dashboard configuration (views, cards, etc.)
            403: Permission denied
            404: Dashboard or config not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Check read permission
        if not check_permission(hass, CONF_DASHBOARDS_READ):
            return self.json_message(
                "Dashboard read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        lovelace_data = get_lovelace_data(hass)

        if not lovelace_data:
            return self.json_message(
                f"Dashboard '{dashboard_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

        url_path = None if dashboard_id == "lovelace" else dashboard_id
        dashboard_configs = lovelace_data.dashboards

        config = dashboard_configs.get(url_path)
        if config is None:
            return self.json_message(
                f"Dashboard '{dashboard_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

        try:
            dashboard_config = await config.async_load(force=False)
            return self.json(dashboard_config)
        except Exception as err:
            # ConfigNotFound or other errors
            _LOGGER.warning("Error loading dashboard config: %s", err)
            return self.json_message(
                f"Configuration for dashboard '{dashboard_id}' not found or empty",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

    async def put(
        self, request: web.Request, dashboard_id: str
    ) -> web.Response:
        """Replace the full configuration of a dashboard.

        Path params:
            dashboard_id: The dashboard URL path (or "lovelace" for default)

        Request body:
            {
                "views": [...],
                "title": "Optional Dashboard Title"
            }

        Returns:
            200: Configuration saved
            400: Invalid configuration
            401: Not authorized (non-admin)
            403: Permission denied
            404: Dashboard not found
            409: YAML dashboard is read-only
        """
        hass: HomeAssistant = request.app["hass"]

        # Check update permission
        if not check_permission(hass, CONF_DASHBOARDS_UPDATE):
            return self.json_message(
                "Dashboard update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Check admin permission
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        lovelace_data = get_lovelace_data(hass)
        url_path = None if dashboard_id == "lovelace" else dashboard_id
        dashboard_configs = lovelace_data.dashboards

        dashboard = dashboard_configs.get(url_path)
        if dashboard is None:
            return self.json_message(
                f"Dashboard '{dashboard_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DASHBOARD_NOT_FOUND,
            )

        # Check if YAML dashboard (read-only)
        info = await dashboard.async_get_info()
        if info.get("mode") == MODE_YAML:
            return self.json_message(
                f"Dashboard '{dashboard_id}' is YAML-based and read-only",
                HTTPStatus.CONFLICT,
                ERR_YAML_DASHBOARD,
            )

        try:
            body = await request.json()
        except ValueError:
            return self.json_message(
                "Invalid JSON in request body",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        try:
            validated_config = validate_dashboard_config(body)
        except vol.Invalid as err:
            return self.json_message(
                f"Invalid configuration: {err}",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        # Get validation mode from config, allow query param override
        options = get_config_options(hass)
        default_validate_mode = options.get(CONF_DASHBOARDS_VALIDATE, VALIDATE_WARN)
        validate_mode = request.query.get("validate", default_validate_mode)

        # Validate entities if enabled
        missing_entities: list[str] = []
        if validate_mode != VALIDATE_NONE:
            missing_entities = validate_dashboard_entities(hass, validated_config)

            # In strict mode, reject if any entities are missing
            if validate_mode == VALIDATE_STRICT and missing_entities:
                return self.json_message(
                    f"Dashboard references {len(missing_entities)} missing entities: {', '.join(missing_entities[:5])}{'...' if len(missing_entities) > 5 else ''}",
                    HTTPStatus.BAD_REQUEST,
                    ERR_INVALID_ENTITIES,
                )

        try:
            await dashboard.async_save(validated_config)

            # Build response with optional warnings
            response_data = dict(validated_config)
            if validate_mode == VALIDATE_WARN and missing_entities:
                response_data["warnings"] = {
                    "missing_entities": missing_entities
                }

            return self.json(response_data)
        except Exception as err:
            _LOGGER.exception("Error saving dashboard config: %s", err)
            return self.json_message(
                f"Error saving configuration: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
