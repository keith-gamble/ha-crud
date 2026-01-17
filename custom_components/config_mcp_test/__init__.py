"""Home Assistant CRUD REST API component.

This component exposes REST endpoints for managing Home Assistant
resources like Lovelace dashboards, automations, scenes, and more.

Endpoints are registered based on the resources enabled in the config.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AUTOMATIONS_CREATE,
    CONF_AUTOMATIONS_DELETE,
    CONF_AUTOMATIONS_READ,
    CONF_AUTOMATIONS_UPDATE,
    CONF_CATEGORIES_CREATE,
    CONF_CATEGORIES_DELETE,
    CONF_CATEGORIES_READ,
    CONF_CATEGORIES_UPDATE,
    CONF_DASHBOARDS_CREATE,
    CONF_DASHBOARDS_DELETE,
    CONF_DASHBOARDS_READ,
    CONF_DASHBOARDS_UPDATE,
    CONF_DASHBOARDS_WRITE,
    CONF_DISCOVERY_AREAS,
    CONF_DISCOVERY_DEVICES,
    CONF_DISCOVERY_ENTITIES,
    CONF_DISCOVERY_INTEGRATIONS,
    CONF_DISCOVERY_SERVICES,
    CONF_ENABLED_RESOURCES,
    CONF_HELPERS_CREATE,
    CONF_HELPERS_DELETE,
    CONF_HELPERS_READ,
    CONF_HELPERS_UPDATE,
    CONF_LABELS_CREATE,
    CONF_LABELS_DELETE,
    CONF_LABELS_READ,
    CONF_LABELS_UPDATE,
    CONF_LOGS_READ,
    CONF_MCP_OAUTH_ENABLED,
    CONF_MCP_SERVER,
    CONF_SCENES_CREATE,
    CONF_SCENES_DELETE,
    CONF_SCENES_READ,
    CONF_SCENES_UPDATE,
    CONF_SCRIPTS_CREATE,
    CONF_SCRIPTS_DELETE,
    CONF_SCRIPTS_READ,
    CONF_SCRIPTS_UPDATE,
    DATA_DASHBOARDS_COLLECTION,
    DEFAULT_OPTIONS,
    DOMAIN,
    RESOURCE_AREAS,
    RESOURCE_AUTOMATIONS,
    RESOURCE_CATEGORIES,
    RESOURCE_DASHBOARDS,
    RESOURCE_DEVICES,
    RESOURCE_ENTITIES,
    RESOURCE_HELPERS,
    RESOURCE_INTEGRATIONS,
    RESOURCE_LABELS,
    RESOURCE_LOGS,
    RESOURCE_SCENES,
    RESOURCE_SCRIPTS,
    RESOURCE_SERVICES,
)
from .views import (
    AreaDetailView,
    AreaListView,
    AutomationDetailView,
    AutomationListView,
    AutomationTriggerView,
    CategoryDetailView,
    CategoryScopeListView,
    DashboardConfigView,
    DashboardDetailView,
    DashboardListView,
    DeviceDetailView,
    DeviceListView,
    DomainEntitiesView,
    DomainListView,
    DomainServiceListView,
    EntityDetailView,
    EntityListView,
    EntityUsageView,
    FloorDetailView,
    FloorListView,
    HelperDetailView,
    HelperListView,
    IntegrationDetailView,
    IntegrationListView,
    LabelDetailView,
    LabelListView,
    LogErrorsView,
    LogListView,
    ResourceListView,
    SceneActivateView,
    SceneDetailView,
    SceneListView,
    ScriptDetailView,
    ScriptListView,
    ScriptRunView,
    ScriptStopView,
    ServiceDetailView,
    ServiceListView,
)
from .mcp_http import MCPOAuthMetadataView, MCPStreamableView

_LOGGER = logging.getLogger(__name__)

# Track registered views to avoid duplicate registration
_REGISTERED_VIEWS: set[str] = set()


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry to new version.

    Args:
        hass: Home Assistant instance
        config_entry: Config entry to migrate

    Returns:
        True if migration was successful
    """
    _LOGGER.info("Migrating config_mcp config entry from version %s", config_entry.version)

    if config_entry.version == 1:
        # Migrate from version 1 (legacy format) to version 2 (granular options)
        old_options = dict(config_entry.options)
        new_options = DEFAULT_OPTIONS.copy()

        # Check for legacy format
        if CONF_ENABLED_RESOURCES in old_options:
            enabled = old_options.get(CONF_ENABLED_RESOURCES, [])
            if RESOURCE_DASHBOARDS in enabled:
                new_options[CONF_DASHBOARDS_READ] = True
                new_options[CONF_DASHBOARDS_WRITE] = True

        hass.config_entries.async_update_entry(
            config_entry,
            options=new_options,
            version=2,
        )
        _LOGGER.info("Migration to version 2 successful")

    return True


def _get_options(entry: ConfigEntry) -> dict[str, Any]:
    """Get options with migration from legacy format.

    Args:
        entry: Config entry

    Returns:
        Options dict in the new granular format
    """
    options = dict(entry.options)

    # Start with defaults, then override with stored options
    merged = DEFAULT_OPTIONS.copy()

    # If already in new granular format (has create/update/delete keys), merge
    if CONF_DASHBOARDS_CREATE in options:
        merged.update(options)
        return merged

    # Check for intermediate format (has read/write but not granular)
    if CONF_DASHBOARDS_WRITE in options:
        # Migrate from read/write to granular permissions
        merged.update(options)
        # Convert write permission to granular
        if options.get(CONF_DASHBOARDS_WRITE, False):
            merged[CONF_DASHBOARDS_CREATE] = True
            merged[CONF_DASHBOARDS_UPDATE] = True
            merged[CONF_DASHBOARDS_DELETE] = True
        _LOGGER.info("Migrated read/write options to granular format")
        return merged

    # Check for very old legacy format
    if CONF_ENABLED_RESOURCES in options:
        enabled = options.get(CONF_ENABLED_RESOURCES, [])
        # Map legacy resources to new format
        if RESOURCE_DASHBOARDS in enabled:
            merged[CONF_DASHBOARDS_READ] = True
            merged[CONF_DASHBOARDS_CREATE] = True
            merged[CONF_DASHBOARDS_UPDATE] = True
            merged[CONF_DASHBOARDS_DELETE] = True
        _LOGGER.info("Migrated legacy options to new format")
        return merged

    # If has discovery options, merge them
    if CONF_DISCOVERY_ENTITIES in options:
        merged.update(options)
        return merged

    # No options set, return defaults
    return merged


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Configuration MCP Server from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Get options (with migration support)
    options = _get_options(entry)

    _LOGGER.info("Configuration MCP Server setting up with options: %s", options)

    # Initialize DashboardsCollection if any dashboard permission is enabled
    dashboards_enabled = (
        options.get(CONF_DASHBOARDS_READ) or
        options.get(CONF_DASHBOARDS_CREATE) or
        options.get(CONF_DASHBOARDS_UPDATE) or
        options.get(CONF_DASHBOARDS_DELETE)
    )
    if dashboards_enabled:
        await _setup_dashboards_collection(hass)

    # Pre-register MCP tools in executor to avoid blocking event loop
    # This must happen before _register_views so tools are ready when MCP server starts
    if options.get(CONF_MCP_SERVER):
        from .tools import register_all_tools
        tool_count = await hass.async_add_executor_job(register_all_tools)
        _LOGGER.info("Pre-registered %d MCP tools at startup", tool_count)

    # Register views for enabled resources
    _register_views(hass, options)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def _setup_dashboards_collection(hass: HomeAssistant) -> None:
    """Set up the dashboards collection for CRUD operations."""
    # Import here to avoid circular imports and ensure lovelace is loaded
    try:
        from homeassistant.components.lovelace.dashboard import DashboardsCollection
    except ImportError:
        _LOGGER.error("Could not import DashboardsCollection from lovelace")
        return

    # Create and load the collection (shares storage with lovelace component)
    collection = DashboardsCollection(hass)
    await collection.async_load()
    hass.data[DATA_DASHBOARDS_COLLECTION] = collection
    _LOGGER.debug("DashboardsCollection initialized with %d items", len(collection.data))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        del hass.data[DOMAIN][entry.entry_id]

    # Note: HTTP views cannot be unregistered in HA, they persist until restart
    _LOGGER.info(
        "Configuration MCP Server unloaded. Note: API endpoints remain active until HA restart."
    )

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    options = _get_options(entry)
    _LOGGER.info("Configuration MCP Server options updated: %s", options)

    # Register any newly enabled views
    _register_views(hass, options)

    # Note: We can't unregister views, so disabled resources remain until restart
    _LOGGER.info(
        "Note: Disabled resources will stop being available after HA restart."
    )


def _register_views(hass: HomeAssistant, options: dict[str, Any]) -> None:
    """Register HTTP views for enabled resources.

    Args:
        hass: Home Assistant instance
        options: Configuration options dict
    """
    global _REGISTERED_VIEWS

    # Dashboard views (if any dashboard permission is enabled)
    dashboards_enabled = (
        options.get(CONF_DASHBOARDS_READ) or
        options.get(CONF_DASHBOARDS_CREATE) or
        options.get(CONF_DASHBOARDS_UPDATE) or
        options.get(CONF_DASHBOARDS_DELETE)
    )
    if dashboards_enabled and RESOURCE_DASHBOARDS not in _REGISTERED_VIEWS:
        hass.http.register_view(DashboardListView())
        hass.http.register_view(DashboardDetailView())
        hass.http.register_view(DashboardConfigView())
        hass.http.register_view(ResourceListView())
        _REGISTERED_VIEWS.add(RESOURCE_DASHBOARDS)
        _LOGGER.info("Registered dashboard API endpoints at /api/config_mcp/dashboards")
        _LOGGER.info("Registered resources API endpoint at /api/config_mcp/resources")

    # Entity discovery views
    if options.get(CONF_DISCOVERY_ENTITIES) and RESOURCE_ENTITIES not in _REGISTERED_VIEWS:
        hass.http.register_view(EntityListView())
        hass.http.register_view(EntityDetailView())
        hass.http.register_view(DomainListView())
        hass.http.register_view(DomainEntitiesView())
        hass.http.register_view(EntityUsageView())
        _REGISTERED_VIEWS.add(RESOURCE_ENTITIES)
        _LOGGER.info("Registered entity discovery API endpoints at /api/config_mcp/entities")

    # Device discovery views
    if options.get(CONF_DISCOVERY_DEVICES) and RESOURCE_DEVICES not in _REGISTERED_VIEWS:
        hass.http.register_view(DeviceListView())
        hass.http.register_view(DeviceDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_DEVICES)
        _LOGGER.info("Registered device discovery API endpoints at /api/config_mcp/devices")

    # Area/Floor discovery views
    if options.get(CONF_DISCOVERY_AREAS) and RESOURCE_AREAS not in _REGISTERED_VIEWS:
        hass.http.register_view(AreaListView())
        hass.http.register_view(AreaDetailView())
        hass.http.register_view(FloorListView())
        hass.http.register_view(FloorDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_AREAS)
        _LOGGER.info("Registered area/floor discovery API endpoints at /api/config_mcp/areas and /api/config_mcp/floors")

    # Integration discovery views
    if options.get(CONF_DISCOVERY_INTEGRATIONS) and RESOURCE_INTEGRATIONS not in _REGISTERED_VIEWS:
        hass.http.register_view(IntegrationListView())
        hass.http.register_view(IntegrationDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_INTEGRATIONS)
        _LOGGER.info("Registered integration discovery API endpoints at /api/config_mcp/integrations")

    # Service discovery views
    if options.get(CONF_DISCOVERY_SERVICES) and RESOURCE_SERVICES not in _REGISTERED_VIEWS:
        hass.http.register_view(ServiceListView())
        hass.http.register_view(DomainServiceListView())
        hass.http.register_view(ServiceDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_SERVICES)
        _LOGGER.info("Registered service discovery API endpoints at /api/config_mcp/services")

    # MCP Server
    if options.get(CONF_MCP_SERVER) and "mcp_server" not in _REGISTERED_VIEWS:
        oauth_enabled = options.get(CONF_MCP_OAUTH_ENABLED, False)
        hass.http.register_view(MCPStreamableView(hass, oauth_enabled=oauth_enabled))
        _REGISTERED_VIEWS.add("mcp_server")
        _LOGGER.info("Registered MCP server endpoint at /api/config_mcp/mcp")

        # Register OAuth metadata view if OAuth is enabled
        if oauth_enabled and "mcp_oauth_metadata" not in _REGISTERED_VIEWS:
            # We need to override HA's default OAuth metadata endpoint
            # HA's default returns relative URLs without issuer, breaking OAuth clients
            oauth_view = MCPOAuthMetadataView(hass)

            # Try to override by replacing the handler in the router
            app = hass.http.app
            override_success = False
            if app is not None:
                try:
                    from aiohttp import web

                    router = app.router

                    # Find and replace the existing well-known route handler
                    for resource in list(router.resources()):
                        info = resource.get_info()
                        if info.get("path") == "/.well-known/oauth-authorization-server":
                            _LOGGER.info("Found existing OAuth metadata route, attempting override...")

                            # Clear existing routes on this resource and add our handler
                            # Access internal _routes dict
                            if hasattr(resource, '_routes'):
                                # Replace GET handler
                                for method, route in list(resource._routes.items()):
                                    if method == "GET":
                                        # Create new handler that returns proper metadata
                                        async def oauth_handler(request):
                                            return await oauth_view.get(request)

                                        # Replace the handler
                                        route._handler = oauth_handler
                                        override_success = True
                                        _LOGGER.info("Successfully replaced OAuth metadata handler")
                                        break
                            break

                except Exception as err:
                    _LOGGER.warning("Could not override OAuth metadata handler: %s", err)

            if not override_success:
                # Fall back - register our view at the subpath and log warning
                hass.http.register_view(oauth_view)
                _LOGGER.warning(
                    "Could not override default OAuth metadata at /.well-known/oauth-authorization-server. "
                    "MCP OAuth authentication may not work. The OIDC metadata is available at "
                    "/.well-known/oauth-authorization-server/oidc instead."
                )

            _REGISTERED_VIEWS.add("mcp_oauth_metadata")

            # Clear the restart required repair since OAuth is now active
            from homeassistant.helpers import issue_registry as ir
            ir.async_delete_issue(hass, DOMAIN, "oauth_restart_required")

    # Automation views (if any automation permission is enabled)
    automations_enabled = (
        options.get(CONF_AUTOMATIONS_READ) or
        options.get(CONF_AUTOMATIONS_CREATE) or
        options.get(CONF_AUTOMATIONS_UPDATE) or
        options.get(CONF_AUTOMATIONS_DELETE)
    )
    if automations_enabled and RESOURCE_AUTOMATIONS not in _REGISTERED_VIEWS:
        hass.http.register_view(AutomationListView())
        hass.http.register_view(AutomationDetailView())
        hass.http.register_view(AutomationTriggerView())
        _REGISTERED_VIEWS.add(RESOURCE_AUTOMATIONS)
        _LOGGER.info("Registered automation API endpoints at /api/config_mcp/automations")

    # Script views (if any script permission is enabled)
    scripts_enabled = (
        options.get(CONF_SCRIPTS_READ) or
        options.get(CONF_SCRIPTS_CREATE) or
        options.get(CONF_SCRIPTS_UPDATE) or
        options.get(CONF_SCRIPTS_DELETE)
    )
    if scripts_enabled and RESOURCE_SCRIPTS not in _REGISTERED_VIEWS:
        hass.http.register_view(ScriptListView())
        hass.http.register_view(ScriptDetailView())
        hass.http.register_view(ScriptRunView())
        hass.http.register_view(ScriptStopView())
        _REGISTERED_VIEWS.add(RESOURCE_SCRIPTS)
        _LOGGER.info("Registered script API endpoints at /api/config_mcp/scripts")

    # Scene views (if any scene permission is enabled)
    scenes_enabled = (
        options.get(CONF_SCENES_READ) or
        options.get(CONF_SCENES_CREATE) or
        options.get(CONF_SCENES_UPDATE) or
        options.get(CONF_SCENES_DELETE)
    )
    if scenes_enabled and RESOURCE_SCENES not in _REGISTERED_VIEWS:
        hass.http.register_view(SceneListView())
        hass.http.register_view(SceneDetailView())
        hass.http.register_view(SceneActivateView())
        _REGISTERED_VIEWS.add(RESOURCE_SCENES)
        _LOGGER.info("Registered scene API endpoints at /api/config_mcp/scenes")

    # Log views (if log reading is enabled)
    if options.get(CONF_LOGS_READ) and RESOURCE_LOGS not in _REGISTERED_VIEWS:
        hass.http.register_view(LogListView())
        hass.http.register_view(LogErrorsView())
        _REGISTERED_VIEWS.add(RESOURCE_LOGS)
        _LOGGER.info("Registered log API endpoints at /api/config_mcp/logs")

    # Category views (if any category permission is enabled)
    categories_enabled = (
        options.get(CONF_CATEGORIES_READ) or
        options.get(CONF_CATEGORIES_CREATE) or
        options.get(CONF_CATEGORIES_UPDATE) or
        options.get(CONF_CATEGORIES_DELETE)
    )
    if categories_enabled and RESOURCE_CATEGORIES not in _REGISTERED_VIEWS:
        hass.http.register_view(CategoryScopeListView())
        hass.http.register_view(CategoryDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_CATEGORIES)
        _LOGGER.info("Registered category API endpoints at /api/config_mcp/categories")

    # Label views (if any label permission is enabled)
    labels_enabled = (
        options.get(CONF_LABELS_READ) or
        options.get(CONF_LABELS_CREATE) or
        options.get(CONF_LABELS_UPDATE) or
        options.get(CONF_LABELS_DELETE)
    )
    if labels_enabled and RESOURCE_LABELS not in _REGISTERED_VIEWS:
        hass.http.register_view(LabelListView())
        hass.http.register_view(LabelDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_LABELS)
        _LOGGER.info("Registered label API endpoints at /api/config_mcp/labels")

    # Helper views (if any helper permission is enabled)
    helpers_enabled = (
        options.get(CONF_HELPERS_READ) or
        options.get(CONF_HELPERS_CREATE) or
        options.get(CONF_HELPERS_UPDATE) or
        options.get(CONF_HELPERS_DELETE)
    )
    if helpers_enabled and RESOURCE_HELPERS not in _REGISTERED_VIEWS:
        hass.http.register_view(HelperListView())
        hass.http.register_view(HelperDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_HELPERS)
        _LOGGER.info("Registered helper API endpoints at /api/config_mcp/helpers")
