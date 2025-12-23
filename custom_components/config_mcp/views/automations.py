"""HTTP views for automation REST API."""

from __future__ import annotations

import logging
import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from ..const import (
    API_BASE_PATH_AUTOMATIONS,
    CONF_AUTOMATIONS_CREATE,
    CONF_AUTOMATIONS_DELETE,
    CONF_AUTOMATIONS_READ,
    CONF_AUTOMATIONS_UPDATE,
    DEFAULT_OPTIONS,
    DOMAIN,
    ERR_AUTOMATION_EXISTS,
    ERR_AUTOMATION_INVALID_CONFIG,
    ERR_AUTOMATION_NOT_FOUND,
    ERR_INVALID_CONFIG,
)

if TYPE_CHECKING:
    from homeassistant.components.automation import AutomationEntity

_LOGGER = logging.getLogger(__name__)

# Domain for the automation component
AUTOMATION_DOMAIN = "automation"
AUTOMATION_DATA_COMPONENT = "automation"


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


def get_available_services(hass: HomeAssistant) -> dict[str, set[str]]:
    """Get all available services grouped by domain.

    Returns:
        Dict mapping domain to set of service names
    """
    services = {}
    for domain, domain_services in hass.services.async_services().items():
        services[domain] = set(domain_services.keys())
    return services


def validate_actions(hass: HomeAssistant, actions: list[dict]) -> list[str]:
    """Validate that all actions reference valid services.

    Args:
        hass: Home Assistant instance
        actions: List of action dicts from automation/script

    Returns:
        List of error messages for invalid actions (empty if all valid)
    """
    if not actions:
        return []

    available_services = get_available_services(hass)
    errors = []

    for idx, action in enumerate(actions):
        # Get the action/service name
        action_name = action.get("action") or action.get("service")

        if not action_name:
            # Skip actions without an action/service field (could be delay, condition, etc.)
            continue

        # Parse domain.service format
        if "." in action_name:
            domain, service = action_name.split(".", 1)
        else:
            errors.append(f"Action {idx + 1}: '{action_name}' is not in domain.service format")
            continue

        # Check if domain exists
        if domain not in available_services:
            errors.append(
                f"Action {idx + 1}: Unknown domain '{domain}' in '{action_name}'. "
                f"Available domains include: {', '.join(sorted(list(available_services.keys())[:10]))}..."
            )
            continue

        # Check if service exists in domain
        if service not in available_services[domain]:
            available = ", ".join(sorted(available_services[domain]))
            errors.append(
                f"Action {idx + 1}: Unknown service '{service}' in domain '{domain}'. "
                f"Available services: {available}"
            )

    return errors


def get_automation_component(hass: HomeAssistant):
    """Get the automation component from hass.data."""
    return hass.data.get(AUTOMATION_DATA_COMPONENT)


def _get_automation_entity(hass: HomeAssistant, entity_id: str):
    """Get an automation entity by ID.

    Args:
        hass: Home Assistant instance
        entity_id: The automation entity ID (automation.xxx)

    Returns:
        The automation entity or None if not found
    """
    component = get_automation_component(hass)
    if component is None:
        return None
    return component.get_entity(entity_id)


def _format_automation(entity, hass: HomeAssistant = None, include_config: bool = False) -> dict[str, Any]:
    """Format an automation entity for API response.

    Args:
        entity: The automation entity
        hass: Home Assistant instance (optional, needed for category/label info)
        include_config: Whether to include the full config

    Returns:
        Dict with automation data
    """
    result = {
        "id": entity.unique_id,
        "entity_id": entity.entity_id,
        "name": entity.name,
        "state": entity.state,  # "on" or "off"
        "enabled": entity.state == "on",
        "last_triggered": entity.extra_state_attributes.get("last_triggered"),
        "mode": entity.extra_state_attributes.get("mode", "single"),
        "current": entity.extra_state_attributes.get("current", 0),
    }

    # Include category and labels from entity registry if hass is provided
    if hass is not None:
        try:
            entity_registry = er.async_get(hass)
            registry_entry = entity_registry.async_get(entity.entity_id)
            if registry_entry:
                # Categories are stored per-scope in entity registry
                result["categories"] = dict(registry_entry.categories) if registry_entry.categories else {}
                result["labels"] = list(registry_entry.labels) if registry_entry.labels else []
        except Exception:
            # If registry lookup fails, just skip category/label info
            result["categories"] = {}
            result["labels"] = []

    if include_config:
        # Include the raw config if requested
        if hasattr(entity, "raw_config") and entity.raw_config:
            result["config"] = entity.raw_config

    return result


async def _load_automation_config(hass: HomeAssistant) -> list[dict]:
    """Load automations from automations.yaml.

    Returns a list of automation config dicts from config/automations.yaml
    """
    import yaml
    from pathlib import Path

    automation_path = Path(hass.config.path("automations.yaml"))

    if not automation_path.exists():
        return []

    def read_yaml():
        try:
            with open(automation_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if data else []
        except Exception as err:
            _LOGGER.error("Error reading automations.yaml: %s", err)
            return []

    return await hass.async_add_executor_job(read_yaml)


async def _save_automation_config(hass: HomeAssistant, automations: list[dict]) -> None:
    """Save automations to automations.yaml."""
    import yaml
    from pathlib import Path

    automation_path = Path(hass.config.path("automations.yaml"))

    def write_yaml():
        try:
            with open(automation_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(automations, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as err:
            _LOGGER.error("Error writing automations.yaml: %s", err)
            raise

    await hass.async_add_executor_job(write_yaml)


async def _reload_automations(hass: HomeAssistant) -> None:
    """Reload automations to apply changes."""
    await hass.services.async_call(
        AUTOMATION_DOMAIN,
        "reload",
        blocking=True,
    )


async def _cleanup_entity_registry(hass: HomeAssistant, entity_id: str) -> None:
    """Remove an entity from the entity registry.

    This prevents orphaned entity registry entries after deletion.
    """
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        entry = registry.async_get(entity_id)

        if entry is not None:
            registry.async_remove(entity_id)
            _LOGGER.debug("Removed entity registry entry for %s", entity_id)
    except Exception as err:
        # Log but don't fail - entity registry cleanup is best-effort
        _LOGGER.warning("Could not clean up entity registry for %s: %s", entity_id, err)


class AutomationListView(HomeAssistantView):
    """View to list all automations and create new ones."""

    url = API_BASE_PATH_AUTOMATIONS
    name = "api:config_mcp:automations"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all automations.

        Returns:
            200: JSON array of automation metadata
            403: Permission denied
        """
        hass: HomeAssistant = request.app["hass"]

        # Check read permission
        if not check_permission(hass, CONF_AUTOMATIONS_READ):
            return self.json_message(
                "Automation read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        component = get_automation_component(hass)

        if component is None:
            return self.json([])

        automations = []
        for entity in component.entities:
            try:
                automations.append(_format_automation(entity, hass=hass, include_config=False))
            except Exception as err:
                _LOGGER.warning(
                    "Error getting info for automation %s: %s",
                    entity.entity_id,
                    err,
                )
                continue

        return self.json(automations)

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request - create new automation.

        Request body:
            {
                "alias": "My Automation",
                "description": "Optional description",
                "mode": "single",
                "triggers": [...],
                "conditions": [...],
                "actions": [...]
            }

        Returns:
            201: Automation created successfully
            400: Invalid request data
            401: Not authorized (non-admin)
            403: Permission denied
            409: Automation already exists
        """
        hass: HomeAssistant = request.app["hass"]

        # Check create permission
        if not check_permission(hass, CONF_AUTOMATIONS_CREATE):
            return self.json_message(
                "Automation create permission is disabled",
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

        # Validate required fields
        if "alias" not in body:
            return self.json_message(
                "Missing required field: alias",
                HTTPStatus.BAD_REQUEST,
                ERR_AUTOMATION_INVALID_CONFIG,
            )

        # Generate a unique ID if not provided
        automation_id = body.get("id", uuid.uuid4().hex)

        # Load existing automations
        automations = await _load_automation_config(hass)

        # Check if ID already exists
        for automation in automations:
            if automation.get("id") == automation_id:
                return self.json_message(
                    f"Automation with id '{automation_id}' already exists",
                    HTTPStatus.CONFLICT,
                    ERR_AUTOMATION_EXISTS,
                )

        # Build the automation config
        new_automation = {
            "id": automation_id,
            "alias": body.get("alias"),
        }

        # Add optional fields
        if "description" in body:
            new_automation["description"] = body["description"]
        if "mode" in body:
            new_automation["mode"] = body["mode"]
        if "max" in body:
            new_automation["max"] = body["max"]
        if "max_exceeded" in body:
            new_automation["max_exceeded"] = body["max_exceeded"]
        if "variables" in body:
            new_automation["variables"] = body["variables"]
        if "trigger_variables" in body:
            new_automation["trigger_variables"] = body["trigger_variables"]

        # Add triggers (can be "trigger" or "triggers")
        triggers = body.get("triggers") or body.get("trigger") or []
        new_automation["triggers"] = triggers

        # Add conditions (can be "condition" or "conditions")
        conditions = body.get("conditions") or body.get("condition") or []
        new_automation["conditions"] = conditions

        # Add actions (can be "action" or "actions")
        actions = body.get("actions") or body.get("action") or []
        new_automation["actions"] = actions

        # Validate actions before saving
        action_errors = validate_actions(hass, actions)
        if action_errors:
            return self.json_message(
                "Invalid actions in automation:\n" + "\n".join(action_errors),
                HTTPStatus.BAD_REQUEST,
                ERR_AUTOMATION_INVALID_CONFIG,
            )

        # Add the new automation and save
        automations.append(new_automation)

        try:
            await _save_automation_config(hass, automations)
            await _reload_automations(hass)
        except Exception as err:
            _LOGGER.exception("Error creating automation: %s", err)
            return self.json_message(
                f"Error creating automation: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json(
            {
                "id": automation_id,
                "entity_id": f"automation.{automation_id}",
                "alias": new_automation["alias"],
                "message": "Automation created. It may take a moment to appear.",
            },
            HTTPStatus.CREATED,
        )


class AutomationDetailView(HomeAssistantView):
    """View for single automation operations."""

    url = API_BASE_PATH_AUTOMATIONS + "/{automation_id}"
    name = "api:config_mcp:automation"
    requires_auth = True

    def _get_entity_id(self, automation_id: str) -> str:
        """Convert automation_id to entity_id if needed."""
        if automation_id.startswith("automation."):
            return automation_id
        return f"automation.{automation_id}"

    async def get(
        self, request: web.Request, automation_id: str
    ) -> web.Response:
        """Handle GET request - get single automation with config.

        Path params:
            automation_id: The automation ID or entity_id

        Returns:
            200: Automation data with config
            403: Permission denied
            404: Automation not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Check read permission
        if not check_permission(hass, CONF_AUTOMATIONS_READ):
            return self.json_message(
                "Automation read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        entity_id = self._get_entity_id(automation_id)
        entity = _get_automation_entity(hass, entity_id)

        # If not found and automation_id doesn't look like an entity_id, search by unique_id
        # This handles numeric IDs from UI-created automations (e.g., "1765219976897")
        if entity is None and not automation_id.startswith("automation."):
            component = get_automation_component(hass)
            if component is not None:
                for ent in component.entities:
                    if ent.unique_id == automation_id:
                        entity = ent
                        break

        if entity is None:
            return self.json_message(
                f"Automation '{automation_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_AUTOMATION_NOT_FOUND,
            )

        return self.json(_format_automation(entity, hass=hass, include_config=True))

    async def put(
        self, request: web.Request, automation_id: str
    ) -> web.Response:
        """Handle PUT request - full update of automation.

        Path params:
            automation_id: The automation ID

        Request body:
            Full automation config

        Returns:
            200: Automation updated
            400: Invalid request data
            401: Not authorized (non-admin)
            403: Permission denied
            404: Automation not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Check update permission
        if not check_permission(hass, CONF_AUTOMATIONS_UPDATE):
            return self.json_message(
                "Automation update permission is disabled",
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

        # Load existing automations
        automations = await _load_automation_config(hass)

        # Find the automation to update
        found_idx = None
        # Check both the direct ID and any variation
        search_id = automation_id.replace("automation.", "")

        for idx, automation in enumerate(automations):
            if automation.get("id") == search_id or automation.get("id") == automation_id:
                found_idx = idx
                break

        if found_idx is None:
            return self.json_message(
                f"Automation '{automation_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_AUTOMATION_NOT_FOUND,
            )

        # Build updated automation config preserving the ID
        updated_automation = {
            "id": automations[found_idx].get("id"),
            "alias": body.get("alias", automations[found_idx].get("alias")),
        }

        # Add optional fields
        if "description" in body:
            updated_automation["description"] = body["description"]
        if "mode" in body:
            updated_automation["mode"] = body["mode"]
        if "max" in body:
            updated_automation["max"] = body["max"]
        if "max_exceeded" in body:
            updated_automation["max_exceeded"] = body["max_exceeded"]
        if "variables" in body:
            updated_automation["variables"] = body["variables"]
        if "trigger_variables" in body:
            updated_automation["trigger_variables"] = body["trigger_variables"]

        # Add triggers (can be "trigger" or "triggers")
        triggers = body.get("triggers") or body.get("trigger") or []
        updated_automation["triggers"] = triggers

        # Add conditions (can be "condition" or "conditions")
        conditions = body.get("conditions") or body.get("condition") or []
        updated_automation["conditions"] = conditions

        # Add actions (can be "action" or "actions")
        actions = body.get("actions") or body.get("action") or []
        updated_automation["actions"] = actions

        # Validate actions before saving
        action_errors = validate_actions(hass, actions)
        if action_errors:
            return self.json_message(
                "Invalid actions in automation:\n" + "\n".join(action_errors),
                HTTPStatus.BAD_REQUEST,
                ERR_AUTOMATION_INVALID_CONFIG,
            )

        # Update and save
        automations[found_idx] = updated_automation

        try:
            await _save_automation_config(hass, automations)
            await _reload_automations(hass)
        except Exception as err:
            _LOGGER.exception("Error updating automation: %s", err)
            return self.json_message(
                f"Error updating automation: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "id": updated_automation["id"],
            "entity_id": f"automation.{updated_automation['id']}",
            "alias": updated_automation["alias"],
            "message": "Automation updated",
        })

    async def patch(
        self, request: web.Request, automation_id: str
    ) -> web.Response:
        """Handle PATCH request - partial update of automation.

        Path params:
            automation_id: The automation ID

        Request body (all fields optional):
            {
                "alias": "New Name",
                "description": "New description",
                "enabled": true/false,
                "category_id": "category_ulid",  # Assign category
                "labels": ["label_id_1", "label_id_2"]  # Assign labels
            }

        Returns:
            200: Automation updated
            400: Invalid request data
            401: Not authorized (non-admin)
            403: Permission denied
            404: Automation not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Check update permission
        if not check_permission(hass, CONF_AUTOMATIONS_UPDATE):
            return self.json_message(
                "Automation update permission is disabled",
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

        if not body:
            return self.json_message(
                "Request body cannot be empty",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        entity_id = self._get_entity_id(automation_id)
        search_id = automation_id.replace("automation.", "")
        result_messages = []

        # Handle enable/disable via service call
        if "enabled" in body:
            entity = _get_automation_entity(hass, entity_id)

            if entity is None:
                return self.json_message(
                    f"Automation '{automation_id}' not found",
                    HTTPStatus.NOT_FOUND,
                    ERR_AUTOMATION_NOT_FOUND,
                )

            service = "turn_on" if body["enabled"] else "turn_off"
            try:
                await hass.services.async_call(
                    AUTOMATION_DOMAIN,
                    service,
                    {"entity_id": entity_id},
                    blocking=True,
                )
                result_messages.append(f"{'Enabled' if body['enabled'] else 'Disabled'}")
            except Exception as err:
                _LOGGER.exception("Error toggling automation: %s", err)
                return self.json_message(
                    f"Error toggling automation: {err}",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        # Handle category and label updates via entity registry
        if "category_id" in body or "labels" in body:
            entity_registry = er.async_get(hass)
            registry_entry = entity_registry.async_get(entity_id)

            if registry_entry is None:
                return self.json_message(
                    f"Automation '{automation_id}' not found in entity registry",
                    HTTPStatus.NOT_FOUND,
                    ERR_AUTOMATION_NOT_FOUND,
                )

            update_kwargs = {}

            if "category_id" in body:
                category_id = body["category_id"]
                if category_id is None or category_id == "":
                    update_kwargs["categories"] = {}
                else:
                    update_kwargs["categories"] = {"automation": category_id}
                result_messages.append("Category updated")

            if "labels" in body:
                label_ids = body["labels"]
                if label_ids is None:
                    update_kwargs["labels"] = set()
                else:
                    update_kwargs["labels"] = set(label_ids)
                result_messages.append("Labels updated")

            if update_kwargs:
                try:
                    entity_registry.async_update_entity(entity_id, **update_kwargs)
                except Exception as err:
                    _LOGGER.exception("Error updating entity registry: %s", err)
                    return self.json_message(
                        f"Error updating category/labels: {err}",
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )

        # Check if we need to update config file fields
        config_fields = [
            "alias", "description", "mode", "max", "max_exceeded",
            "variables", "trigger_variables", "triggers", "trigger",
            "conditions", "condition", "actions", "action"
        ]
        has_config_updates = any(field in body for field in config_fields)

        if has_config_updates:
            # Load existing automations for config updates
            automations = await _load_automation_config(hass)

            # Find the automation to update
            found_idx = None
            for idx, automation in enumerate(automations):
                if automation.get("id") == search_id or automation.get("id") == automation_id:
                    found_idx = idx
                    break

            if found_idx is None:
                return self.json_message(
                    f"Automation '{automation_id}' not found",
                    HTTPStatus.NOT_FOUND,
                    ERR_AUTOMATION_NOT_FOUND,
                )

            # Merge updates with existing config
            updated_automation = automations[found_idx].copy()

            for field in config_fields:
                if field in body:
                    updated_automation[field] = body[field]

            # Validate actions if they were updated
            actions_to_validate = body.get("actions") or body.get("action")
            if actions_to_validate:
                action_errors = validate_actions(hass, actions_to_validate)
                if action_errors:
                    return self.json_message(
                        "Invalid actions in automation:\n" + "\n".join(action_errors),
                        HTTPStatus.BAD_REQUEST,
                        ERR_AUTOMATION_INVALID_CONFIG,
                    )

            # Update and save
            automations[found_idx] = updated_automation

            try:
                await _save_automation_config(hass, automations)
                await _reload_automations(hass)
                result_messages.append("Config updated")
            except Exception as err:
                _LOGGER.exception("Error updating automation: %s", err)
                return self.json_message(
                    f"Error updating automation: {err}",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        if not result_messages:
            result_messages.append("No changes made")

        return self.json({
            "id": search_id,
            "entity_id": entity_id,
            "message": ", ".join(result_messages),
        })

    async def delete(
        self, request: web.Request, automation_id: str
    ) -> web.Response:
        """Handle DELETE request - delete an automation.

        Path params:
            automation_id: The automation ID

        Returns:
            204: Automation deleted (no content)
            401: Not authorized (non-admin)
            403: Permission denied
            404: Automation not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Check delete permission
        if not check_permission(hass, CONF_AUTOMATIONS_DELETE):
            return self.json_message(
                "Automation delete permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Check admin permission
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        # Load existing automations
        automations = await _load_automation_config(hass)

        # Find the automation to delete
        found_idx = None
        search_id = automation_id.replace("automation.", "")

        for idx, automation in enumerate(automations):
            if automation.get("id") == search_id or automation.get("id") == automation_id:
                found_idx = idx
                break

        if found_idx is None:
            return self.json_message(
                f"Automation '{automation_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_AUTOMATION_NOT_FOUND,
            )

        # Get the entity_id before deletion for registry cleanup
        entity_id = self._get_entity_id(search_id)

        # Remove and save
        automations.pop(found_idx)

        try:
            await _save_automation_config(hass, automations)
            await _reload_automations(hass)

            # Clean up entity registry entry
            await _cleanup_entity_registry(hass, entity_id)
        except Exception as err:
            _LOGGER.exception("Error deleting automation: %s", err)
            return self.json_message(
                f"Error deleting automation: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return web.Response(status=HTTPStatus.NO_CONTENT)


class AutomationTriggerView(HomeAssistantView):
    """View for triggering an automation."""

    url = API_BASE_PATH_AUTOMATIONS + "/{automation_id}/trigger"
    name = "api:config_mcp:automation:trigger"
    requires_auth = True

    def _get_entity_id(self, automation_id: str) -> str:
        """Convert automation_id to entity_id if needed."""
        if automation_id.startswith("automation."):
            return automation_id
        return f"automation.{automation_id}"

    async def post(
        self, request: web.Request, automation_id: str
    ) -> web.Response:
        """Handle POST request - trigger an automation.

        Path params:
            automation_id: The automation ID or entity_id

        Request body (optional):
            {
                "skip_condition": false,
                "variables": {...}
            }

        Returns:
            200: Automation triggered
            401: Not authorized (non-admin)
            403: Permission denied
            404: Automation not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Check update permission (triggering counts as an update action)
        if not check_permission(hass, CONF_AUTOMATIONS_UPDATE):
            return self.json_message(
                "Automation update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Check admin permission
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        entity_id = self._get_entity_id(automation_id)
        entity = _get_automation_entity(hass, entity_id)

        if entity is None:
            return self.json_message(
                f"Automation '{automation_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_AUTOMATION_NOT_FOUND,
            )

        # Parse optional body for trigger parameters
        try:
            body = await request.json()
        except ValueError:
            body = {}

        service_data = {"entity_id": entity_id}

        if body.get("skip_condition"):
            service_data["skip_condition"] = True
        if body.get("variables"):
            service_data["variables"] = body["variables"]

        try:
            await hass.services.async_call(
                AUTOMATION_DOMAIN,
                "trigger",
                service_data,
                blocking=True,
            )
        except Exception as err:
            _LOGGER.exception("Error triggering automation: %s", err)
            return self.json_message(
                f"Error triggering automation: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "id": entity.unique_id,
            "entity_id": entity_id,
            "triggered": True,
            "message": "Automation triggered",
        })
