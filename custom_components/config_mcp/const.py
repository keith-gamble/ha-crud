"""Constants for Configuration MCP Server component."""

DOMAIN = "config_mcp"

# Configuration keys - Discovery APIs (read-only)
CONF_DISCOVERY_ENTITIES = "discovery_entities"
CONF_DISCOVERY_DEVICES = "discovery_devices"
CONF_DISCOVERY_AREAS = "discovery_areas"
CONF_DISCOVERY_INTEGRATIONS = "discovery_integrations"
CONF_DISCOVERY_SERVICES = "discovery_services"

# Configuration keys - CRUD APIs (granular permissions)
# Dashboards
CONF_DASHBOARDS_READ = "dashboards_read"
CONF_DASHBOARDS_CREATE = "dashboards_create"
CONF_DASHBOARDS_UPDATE = "dashboards_update"
CONF_DASHBOARDS_DELETE = "dashboards_delete"
CONF_DASHBOARDS_VALIDATE = "dashboards_validate"

# Dashboard validation modes
VALIDATE_NONE = "none"
VALIDATE_WARN = "warn"
VALIDATE_STRICT = "strict"

# Automations
CONF_AUTOMATIONS_READ = "automations_read"
CONF_AUTOMATIONS_CREATE = "automations_create"
CONF_AUTOMATIONS_UPDATE = "automations_update"
CONF_AUTOMATIONS_DELETE = "automations_delete"

# Scripts
CONF_SCRIPTS_READ = "scripts_read"
CONF_SCRIPTS_CREATE = "scripts_create"
CONF_SCRIPTS_UPDATE = "scripts_update"
CONF_SCRIPTS_DELETE = "scripts_delete"

# Scenes
CONF_SCENES_READ = "scenes_read"
CONF_SCENES_CREATE = "scenes_create"
CONF_SCENES_UPDATE = "scenes_update"
CONF_SCENES_DELETE = "scenes_delete"

# Helpers (input_boolean, input_number, input_text, input_select, input_datetime, counter, timer)
CONF_HELPERS_READ = "helpers_read"
CONF_HELPERS_CREATE = "helpers_create"
CONF_HELPERS_UPDATE = "helpers_update"
CONF_HELPERS_DELETE = "helpers_delete"

# Logs (MCP only - for debugging/verification)
CONF_LOGS_READ = "logs_read"

# Categories (for organizing automations, scripts, etc.)
CONF_CATEGORIES_READ = "categories_read"
CONF_CATEGORIES_CREATE = "categories_create"
CONF_CATEGORIES_UPDATE = "categories_update"
CONF_CATEGORIES_DELETE = "categories_delete"

# Labels (for tagging entities, automations, scripts, etc.)
CONF_LABELS_READ = "labels_read"
CONF_LABELS_CREATE = "labels_create"
CONF_LABELS_UPDATE = "labels_update"
CONF_LABELS_DELETE = "labels_delete"

# Deprecated keys for migration from older versions
CONF_DASHBOARDS_WRITE = "dashboards_write"
CONF_AUTOMATIONS_WRITE = "automations_write"
CONF_SCRIPTS_WRITE = "scripts_write"
CONF_SCENES_WRITE = "scenes_write"
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
RESOURCE_LOGS = "logs"

# Resource types for organization
RESOURCE_CATEGORIES = "categories"
RESOURCE_LABELS = "labels"

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

# Helper domains (input_* helpers and utility helpers)
HELPER_DOMAINS = [
    "input_boolean",
    "input_number",
    "input_text",
    "input_select",
    "input_datetime",
    "counter",
    "timer",
]

# MCP Server configuration key
CONF_MCP_SERVER = "mcp_server"
CONF_MCP_OAUTH_ENABLED = "mcp_oauth_enabled"

# OIDC Provider domain (optional dependency)
OIDC_DOMAIN = "oidc_provider"

# OAuth metadata endpoint path
OAUTH_METADATA_PATH = "/.well-known/oauth-authorization-server"

# Default configuration
DEFAULT_OPTIONS = {
    # Discovery APIs - all enabled by default
    CONF_DISCOVERY_ENTITIES: True,
    CONF_DISCOVERY_DEVICES: True,
    CONF_DISCOVERY_AREAS: True,
    CONF_DISCOVERY_INTEGRATIONS: True,
    CONF_DISCOVERY_SERVICES: True,
    # Dashboard APIs - read/update enabled, create/delete disabled by default
    CONF_DASHBOARDS_READ: True,
    CONF_DASHBOARDS_CREATE: False,
    CONF_DASHBOARDS_UPDATE: True,
    CONF_DASHBOARDS_DELETE: False,
    CONF_DASHBOARDS_VALIDATE: VALIDATE_WARN,
    # Automations - disabled by default for safety
    CONF_AUTOMATIONS_READ: False,
    CONF_AUTOMATIONS_CREATE: False,
    CONF_AUTOMATIONS_UPDATE: False,
    CONF_AUTOMATIONS_DELETE: False,
    # Scripts - all disabled by default
    CONF_SCRIPTS_READ: False,
    CONF_SCRIPTS_CREATE: False,
    CONF_SCRIPTS_UPDATE: False,
    CONF_SCRIPTS_DELETE: False,
    # Scenes - all disabled by default
    CONF_SCENES_READ: False,
    CONF_SCENES_CREATE: False,
    CONF_SCENES_UPDATE: False,
    CONF_SCENES_DELETE: False,
    # Helpers - all disabled by default
    CONF_HELPERS_READ: False,
    CONF_HELPERS_CREATE: False,
    CONF_HELPERS_UPDATE: False,
    CONF_HELPERS_DELETE: False,
    # Logs - disabled by default for security
    CONF_LOGS_READ: False,
    # Categories - read enabled, write disabled by default
    CONF_CATEGORIES_READ: True,
    CONF_CATEGORIES_CREATE: False,
    CONF_CATEGORIES_UPDATE: False,
    CONF_CATEGORIES_DELETE: False,
    # Labels - read enabled, write disabled by default
    CONF_LABELS_READ: True,
    CONF_LABELS_CREATE: False,
    CONF_LABELS_UPDATE: False,
    CONF_LABELS_DELETE: False,
    # MCP Server - enabled by default
    CONF_MCP_SERVER: True,
    # MCP OAuth - disabled by default (requires hass-oidc-auth)
    CONF_MCP_OAUTH_ENABLED: False,
}

# Deprecated - kept for migration
DEFAULT_RESOURCES = [RESOURCE_DASHBOARDS]

# API Base paths
API_BASE_PATH_DASHBOARDS = "/api/config_mcp/dashboards"
API_BASE_PATH_AUTOMATIONS = "/api/config_mcp/automations"
API_BASE_PATH_SCENES = "/api/config_mcp/scenes"
API_BASE_PATH_SCRIPTS = "/api/config_mcp/scripts"
API_BASE_PATH_HELPERS = "/api/config_mcp/helpers"

# Discovery API paths (read-only)
API_BASE_PATH_ENTITIES = "/api/config_mcp/entities"
API_BASE_PATH_DEVICES = "/api/config_mcp/devices"
API_BASE_PATH_AREAS = "/api/config_mcp/areas"
API_BASE_PATH_FLOORS = "/api/config_mcp/floors"
API_BASE_PATH_INTEGRATIONS = "/api/config_mcp/integrations"
API_BASE_PATH_SERVICES = "/api/config_mcp/services"
API_BASE_PATH_RESOURCES = "/api/config_mcp/resources"
API_BASE_PATH_LOGS = "/api/config_mcp/logs"

# Organization API paths
API_BASE_PATH_CATEGORIES = "/api/config_mcp/categories"
API_BASE_PATH_LABELS = "/api/config_mcp/labels"

# Valid category scopes (from Home Assistant's CategoryRegistry)
CATEGORY_SCOPES = ["automation", "script", "helper"]

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
ERR_INVALID_ENTITIES = "invalid_entities"

# Error codes - Discovery
ERR_ENTITY_NOT_FOUND = "entity_not_found"
ERR_DEVICE_NOT_FOUND = "device_not_found"
ERR_AREA_NOT_FOUND = "area_not_found"
ERR_FLOOR_NOT_FOUND = "floor_not_found"
ERR_DOMAIN_NOT_FOUND = "domain_not_found"

# Error codes - Automations
ERR_AUTOMATION_NOT_FOUND = "automation_not_found"
ERR_AUTOMATION_EXISTS = "automation_already_exists"
ERR_AUTOMATION_INVALID_CONFIG = "automation_invalid_config"

# Error codes - Scripts
ERR_SCRIPT_NOT_FOUND = "script_not_found"
ERR_SCRIPT_EXISTS = "script_already_exists"
ERR_SCRIPT_INVALID_CONFIG = "script_invalid_config"

# Error codes - Scenes
ERR_SCENE_NOT_FOUND = "scene_not_found"
ERR_SCENE_EXISTS = "scene_already_exists"
ERR_SCENE_INVALID_CONFIG = "scene_invalid_config"

# Error codes - Helpers
ERR_HELPER_NOT_FOUND = "helper_not_found"
ERR_HELPER_EXISTS = "helper_already_exists"
ERR_HELPER_INVALID_CONFIG = "helper_invalid_config"
ERR_HELPER_INVALID_DOMAIN = "helper_invalid_domain"

# Error codes - Logs
ERR_LOG_NOT_FOUND = "log_not_found"
ERR_LOG_INVALID_PARAMS = "log_invalid_params"

# Error codes - Categories
ERR_CATEGORY_NOT_FOUND = "category_not_found"
ERR_CATEGORY_EXISTS = "category_already_exists"
ERR_CATEGORY_INVALID_SCOPE = "category_invalid_scope"

# Error codes - Labels
ERR_LABEL_NOT_FOUND = "label_not_found"
ERR_LABEL_EXISTS = "label_already_exists"

# Data keys for hass.data storage
DATA_DASHBOARDS_COLLECTION = f"{DOMAIN}_dashboards_collection"
DATA_AUTOMATIONS_COMPONENT = f"{DOMAIN}_automations_component"

# MCP Server configuration
API_BASE_PATH_MCP = "/api/config_mcp/mcp"
MCP_SERVER_NAME = "config-mcp"
MCP_SERVER_VERSION = "1.2.1"
