"""Constants for ha_crud component."""

DOMAIN = "ha_crud"

# Configuration keys - Discovery APIs (read-only)
CONF_DISCOVERY_ENTITIES = "discovery_entities"
CONF_DISCOVERY_DEVICES = "discovery_devices"
CONF_DISCOVERY_AREAS = "discovery_areas"  # Includes floors
CONF_DISCOVERY_INTEGRATIONS = "discovery_integrations"
CONF_DISCOVERY_SERVICES = "discovery_services"

# Configuration keys - CRUD APIs (read/write)
CONF_DASHBOARDS_READ = "dashboards_read"
CONF_DASHBOARDS_WRITE = "dashboards_write"
CONF_AUTOMATIONS_READ = "automations_read"
CONF_AUTOMATIONS_WRITE = "automations_write"
CONF_SCRIPTS_READ = "scripts_read"
CONF_SCRIPTS_WRITE = "scripts_write"
CONF_SCENES_READ = "scenes_read"
CONF_SCENES_WRITE = "scenes_write"

# Legacy config key (for migration)
CONF_ENABLED_RESOURCES = "enabled_resources"

# Resource types that can be exposed via the API (CRUD)
RESOURCE_DASHBOARDS = "dashboards"
RESOURCE_AUTOMATIONS = "automations"
RESOURCE_SCENES = "scenes"
RESOURCE_SCRIPTS = "scripts"
RESOURCE_HELPERS = "helpers"

# Resource types for discovery (read-only)
RESOURCE_ENTITIES = "entities"
RESOURCE_DEVICES = "devices"
RESOURCE_AREAS = "areas"
RESOURCE_INTEGRATIONS = "integrations"
RESOURCE_SERVICES = "services"

# All available resource types (for config flow)
AVAILABLE_RESOURCES = [
    RESOURCE_DASHBOARDS,
    RESOURCE_AUTOMATIONS,
    RESOURCE_SCENES,
    RESOURCE_SCRIPTS,
    RESOURCE_HELPERS,
]

# Discovery resources
DISCOVERY_RESOURCES = [
    RESOURCE_ENTITIES,
    RESOURCE_DEVICES,
    RESOURCE_AREAS,
    RESOURCE_INTEGRATIONS,
    RESOURCE_SERVICES,
]

# Default configuration
DEFAULT_OPTIONS = {
    # Discovery APIs - all enabled by default
    CONF_DISCOVERY_ENTITIES: True,
    CONF_DISCOVERY_DEVICES: True,
    CONF_DISCOVERY_AREAS: True,
    CONF_DISCOVERY_INTEGRATIONS: True,
    CONF_DISCOVERY_SERVICES: True,
    # CRUD APIs - dashboards enabled by default
    CONF_DASHBOARDS_READ: True,
    CONF_DASHBOARDS_WRITE: True,
    CONF_AUTOMATIONS_READ: False,
    CONF_AUTOMATIONS_WRITE: False,
    CONF_SCRIPTS_READ: False,
    CONF_SCRIPTS_WRITE: False,
    CONF_SCENES_READ: False,
    CONF_SCENES_WRITE: False,
}

# Legacy - kept for backwards compatibility
DEFAULT_RESOURCES = [RESOURCE_DASHBOARDS]

# API Base paths - using /api/ha_crud/ to avoid conflicts with HA built-in /api/config/
API_BASE_PATH_DASHBOARDS = "/api/ha_crud/dashboards"
API_BASE_PATH_AUTOMATIONS = "/api/ha_crud/automations"
API_BASE_PATH_SCENES = "/api/ha_crud/scenes"
API_BASE_PATH_SCRIPTS = "/api/ha_crud/scripts"
API_BASE_PATH_HELPERS = "/api/ha_crud/helpers"

# Discovery API paths (read-only)
API_BASE_PATH_ENTITIES = "/api/ha_crud/entities"
API_BASE_PATH_DEVICES = "/api/ha_crud/devices"
API_BASE_PATH_AREAS = "/api/ha_crud/areas"
API_BASE_PATH_FLOORS = "/api/ha_crud/floors"
API_BASE_PATH_INTEGRATIONS = "/api/ha_crud/integrations"
API_BASE_PATH_SERVICES = "/api/ha_crud/services"

# Lovelace data keys
LOVELACE_DATA = "lovelace"

# Dashboard modes
MODE_STORAGE = "storage"
MODE_YAML = "yaml"

# Configuration keys
CONF_URL_PATH = "url_path"
CONF_TITLE = "title"
CONF_ICON = "icon"
CONF_SHOW_IN_SIDEBAR = "show_in_sidebar"
CONF_REQUIRE_ADMIN = "require_admin"

# Error codes - Dashboards
ERR_DASHBOARD_NOT_FOUND = "dashboard_not_found"
ERR_DASHBOARD_EXISTS = "dashboard_already_exists"
ERR_INVALID_CONFIG = "invalid_config"
ERR_YAML_DASHBOARD = "yaml_dashboard_readonly"
ERR_DEFAULT_DASHBOARD = "default_dashboard_protected"

# Error codes - Discovery
ERR_ENTITY_NOT_FOUND = "entity_not_found"
ERR_DEVICE_NOT_FOUND = "device_not_found"
ERR_AREA_NOT_FOUND = "area_not_found"
ERR_FLOOR_NOT_FOUND = "floor_not_found"
ERR_DOMAIN_NOT_FOUND = "domain_not_found"

# Data keys for hass.data storage
DATA_DASHBOARDS_COLLECTION = f"{DOMAIN}_dashboards_collection"
