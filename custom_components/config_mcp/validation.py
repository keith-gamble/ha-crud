"""Schema validation for dashboard configurations."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
)


def validate_url_path(value: str) -> str:
    """Validate dashboard URL path.

    Home Assistant requires dashboard URL paths to:
    - Contain at least one hyphen
    - Use only lowercase alphanumeric characters and hyphens
    - Start and end with alphanumeric characters
    """
    if not value:
        raise vol.Invalid("URL path cannot be empty")

    # Must contain hyphen (Home Assistant convention)
    if "-" not in value:
        raise vol.Invalid("URL path must contain a hyphen (-)")

    # Validate characters (lowercase, numbers, hyphens)
    if not all(c.isalnum() or c == "-" for c in value):
        raise vol.Invalid(
            "URL path must contain only lowercase letters, numbers, and hyphens"
        )

    if not value[0].isalnum() or not value[-1].isalnum():
        raise vol.Invalid("URL path must start and end with alphanumeric character")

    return value.lower()


# Schema for creating a new dashboard
CREATE_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL_PATH): validate_url_path,
        vol.Required(CONF_TITLE): cv.string,
        vol.Optional(CONF_ICON, default="mdi:view-dashboard"): cv.icon,
        vol.Optional(CONF_SHOW_IN_SIDEBAR, default=True): cv.boolean,
        vol.Optional(CONF_REQUIRE_ADMIN, default=False): cv.boolean,
    }
)


# Schema for full update (PUT) - title required, others optional
UPDATE_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TITLE): cv.string,
        vol.Optional(CONF_ICON): vol.Any(cv.icon, None),
        vol.Optional(CONF_SHOW_IN_SIDEBAR, default=True): cv.boolean,
        vol.Optional(CONF_REQUIRE_ADMIN, default=False): cv.boolean,
    }
)


# Schema for partial update (PATCH) - all fields optional
PATCH_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TITLE): cv.string,
        vol.Optional(CONF_ICON): vol.Any(cv.icon, None),
        vol.Optional(CONF_SHOW_IN_SIDEBAR): cv.boolean,
        vol.Optional(CONF_REQUIRE_ADMIN): cv.boolean,
    }
)


# Schema for dashboard content/configuration (views, cards, etc.)
DASHBOARD_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional("views"): list,
        vol.Optional("title"): cv.string,
        vol.Optional("background"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)


def validate_create_data(data: dict) -> dict:
    """Validate data for creating a dashboard."""
    return CREATE_DASHBOARD_SCHEMA(data)


def validate_update_data(data: dict) -> dict:
    """Validate data for full update."""
    return UPDATE_DASHBOARD_SCHEMA(data)


def validate_patch_data(data: dict) -> dict:
    """Validate data for partial update."""
    return PATCH_DASHBOARD_SCHEMA(data)


def validate_dashboard_config(config: dict) -> dict:
    """Validate dashboard configuration content."""
    return DASHBOARD_CONFIG_SCHEMA(config)
