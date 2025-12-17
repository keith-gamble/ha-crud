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
    CONF_DASHBOARDS_READ,
    CONF_DASHBOARDS_WRITE,
    CONF_DISCOVERY_AREAS,
    CONF_DISCOVERY_DEVICES,
    CONF_DISCOVERY_ENTITIES,
    CONF_DISCOVERY_INTEGRATIONS,
    CONF_DISCOVERY_SERVICES,
    CONF_ENABLED_RESOURCES,
    DATA_DASHBOARDS_COLLECTION,
    DEFAULT_OPTIONS,
    DOMAIN,
    RESOURCE_AREAS,
    RESOURCE_DASHBOARDS,
    RESOURCE_DEVICES,
    RESOURCE_ENTITIES,
    RESOURCE_INTEGRATIONS,
    RESOURCE_SERVICES,
)
from .views import (
    AreaDetailView,
    AreaListView,
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
    FloorDetailView,
    FloorListView,
    IntegrationDetailView,
    IntegrationListView,
    ServiceDetailView,
    ServiceListView,
)

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
    _LOGGER.info("Migrating ha_crud config entry from version %s", config_entry.version)

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

    # If already in new format, return as-is
    if CONF_DISCOVERY_ENTITIES in options:
        return options

    # Check for legacy format
    if CONF_ENABLED_RESOURCES in options:
        enabled = options.get(CONF_ENABLED_RESOURCES, [])
        new_options = DEFAULT_OPTIONS.copy()

        # Map legacy resources to new format
        if RESOURCE_DASHBOARDS in enabled:
            new_options[CONF_DASHBOARDS_READ] = True
            new_options[CONF_DASHBOARDS_WRITE] = True

        _LOGGER.info("Migrated legacy options to new format")
        return new_options

    # No options set, return defaults
    return DEFAULT_OPTIONS.copy()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA CRUD REST API from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Get options (with migration support)
    options = _get_options(entry)

    _LOGGER.info("HA CRUD REST API setting up with options: %s", options)

    # Initialize DashboardsCollection if dashboards are enabled
    if options.get(CONF_DASHBOARDS_READ) or options.get(CONF_DASHBOARDS_WRITE):
        await _setup_dashboards_collection(hass)

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
        "HA CRUD REST API unloaded. Note: API endpoints remain active until HA restart."
    )

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    options = _get_options(entry)
    _LOGGER.info("HA CRUD REST API options updated: %s", options)

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

    # Dashboard views (if read or write enabled)
    dashboards_enabled = options.get(CONF_DASHBOARDS_READ) or options.get(CONF_DASHBOARDS_WRITE)
    if dashboards_enabled and RESOURCE_DASHBOARDS not in _REGISTERED_VIEWS:
        hass.http.register_view(DashboardListView())
        hass.http.register_view(DashboardDetailView())
        hass.http.register_view(DashboardConfigView())
        _REGISTERED_VIEWS.add(RESOURCE_DASHBOARDS)
        _LOGGER.info("Registered dashboard API endpoints at /api/ha_crud/dashboards")

    # Entity discovery views
    if options.get(CONF_DISCOVERY_ENTITIES) and RESOURCE_ENTITIES not in _REGISTERED_VIEWS:
        hass.http.register_view(EntityListView())
        hass.http.register_view(EntityDetailView())
        hass.http.register_view(DomainListView())
        hass.http.register_view(DomainEntitiesView())
        _REGISTERED_VIEWS.add(RESOURCE_ENTITIES)
        _LOGGER.info("Registered entity discovery API endpoints at /api/ha_crud/entities")

    # Device discovery views
    if options.get(CONF_DISCOVERY_DEVICES) and RESOURCE_DEVICES not in _REGISTERED_VIEWS:
        hass.http.register_view(DeviceListView())
        hass.http.register_view(DeviceDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_DEVICES)
        _LOGGER.info("Registered device discovery API endpoints at /api/ha_crud/devices")

    # Area/Floor discovery views
    if options.get(CONF_DISCOVERY_AREAS) and RESOURCE_AREAS not in _REGISTERED_VIEWS:
        hass.http.register_view(AreaListView())
        hass.http.register_view(AreaDetailView())
        hass.http.register_view(FloorListView())
        hass.http.register_view(FloorDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_AREAS)
        _LOGGER.info("Registered area/floor discovery API endpoints at /api/ha_crud/areas and /api/ha_crud/floors")

    # Integration discovery views
    if options.get(CONF_DISCOVERY_INTEGRATIONS) and RESOURCE_INTEGRATIONS not in _REGISTERED_VIEWS:
        hass.http.register_view(IntegrationListView())
        hass.http.register_view(IntegrationDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_INTEGRATIONS)
        _LOGGER.info("Registered integration discovery API endpoints at /api/ha_crud/integrations")

    # Service discovery views
    if options.get(CONF_DISCOVERY_SERVICES) and RESOURCE_SERVICES not in _REGISTERED_VIEWS:
        hass.http.register_view(ServiceListView())
        hass.http.register_view(DomainServiceListView())
        hass.http.register_view(ServiceDetailView())
        _REGISTERED_VIEWS.add(RESOURCE_SERVICES)
        _LOGGER.info("Registered service discovery API endpoints at /api/ha_crud/services")

    # Future resource views will be added here:
    # Automations, Scripts, Scenes, etc.
