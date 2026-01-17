"""HTTP views for script REST API."""

from __future__ import annotations

import logging
import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import (
    API_BASE_PATH_SCRIPTS,
    CONF_SCRIPTS_CREATE,
    CONF_SCRIPTS_DELETE,
    CONF_SCRIPTS_READ,
    CONF_SCRIPTS_UPDATE,
    DEFAULT_OPTIONS,
    DOMAIN,
    ERR_INVALID_CONFIG,
    ERR_SCRIPT_EXISTS,
    ERR_SCRIPT_INVALID_CONFIG,
    ERR_SCRIPT_NOT_FOUND,
)

if TYPE_CHECKING:
    from homeassistant.components.script import ScriptEntity

_LOGGER = logging.getLogger(__name__)

# Domain for the script component
SCRIPT_DOMAIN = "script"


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


def get_available_services(hass: HomeAssistant) -> dict[str, set[str]]:
    """Get all available services grouped by domain.

    Returns:
        Dict mapping domain to set of service names
    """
    services = {}
    for domain, domain_services in hass.services.async_services().items():
        services[domain] = set(domain_services.keys())
    return services


def validate_sequence(hass: HomeAssistant, sequence: list[dict]) -> list[str]:
    """Validate that all actions in a sequence reference valid services.

    Args:
        hass: Home Assistant instance
        sequence: List of action dicts from script sequence

    Returns:
        List of error messages for invalid actions (empty if all valid)
    """
    if not sequence:
        return []

    available_services = get_available_services(hass)
    errors = []

    for idx, action in enumerate(sequence):
        # Get the action/service name
        action_name = action.get("action") or action.get("service")

        if not action_name:
            # Skip actions without an action/service field (could be delay, condition, etc.)
            continue

        # Parse domain.service format
        if "." in action_name:
            domain, service = action_name.split(".", 1)
        else:
            errors.append(f"Step {idx + 1}: '{action_name}' is not in domain.service format")
            continue

        # Check if domain exists
        if domain not in available_services:
            errors.append(
                f"Step {idx + 1}: Unknown domain '{domain}' in '{action_name}'. "
                f"Available domains include: {', '.join(sorted(list(available_services.keys())[:10]))}..."
            )
            continue

        # Check if service exists in domain
        if service not in available_services[domain]:
            available = ", ".join(sorted(available_services[domain]))
            errors.append(
                f"Step {idx + 1}: Unknown service '{service}' in domain '{domain}'. "
                f"Available services: {available}"
            )

    return errors


def get_script_component(hass: HomeAssistant):
    """Get the script component from hass.data."""
    return hass.data.get(SCRIPT_DOMAIN)


def _get_script_entity(hass: HomeAssistant, entity_id: str):
    """Get a script entity by ID."""
    component = get_script_component(hass)
    if component is None:
        return None
    return component.get_entity(entity_id)


def _format_script(entity, hass: HomeAssistant = None, include_config: bool = False) -> dict[str, Any]:
    """Format a script entity for API response."""
    # Get the script ID from entity_id (script.xxx -> xxx)
    script_id = entity.entity_id.replace("script.", "")

    result = {
        "id": script_id,
        "entity_id": entity.entity_id,
        "name": entity.name,
        "state": entity.state,  # "on" (running) or "off" (idle)
        "is_running": entity.state == "on",
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
        # Include the raw config if available
        if hasattr(entity, "raw_config") and entity.raw_config:
            result["config"] = entity.raw_config

    return result


async def _load_script_config(hass: HomeAssistant) -> dict[str, dict]:
    """Load scripts from scripts.yaml.

    Returns a dict of script_id -> config
    """
    import yaml
    from pathlib import Path

    script_path = Path(hass.config.path("scripts.yaml"))

    if not script_path.exists():
        return {}

    def read_yaml():
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if data else {}
        except Exception as err:
            _LOGGER.error("Error reading scripts.yaml: %s", err)
            return {}

    return await hass.async_add_executor_job(read_yaml)


async def _save_script_config(hass: HomeAssistant, scripts: dict[str, dict]) -> None:
    """Save scripts to scripts.yaml."""
    import yaml
    from pathlib import Path

    script_path = Path(hass.config.path("scripts.yaml"))

    def write_yaml():
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(scripts, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as err:
            _LOGGER.error("Error writing scripts.yaml: %s", err)
            raise

    await hass.async_add_executor_job(write_yaml)


async def _reload_scripts(hass: HomeAssistant) -> None:
    """Reload scripts to apply changes."""
    await hass.services.async_call(
        SCRIPT_DOMAIN,
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


class ScriptListView(HomeAssistantView):
    """View to list all scripts and create new ones."""

    url = API_BASE_PATH_SCRIPTS
    name = "api:config_mcp:scripts"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all scripts."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCRIPTS_READ):
            return self.json_message(
                "Script read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        component = get_script_component(hass)

        if component is None:
            return self.json([])

        scripts = []
        for entity in component.entities:
            try:
                scripts.append(_format_script(entity, hass=hass, include_config=False))
            except Exception as err:
                _LOGGER.warning(
                    "Error getting info for script %s: %s",
                    entity.entity_id,
                    err,
                )
                continue

        return self.json(scripts)

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request - create new script.

        Request body:
            {
                "id": "my_script",  (optional, will be generated if not provided)
                "alias": "My Script",
                "description": "Optional description",
                "icon": "mdi:script",
                "mode": "single",
                "sequence": [...]
            }
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCRIPTS_CREATE):
            return self.json_message(
                "Script create permission is disabled",
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
        if "alias" not in body and "id" not in body:
            return self.json_message(
                "Missing required field: alias or id",
                HTTPStatus.BAD_REQUEST,
                ERR_SCRIPT_INVALID_CONFIG,
            )

        # Generate script ID from alias or use provided ID
        if "id" in body:
            script_id = body["id"]
        else:
            # Convert alias to valid script ID (lowercase, underscores)
            script_id = body["alias"].lower().replace(" ", "_").replace("-", "_")
            # Remove any non-alphanumeric characters except underscores
            script_id = "".join(c for c in script_id if c.isalnum() or c == "_")

        # Load existing scripts
        scripts = await _load_script_config(hass)

        # Check if script ID already exists
        if script_id in scripts:
            return self.json_message(
                f"Script with id '{script_id}' already exists",
                HTTPStatus.CONFLICT,
                ERR_SCRIPT_EXISTS,
            )

        # Build the script config
        new_script = {}

        if "alias" in body:
            new_script["alias"] = body["alias"]
        if "description" in body:
            new_script["description"] = body["description"]
        if "icon" in body:
            new_script["icon"] = body["icon"]
        if "mode" in body:
            new_script["mode"] = body["mode"]
        if "max" in body:
            new_script["max"] = body["max"]
        if "max_exceeded" in body:
            new_script["max_exceeded"] = body["max_exceeded"]
        if "fields" in body:
            new_script["fields"] = body["fields"]
        if "variables" in body:
            new_script["variables"] = body["variables"]

        # Add sequence (required for scripts)
        sequence = body.get("sequence", [])
        new_script["sequence"] = sequence

        # Validate sequence actions before saving
        sequence_errors = validate_sequence(hass, sequence)
        if sequence_errors:
            return self.json_message(
                "Invalid actions in script sequence:\n" + "\n".join(sequence_errors),
                HTTPStatus.BAD_REQUEST,
                ERR_SCRIPT_INVALID_CONFIG,
            )

        # Add the new script and save
        scripts[script_id] = new_script

        try:
            await _save_script_config(hass, scripts)
            await _reload_scripts(hass)
        except Exception as err:
            _LOGGER.exception("Error creating script: %s", err)
            return self.json_message(
                f"Error creating script: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json(
            {
                "id": script_id,
                "entity_id": f"script.{script_id}",
                "alias": new_script.get("alias", script_id),
                "message": "Script created. It may take a moment to appear.",
            },
            HTTPStatus.CREATED,
        )


class ScriptDetailView(HomeAssistantView):
    """View for single script operations."""

    url = API_BASE_PATH_SCRIPTS + "/{script_id}"
    name = "api:config_mcp:script"
    requires_auth = True

    def _get_entity_id(self, script_id: str) -> str:
        """Convert script_id to entity_id if needed."""
        if script_id.startswith("script."):
            return script_id
        return f"script.{script_id}"

    def _get_script_id(self, script_id: str) -> str:
        """Get the script ID without the domain prefix."""
        if script_id.startswith("script."):
            return script_id.replace("script.", "")
        return script_id

    async def get(
        self, request: web.Request, script_id: str
    ) -> web.Response:
        """Handle GET request - get single script with config."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCRIPTS_READ):
            return self.json_message(
                "Script read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        entity_id = self._get_entity_id(script_id)
        entity = _get_script_entity(hass, entity_id)

        if entity is None:
            return self.json_message(
                f"Script '{script_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCRIPT_NOT_FOUND,
            )

        return self.json(_format_script(entity, hass=hass, include_config=True))

    async def put(
        self, request: web.Request, script_id: str
    ) -> web.Response:
        """Handle PUT request - full update of script."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCRIPTS_UPDATE):
            return self.json_message(
                "Script update permission is disabled",
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

        # Load existing scripts
        scripts = await _load_script_config(hass)
        clean_id = self._get_script_id(script_id)

        if clean_id not in scripts:
            return self.json_message(
                f"Script '{script_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCRIPT_NOT_FOUND,
            )

        # Build updated script config
        updated_script = {}

        if "alias" in body:
            updated_script["alias"] = body["alias"]
        if "description" in body:
            updated_script["description"] = body["description"]
        if "icon" in body:
            updated_script["icon"] = body["icon"]
        if "mode" in body:
            updated_script["mode"] = body["mode"]
        if "max" in body:
            updated_script["max"] = body["max"]
        if "max_exceeded" in body:
            updated_script["max_exceeded"] = body["max_exceeded"]
        if "fields" in body:
            updated_script["fields"] = body["fields"]
        if "variables" in body:
            updated_script["variables"] = body["variables"]

        # Sequence is required
        sequence = body.get("sequence", [])
        updated_script["sequence"] = sequence

        # Validate sequence actions before saving
        sequence_errors = validate_sequence(hass, sequence)
        if sequence_errors:
            return self.json_message(
                "Invalid actions in script sequence:\n" + "\n".join(sequence_errors),
                HTTPStatus.BAD_REQUEST,
                ERR_SCRIPT_INVALID_CONFIG,
            )

        # Update and save
        scripts[clean_id] = updated_script

        try:
            await _save_script_config(hass, scripts)
            await _reload_scripts(hass)
        except Exception as err:
            _LOGGER.exception("Error updating script: %s", err)
            return self.json_message(
                f"Error updating script: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "id": clean_id,
            "entity_id": f"script.{clean_id}",
            "alias": updated_script.get("alias", clean_id),
            "message": "Script updated",
        })

    async def patch(
        self, request: web.Request, script_id: str
    ) -> web.Response:
        """Handle PATCH request - partial update of script.

        Request body (all fields optional):
            {
                "alias": "New Name",
                "description": "New description",
                "category_id": "category_ulid",  # Assign category
                "labels": ["label_id_1", "label_id_2"]  # Assign labels
            }
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCRIPTS_UPDATE):
            return self.json_message(
                "Script update permission is disabled",
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
                "Request body cannot be empty",
                HTTPStatus.BAD_REQUEST,
                ERR_INVALID_CONFIG,
            )

        clean_id = self._get_script_id(script_id)
        entity_id = f"script.{clean_id}"
        result_messages = []

        # Handle category and label updates via entity registry
        if "category_id" in body or "labels" in body:
            entity_registry = er.async_get(hass)
            registry_entry = entity_registry.async_get(entity_id)

            if registry_entry is None:
                return self.json_message(
                    f"Script '{script_id}' not found in entity registry",
                    HTTPStatus.NOT_FOUND,
                    ERR_SCRIPT_NOT_FOUND,
                )

            update_kwargs = {}

            if "category_id" in body:
                category_id = body["category_id"]
                if category_id is None or category_id == "":
                    update_kwargs["categories"] = {}
                else:
                    update_kwargs["categories"] = {"script": category_id}
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
            "alias", "description", "icon", "mode", "max", "max_exceeded",
            "fields", "variables", "sequence"
        ]
        has_config_updates = any(field in body for field in config_fields)

        if has_config_updates:
            # Load existing scripts
            scripts = await _load_script_config(hass)

            if clean_id not in scripts:
                return self.json_message(
                    f"Script '{script_id}' not found",
                    HTTPStatus.NOT_FOUND,
                    ERR_SCRIPT_NOT_FOUND,
                )

            # Merge updates with existing config
            updated_script = scripts[clean_id].copy()

            for field in config_fields:
                if field in body:
                    updated_script[field] = body[field]

            # Validate sequence if it was updated
            if "sequence" in body:
                sequence_errors = validate_sequence(hass, body["sequence"])
                if sequence_errors:
                    return self.json_message(
                        "Invalid actions in script sequence:\n" + "\n".join(sequence_errors),
                        HTTPStatus.BAD_REQUEST,
                        ERR_SCRIPT_INVALID_CONFIG,
                    )

            # Update and save
            scripts[clean_id] = updated_script

            try:
                await _save_script_config(hass, scripts)
                await _reload_scripts(hass)
                result_messages.append("Config updated")
            except Exception as err:
                _LOGGER.exception("Error updating script: %s", err)
                return self.json_message(
                    f"Error updating script: {err}",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        if not result_messages:
            result_messages.append("No changes made")

        return self.json({
            "id": clean_id,
            "entity_id": entity_id,
            "message": ", ".join(result_messages),
        })

    async def delete(
        self, request: web.Request, script_id: str
    ) -> web.Response:
        """Handle DELETE request - delete a script."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCRIPTS_DELETE):
            return self.json_message(
                "Script delete permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        # Load existing scripts
        scripts = await _load_script_config(hass)
        clean_id = self._get_script_id(script_id)

        if clean_id not in scripts:
            return self.json_message(
                f"Script '{script_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCRIPT_NOT_FOUND,
            )

        # Get the entity_id before deletion for registry cleanup
        entity_id = self._get_entity_id(clean_id)

        # Remove and save
        del scripts[clean_id]

        try:
            await _save_script_config(hass, scripts)
            await _reload_scripts(hass)

            # Clean up entity registry entry
            await _cleanup_entity_registry(hass, entity_id)
        except Exception as err:
            _LOGGER.exception("Error deleting script: %s", err)
            return self.json_message(
                f"Error deleting script: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return web.Response(status=HTTPStatus.NO_CONTENT)


class ScriptRunView(HomeAssistantView):
    """View for running a script."""

    url = API_BASE_PATH_SCRIPTS + "/{script_id}/run"
    name = "api:config_mcp:script:run"
    requires_auth = True

    def _get_entity_id(self, script_id: str) -> str:
        """Convert script_id to entity_id if needed."""
        if script_id.startswith("script."):
            return script_id
        return f"script.{script_id}"

    async def post(
        self, request: web.Request, script_id: str
    ) -> web.Response:
        """Handle POST request - run a script.

        Request body (optional):
            {
                "variables": {...}  # Variables to pass to the script
            }
        """
        hass: HomeAssistant = request.app["hass"]

        # Running a script counts as an update action
        if not check_permission(hass, CONF_SCRIPTS_UPDATE):
            return self.json_message(
                "Script update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        entity_id = self._get_entity_id(script_id)
        entity = _get_script_entity(hass, entity_id)

        if entity is None:
            return self.json_message(
                f"Script '{script_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCRIPT_NOT_FOUND,
            )

        # Parse optional body for variables
        try:
            body = await request.json()
        except ValueError:
            body = {}

        service_data = {"entity_id": entity_id}

        # Add variables if provided
        if body.get("variables"):
            service_data["variables"] = body["variables"]

        try:
            await hass.services.async_call(
                SCRIPT_DOMAIN,
                "turn_on",
                service_data,
                blocking=True,
            )
        except Exception as err:
            _LOGGER.exception("Error running script: %s", err)
            return self.json_message(
                f"Error running script: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "id": script_id.replace("script.", ""),
            "entity_id": entity_id,
            "started": True,
            "message": "Script started",
        })


class ScriptStopView(HomeAssistantView):
    """View for stopping a running script."""

    url = API_BASE_PATH_SCRIPTS + "/{script_id}/stop"
    name = "api:config_mcp:script:stop"
    requires_auth = True

    def _get_entity_id(self, script_id: str) -> str:
        """Convert script_id to entity_id if needed."""
        if script_id.startswith("script."):
            return script_id
        return f"script.{script_id}"

    async def post(
        self, request: web.Request, script_id: str
    ) -> web.Response:
        """Handle POST request - stop a running script."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCRIPTS_UPDATE):
            return self.json_message(
                "Script update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        entity_id = self._get_entity_id(script_id)
        entity = _get_script_entity(hass, entity_id)

        if entity is None:
            return self.json_message(
                f"Script '{script_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCRIPT_NOT_FOUND,
            )

        try:
            await hass.services.async_call(
                SCRIPT_DOMAIN,
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.exception("Error stopping script: %s", err)
            return self.json_message(
                f"Error stopping script: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "id": script_id.replace("script.", ""),
            "entity_id": entity_id,
            "stopped": True,
            "message": "Script stopped",
        })
