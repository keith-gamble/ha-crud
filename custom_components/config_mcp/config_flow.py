"""Config flow for Configuration MCP Server."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_AUTOMATIONS_CREATE,
    CONF_AUTOMATIONS_DELETE,
    CONF_AUTOMATIONS_READ,
    CONF_AUTOMATIONS_UPDATE,
    CONF_AUTOMATIONS_WRITE,
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
    CONF_LOGS_READ,
    CONF_MCP_OAUTH_ENABLED,
    CONF_MCP_SERVER,
    CONF_SCENES_CREATE,
    CONF_SCENES_DELETE,
    CONF_SCENES_READ,
    CONF_SCENES_UPDATE,
    CONF_SCENES_WRITE,
    CONF_SCRIPTS_CREATE,
    CONF_SCRIPTS_DELETE,
    CONF_SCRIPTS_READ,
    CONF_SCRIPTS_UPDATE,
    CONF_SCRIPTS_WRITE,
    DEFAULT_OPTIONS,
    DOMAIN,
    RESOURCE_DASHBOARDS,
)


def _migrate_legacy_options(options: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy options format to new granular format.

    Args:
        options: Current options dict (may be legacy or new format)

    Returns:
        Options in the new granular format
    """
    # Start with defaults
    new_options = DEFAULT_OPTIONS.copy()

    # If already in new granular format (has create/update/delete keys), merge
    if CONF_DASHBOARDS_CREATE in options:
        new_options.update(options)
        return new_options

    # Check for intermediate format (has read/write but not granular)
    if CONF_DASHBOARDS_WRITE in options:
        # Migrate from read/write to granular permissions
        new_options.update(options)
        # Convert write permission to granular
        if options.get(CONF_DASHBOARDS_WRITE, False):
            new_options[CONF_DASHBOARDS_CREATE] = True
            new_options[CONF_DASHBOARDS_UPDATE] = True
            new_options[CONF_DASHBOARDS_DELETE] = True
        return new_options

    # Check for very old legacy format
    if CONF_ENABLED_RESOURCES in options:
        enabled = options.get(CONF_ENABLED_RESOURCES, [])
        # Map legacy resources to new format
        if RESOURCE_DASHBOARDS in enabled:
            new_options[CONF_DASHBOARDS_READ] = True
            new_options[CONF_DASHBOARDS_CREATE] = True
            new_options[CONF_DASHBOARDS_UPDATE] = True
            new_options[CONF_DASHBOARDS_DELETE] = True
        return new_options

    # If has discovery options, merge them
    if CONF_DISCOVERY_ENTITIES in options:
        new_options.update(options)
        return new_options

    # No options set, return defaults
    return new_options


class HaCrudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Configuration MCP Server."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        # Only allow a single instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Configuration MCP Server",
                data={},
                options=DEFAULT_OPTIONS.copy(),
            )

        # Simple confirmation step - configuration happens in options
        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "docs_url": "https://github.com/keith-gamble/config-mcp"
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return HaCrudOptionsFlow()


class HaCrudOptionsFlow(OptionsFlow):
    """Handle options flow for Configuration MCP Server."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._options: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the main menu."""
        # Initialize options from config entry on first load
        if not self._options:
            self._options = _migrate_legacy_options(dict(self.config_entry.options))

        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "mcp_server",
                "discovery",
                "dashboards",
                "automations",
                "scripts",
                "scenes",
            ],
        )

    async def async_step_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure discovery APIs."""
        # Initialize options if not already done
        if not self._options:
            self._options = _migrate_legacy_options(dict(self.config_entry.options))

        if user_input is not None:
            # Update options and save immediately
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="discovery",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DISCOVERY_ENTITIES,
                        default=self._options.get(CONF_DISCOVERY_ENTITIES, True),
                    ): bool,
                    vol.Required(
                        CONF_DISCOVERY_DEVICES,
                        default=self._options.get(CONF_DISCOVERY_DEVICES, True),
                    ): bool,
                    vol.Required(
                        CONF_DISCOVERY_AREAS,
                        default=self._options.get(CONF_DISCOVERY_AREAS, True),
                    ): bool,
                    vol.Required(
                        CONF_DISCOVERY_INTEGRATIONS,
                        default=self._options.get(CONF_DISCOVERY_INTEGRATIONS, True),
                    ): bool,
                    vol.Required(
                        CONF_DISCOVERY_SERVICES,
                        default=self._options.get(CONF_DISCOVERY_SERVICES, True),
                    ): bool,
                }
            ),
        )

    async def async_step_dashboards(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure dashboard API."""
        # Initialize options if not already done
        if not self._options:
            self._options = _migrate_legacy_options(dict(self.config_entry.options))

        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="dashboards",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DASHBOARDS_READ,
                        default=self._options.get(CONF_DASHBOARDS_READ, True),
                    ): bool,
                    vol.Required(
                        CONF_DASHBOARDS_CREATE,
                        default=self._options.get(CONF_DASHBOARDS_CREATE, False),
                    ): bool,
                    vol.Required(
                        CONF_DASHBOARDS_UPDATE,
                        default=self._options.get(CONF_DASHBOARDS_UPDATE, True),
                    ): bool,
                    vol.Required(
                        CONF_DASHBOARDS_DELETE,
                        default=self._options.get(CONF_DASHBOARDS_DELETE, False),
                    ): bool,
                }
            ),
        )

    async def async_step_mcp_server(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure MCP server."""
        from homeassistant.helpers import issue_registry as ir

        from .oauth import is_oidc_available

        # Initialize options if not already done
        if not self._options:
            self._options = _migrate_legacy_options(dict(self.config_entry.options))

        if user_input is not None:
            self._options.update(user_input)

            # Check if OAuth was just enabled - create repair if so
            old_oauth = self.config_entry.options.get(CONF_MCP_OAUTH_ENABLED, False)
            new_oauth = user_input.get(CONF_MCP_OAUTH_ENABLED, False)

            if new_oauth and not old_oauth:
                # OAuth was just enabled - create repair notification
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    "oauth_restart_required",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="oauth_restart_required",
                )
            elif not new_oauth and old_oauth:
                # OAuth was disabled - remove repair if it exists
                ir.async_delete_issue(self.hass, DOMAIN, "oauth_restart_required")

            return self.async_create_entry(title="", data=self._options)

        # Check if OIDC is available
        oidc_available = is_oidc_available(self.hass)

        # Build schema - OAuth option only shown if OIDC is available
        schema_dict: dict[Any, Any] = {
            vol.Required(
                CONF_MCP_SERVER,
                default=self._options.get(CONF_MCP_SERVER, True),
            ): bool,
        }

        if oidc_available:
            schema_dict[vol.Required(
                CONF_MCP_OAUTH_ENABLED,
                default=self._options.get(CONF_MCP_OAUTH_ENABLED, False),
            )] = bool

        # Log reading is always available as an option
        schema_dict[vol.Required(
            CONF_LOGS_READ,
            default=self._options.get(CONF_LOGS_READ, False),
        )] = bool

        return self.async_show_form(
            step_id="mcp_server",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "oidc_status": "Available" if oidc_available else "Not installed",
            },
        )

    async def async_step_automations(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure automations API."""
        # Initialize options if not already done
        if not self._options:
            self._options = _migrate_legacy_options(dict(self.config_entry.options))

        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="automations",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AUTOMATIONS_READ,
                        default=self._options.get(CONF_AUTOMATIONS_READ, False),
                    ): bool,
                    vol.Required(
                        CONF_AUTOMATIONS_CREATE,
                        default=self._options.get(CONF_AUTOMATIONS_CREATE, False),
                    ): bool,
                    vol.Required(
                        CONF_AUTOMATIONS_UPDATE,
                        default=self._options.get(CONF_AUTOMATIONS_UPDATE, False),
                    ): bool,
                    vol.Required(
                        CONF_AUTOMATIONS_DELETE,
                        default=self._options.get(CONF_AUTOMATIONS_DELETE, False),
                    ): bool,
                }
            ),
        )

    async def async_step_scripts(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure scripts API."""
        # Initialize options if not already done
        if not self._options:
            self._options = _migrate_legacy_options(dict(self.config_entry.options))

        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="scripts",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCRIPTS_READ,
                        default=self._options.get(CONF_SCRIPTS_READ, False),
                    ): bool,
                    vol.Required(
                        CONF_SCRIPTS_CREATE,
                        default=self._options.get(CONF_SCRIPTS_CREATE, False),
                    ): bool,
                    vol.Required(
                        CONF_SCRIPTS_UPDATE,
                        default=self._options.get(CONF_SCRIPTS_UPDATE, False),
                    ): bool,
                    vol.Required(
                        CONF_SCRIPTS_DELETE,
                        default=self._options.get(CONF_SCRIPTS_DELETE, False),
                    ): bool,
                }
            ),
        )

    async def async_step_scenes(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure scenes API."""
        # Initialize options if not already done
        if not self._options:
            self._options = _migrate_legacy_options(dict(self.config_entry.options))

        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="scenes",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCENES_READ,
                        default=self._options.get(CONF_SCENES_READ, False),
                    ): bool,
                    vol.Required(
                        CONF_SCENES_CREATE,
                        default=self._options.get(CONF_SCENES_CREATE, False),
                    ): bool,
                    vol.Required(
                        CONF_SCENES_UPDATE,
                        default=self._options.get(CONF_SCENES_UPDATE, False),
                    ): bool,
                    vol.Required(
                        CONF_SCENES_DELETE,
                        default=self._options.get(CONF_SCENES_DELETE, False),
                    ): bool,
                }
            ),
        )
