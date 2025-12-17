"""Config flow for HA CRUD REST API."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_AUTOMATIONS_READ,
    CONF_AUTOMATIONS_WRITE,
    CONF_DASHBOARDS_READ,
    CONF_DASHBOARDS_WRITE,
    CONF_DISCOVERY_AREAS,
    CONF_DISCOVERY_DEVICES,
    CONF_DISCOVERY_ENTITIES,
    CONF_DISCOVERY_INTEGRATIONS,
    CONF_DISCOVERY_SERVICES,
    CONF_ENABLED_RESOURCES,
    CONF_SCENES_READ,
    CONF_SCENES_WRITE,
    CONF_SCRIPTS_READ,
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
    # If already in new format, return as-is
    if CONF_DISCOVERY_ENTITIES in options:
        return dict(options)

    # Check for legacy format
    if CONF_ENABLED_RESOURCES in options:
        enabled = options.get(CONF_ENABLED_RESOURCES, [])
        new_options = DEFAULT_OPTIONS.copy()

        # Map legacy resources to new format
        if RESOURCE_DASHBOARDS in enabled:
            new_options[CONF_DASHBOARDS_READ] = True
            new_options[CONF_DASHBOARDS_WRITE] = True

        return new_options

    # No options set, return defaults
    return DEFAULT_OPTIONS.copy()


class HaCrudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HA CRUD REST API."""

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
                title="HA CRUD REST API",
                data={},
                options=DEFAULT_OPTIONS.copy(),
            )

        # Simple confirmation step - configuration happens in options
        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "docs_url": "https://github.com/keith-gamble/ha-crud"
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return HaCrudOptionsFlow()


class HaCrudOptionsFlow(OptionsFlow):
    """Handle options flow for HA CRUD REST API."""

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
                "discovery",
                "dashboards",
                "automations",
                "scripts",
                "scenes",
                "save_and_exit",
            ],
        )

    async def async_step_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure discovery APIs."""
        if user_input is not None:
            # Update options and return to menu
            self._options.update(user_input)
            return await self.async_step_init()

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
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="dashboards",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DASHBOARDS_READ,
                        default=self._options.get(CONF_DASHBOARDS_READ, True),
                    ): bool,
                    vol.Required(
                        CONF_DASHBOARDS_WRITE,
                        default=self._options.get(CONF_DASHBOARDS_WRITE, True),
                    ): bool,
                }
            ),
        )

    async def async_step_automations(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure automations API."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="automations",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AUTOMATIONS_READ,
                        default=self._options.get(CONF_AUTOMATIONS_READ, False),
                    ): bool,
                    vol.Required(
                        CONF_AUTOMATIONS_WRITE,
                        default=self._options.get(CONF_AUTOMATIONS_WRITE, False),
                    ): bool,
                }
            ),
        )

    async def async_step_scripts(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure scripts API."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="scripts",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCRIPTS_READ,
                        default=self._options.get(CONF_SCRIPTS_READ, False),
                    ): bool,
                    vol.Required(
                        CONF_SCRIPTS_WRITE,
                        default=self._options.get(CONF_SCRIPTS_WRITE, False),
                    ): bool,
                }
            ),
        )

    async def async_step_scenes(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure scenes API."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="scenes",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCENES_READ,
                        default=self._options.get(CONF_SCENES_READ, False),
                    ): bool,
                    vol.Required(
                        CONF_SCENES_WRITE,
                        default=self._options.get(CONF_SCENES_WRITE, False),
                    ): bool,
                }
            ),
        )

    async def async_step_save_and_exit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Save options and exit."""
        return self.async_create_entry(title="", data=self._options)
