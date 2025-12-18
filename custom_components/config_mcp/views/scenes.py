"""HTTP views for scene REST API."""

from __future__ import annotations

import logging
import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import (
    API_BASE_PATH_SCENES,
    CONF_SCENES_CREATE,
    CONF_SCENES_DELETE,
    CONF_SCENES_READ,
    CONF_SCENES_UPDATE,
    DEFAULT_OPTIONS,
    DOMAIN,
    ERR_INVALID_CONFIG,
    ERR_SCENE_EXISTS,
    ERR_SCENE_INVALID_CONFIG,
    ERR_SCENE_NOT_FOUND,
)

if TYPE_CHECKING:
    from homeassistant.components.scene import Scene

_LOGGER = logging.getLogger(__name__)

# Domain for the scene component
SCENE_DOMAIN = "scene"


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


def get_scene_component(hass: HomeAssistant):
    """Get the scene component from hass.data."""
    return hass.data.get(SCENE_DOMAIN)


def _get_scene_entity(hass: HomeAssistant, entity_id: str):
    """Get a scene entity by ID."""
    component = get_scene_component(hass)
    if component is None:
        return None
    return component.get_entity(entity_id)


def _format_scene(entity, include_config: bool = False) -> dict[str, Any]:
    """Format a scene entity for API response."""
    # Get the scene ID from entity_id (scene.xxx -> xxx)
    scene_id = entity.entity_id.replace("scene.", "")

    result = {
        "id": scene_id,
        "entity_id": entity.entity_id,
        "name": entity.name,
        "state": entity.state,  # "scening" briefly when activated, usually "unknown"
    }

    # Add icon if available
    if hasattr(entity, "icon") and entity.icon:
        result["icon"] = entity.icon

    if include_config:
        # Include the raw config if available
        if hasattr(entity, "scene_config") and entity.scene_config:
            result["config"] = entity.scene_config
        elif hasattr(entity, "_config") and entity._config:
            result["config"] = entity._config

    return result


async def _load_scene_config(hass: HomeAssistant) -> list[dict]:
    """Load scenes from scenes.yaml.

    Returns a list of scene configs (scenes use list format like automations).
    """
    import yaml
    from pathlib import Path

    scene_path = Path(hass.config.path("scenes.yaml"))

    if not scene_path.exists():
        return []

    def read_yaml():
        try:
            with open(scene_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, list) else []
        except Exception as err:
            _LOGGER.error("Error reading scenes.yaml: %s", err)
            return []

    return await hass.async_add_executor_job(read_yaml)


async def _save_scene_config(hass: HomeAssistant, scenes: list[dict]) -> None:
    """Save scenes to scenes.yaml."""
    import yaml
    from pathlib import Path

    scene_path = Path(hass.config.path("scenes.yaml"))

    def write_yaml():
        try:
            with open(scene_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(scenes, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as err:
            _LOGGER.error("Error writing scenes.yaml: %s", err)
            raise

    await hass.async_add_executor_job(write_yaml)


async def _reload_scenes(hass: HomeAssistant) -> None:
    """Reload scenes to apply changes."""
    await hass.services.async_call(
        SCENE_DOMAIN,
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


def _find_scene_by_id(scenes: list[dict], scene_id: str) -> tuple[int, dict | None]:
    """Find a scene in the list by its ID.

    Returns (index, scene_config) or (-1, None) if not found.
    """
    for idx, scene in enumerate(scenes):
        if scene.get("id") == scene_id:
            return idx, scene
    return -1, None


def validate_entities(hass: HomeAssistant, entities: dict) -> list[str]:
    """Validate that all entities in a scene configuration exist.

    Args:
        hass: Home Assistant instance
        entities: Dict of entity_id -> state configuration

    Returns:
        List of error messages for invalid entities (empty if all valid)
    """
    if not entities:
        return []

    errors = []
    state_machine = hass.states

    for entity_id in entities.keys():
        # Check if entity exists
        if state_machine.get(entity_id) is None:
            errors.append(f"Entity '{entity_id}' does not exist")

    return errors


class SceneListView(HomeAssistantView):
    """View to list all scenes and create new ones."""

    url = API_BASE_PATH_SCENES
    name = "api:config_mcp:scenes"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all scenes."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCENES_READ):
            return self.json_message(
                "Scene read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        component = get_scene_component(hass)

        if component is None:
            return self.json([])

        scenes = []
        for entity in component.entities:
            try:
                scenes.append(_format_scene(entity, include_config=False))
            except Exception as err:
                _LOGGER.warning(
                    "Error getting info for scene %s: %s",
                    entity.entity_id,
                    err,
                )
                continue

        return self.json(scenes)

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request - create new scene.

        Request body:
            {
                "id": "my_scene",  (optional, will be generated if not provided)
                "name": "My Scene",
                "icon": "mdi:lightbulb",
                "entities": {
                    "light.living_room": {
                        "state": "on",
                        "brightness": 128
                    },
                    "switch.fan": "off"
                }
            }
        """
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCENES_CREATE):
            return self.json_message(
                "Scene create permission is disabled",
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
        if "name" not in body:
            return self.json_message(
                "Missing required field: name",
                HTTPStatus.BAD_REQUEST,
                ERR_SCENE_INVALID_CONFIG,
            )

        # Generate scene ID or use provided one
        if "id" in body:
            scene_id = body["id"]
        else:
            scene_id = str(uuid.uuid4()).replace("-", "")

        # Load existing scenes
        scenes = await _load_scene_config(hass)

        # Check if scene ID already exists
        existing_idx, _ = _find_scene_by_id(scenes, scene_id)
        if existing_idx >= 0:
            return self.json_message(
                f"Scene with id '{scene_id}' already exists",
                HTTPStatus.CONFLICT,
                ERR_SCENE_EXISTS,
            )

        # Build the scene config
        new_scene = {
            "id": scene_id,
            "name": body["name"],
        }

        if "icon" in body:
            new_scene["icon"] = body["icon"]

        # Get entities configuration
        entities = body.get("entities", {})
        new_scene["entities"] = entities

        # Validate entities exist
        entity_errors = validate_entities(hass, entities)
        if entity_errors:
            return self.json_message(
                "Invalid entities in scene:\n" + "\n".join(entity_errors),
                HTTPStatus.BAD_REQUEST,
                ERR_SCENE_INVALID_CONFIG,
            )

        # Add the new scene and save
        scenes.append(new_scene)

        try:
            await _save_scene_config(hass, scenes)
            await _reload_scenes(hass)
        except Exception as err:
            _LOGGER.exception("Error creating scene: %s", err)
            return self.json_message(
                f"Error creating scene: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json(
            {
                "id": scene_id,
                "entity_id": f"scene.{body['name'].lower().replace(' ', '_').replace('-', '_')}",
                "name": body["name"],
                "message": "Scene created. It may take a moment to appear.",
            },
            HTTPStatus.CREATED,
        )


class SceneDetailView(HomeAssistantView):
    """View for single scene operations."""

    url = API_BASE_PATH_SCENES + "/{scene_id}"
    name = "api:config_mcp:scene"
    requires_auth = True

    def _get_entity_id(self, scene_id: str) -> str:
        """Convert scene_id to entity_id if needed."""
        if scene_id.startswith("scene."):
            return scene_id
        return f"scene.{scene_id}"

    def _get_scene_id(self, scene_id: str) -> str:
        """Get the scene ID without the domain prefix."""
        if scene_id.startswith("scene."):
            return scene_id.replace("scene.", "")
        return scene_id

    async def get(
        self, request: web.Request, scene_id: str
    ) -> web.Response:
        """Handle GET request - get single scene with config."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCENES_READ):
            return self.json_message(
                "Scene read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        # Load scenes from YAML to get full config
        scenes = await _load_scene_config(hass)
        clean_id = self._get_scene_id(scene_id)

        # Find the scene by ID
        _, scene_config = _find_scene_by_id(scenes, clean_id)

        if scene_config is None:
            # Try to find by entity name slug
            entity_id = self._get_entity_id(clean_id)
            entity = _get_scene_entity(hass, entity_id)

            if entity is None:
                return self.json_message(
                    f"Scene '{scene_id}' not found",
                    HTTPStatus.NOT_FOUND,
                    ERR_SCENE_NOT_FOUND,
                )

            # Return basic info from entity
            return self.json(_format_scene(entity, include_config=True))

        # Return full config from YAML
        return self.json({
            "id": scene_config.get("id"),
            "name": scene_config.get("name"),
            "icon": scene_config.get("icon"),
            "entities": scene_config.get("entities", {}),
        })

    async def put(
        self, request: web.Request, scene_id: str
    ) -> web.Response:
        """Handle PUT request - full update of scene."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCENES_UPDATE):
            return self.json_message(
                "Scene update permission is disabled",
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

        # Load existing scenes
        scenes = await _load_scene_config(hass)
        clean_id = self._get_scene_id(scene_id)

        # Find the scene
        existing_idx, _ = _find_scene_by_id(scenes, clean_id)
        if existing_idx < 0:
            return self.json_message(
                f"Scene '{scene_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCENE_NOT_FOUND,
            )

        # Build updated scene config
        updated_scene = {
            "id": clean_id,
        }

        if "name" in body:
            updated_scene["name"] = body["name"]
        else:
            updated_scene["name"] = scenes[existing_idx].get("name", clean_id)

        if "icon" in body:
            updated_scene["icon"] = body["icon"]

        # Get entities configuration
        entities = body.get("entities", {})
        updated_scene["entities"] = entities

        # Validate entities exist
        entity_errors = validate_entities(hass, entities)
        if entity_errors:
            return self.json_message(
                "Invalid entities in scene:\n" + "\n".join(entity_errors),
                HTTPStatus.BAD_REQUEST,
                ERR_SCENE_INVALID_CONFIG,
            )

        # Update and save
        scenes[existing_idx] = updated_scene

        try:
            await _save_scene_config(hass, scenes)
            await _reload_scenes(hass)
        except Exception as err:
            _LOGGER.exception("Error updating scene: %s", err)
            return self.json_message(
                f"Error updating scene: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "id": clean_id,
            "name": updated_scene.get("name", clean_id),
            "message": "Scene updated",
        })

    async def patch(
        self, request: web.Request, scene_id: str
    ) -> web.Response:
        """Handle PATCH request - partial update of scene."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCENES_UPDATE):
            return self.json_message(
                "Scene update permission is disabled",
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

        # Load existing scenes
        scenes = await _load_scene_config(hass)
        clean_id = self._get_scene_id(scene_id)

        # Find the scene
        existing_idx, existing_scene = _find_scene_by_id(scenes, clean_id)
        if existing_idx < 0:
            return self.json_message(
                f"Scene '{scene_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCENE_NOT_FOUND,
            )

        # Merge updates with existing config
        updated_scene = existing_scene.copy()

        # Update allowed fields
        if "name" in body:
            updated_scene["name"] = body["name"]
        if "icon" in body:
            updated_scene["icon"] = body["icon"]
        if "entities" in body:
            updated_scene["entities"] = body["entities"]

            # Validate entities if updated
            entity_errors = validate_entities(hass, body["entities"])
            if entity_errors:
                return self.json_message(
                    "Invalid entities in scene:\n" + "\n".join(entity_errors),
                    HTTPStatus.BAD_REQUEST,
                    ERR_SCENE_INVALID_CONFIG,
                )

        # Update and save
        scenes[existing_idx] = updated_scene

        try:
            await _save_scene_config(hass, scenes)
            await _reload_scenes(hass)
        except Exception as err:
            _LOGGER.exception("Error updating scene: %s", err)
            return self.json_message(
                f"Error updating scene: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "id": clean_id,
            "name": updated_scene.get("name", clean_id),
            "message": "Scene updated",
        })

    async def delete(
        self, request: web.Request, scene_id: str
    ) -> web.Response:
        """Handle DELETE request - delete a scene."""
        hass: HomeAssistant = request.app["hass"]

        if not check_permission(hass, CONF_SCENES_DELETE):
            return self.json_message(
                "Scene delete permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        # Load existing scenes
        scenes = await _load_scene_config(hass)
        clean_id = self._get_scene_id(scene_id)

        # Find the scene
        existing_idx, existing_scene = _find_scene_by_id(scenes, clean_id)
        if existing_idx < 0:
            return self.json_message(
                f"Scene '{scene_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCENE_NOT_FOUND,
            )

        # Get entity_id for registry cleanup (derive from name)
        scene_name = existing_scene.get("name", clean_id)
        entity_id = f"scene.{scene_name.lower().replace(' ', '_').replace('-', '_')}"

        # Remove and save
        scenes.pop(existing_idx)

        try:
            await _save_scene_config(hass, scenes)
            await _reload_scenes(hass)

            # Clean up entity registry entry
            await _cleanup_entity_registry(hass, entity_id)
        except Exception as err:
            _LOGGER.exception("Error deleting scene: %s", err)
            return self.json_message(
                f"Error deleting scene: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return web.Response(status=HTTPStatus.NO_CONTENT)


class SceneActivateView(HomeAssistantView):
    """View for activating a scene."""

    url = API_BASE_PATH_SCENES + "/{scene_id}/activate"
    name = "api:config_mcp:scene:activate"
    requires_auth = True

    def _get_entity_id(self, scene_id: str) -> str:
        """Convert scene_id to entity_id if needed."""
        if scene_id.startswith("scene."):
            return scene_id
        return f"scene.{scene_id}"

    async def post(
        self, request: web.Request, scene_id: str
    ) -> web.Response:
        """Handle POST request - activate a scene.

        Request body (optional):
            {
                "transition": 2  # Transition time in seconds
            }
        """
        hass: HomeAssistant = request.app["hass"]

        # Activating a scene counts as an update action
        if not check_permission(hass, CONF_SCENES_UPDATE):
            return self.json_message(
                "Scene update permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return self.json_message(
                "Admin permission required",
                HTTPStatus.UNAUTHORIZED,
            )

        # Try to find the scene - first check by ID in YAML, then by entity_id
        scenes = await _load_scene_config(hass)

        # Check if scene_id is a UUID-style ID from our config
        _, scene_config = _find_scene_by_id(scenes, scene_id)

        if scene_config is not None:
            # Found by ID - derive entity_id from name
            scene_name = scene_config.get("name", scene_id)
            entity_id = f"scene.{scene_name.lower().replace(' ', '_').replace('-', '_')}"
        else:
            # Not found by ID - try as entity_id directly
            entity_id = self._get_entity_id(scene_id)

        entity = _get_scene_entity(hass, entity_id)

        if entity is None:
            return self.json_message(
                f"Scene '{scene_id}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SCENE_NOT_FOUND,
            )

        # Parse optional body for transition
        try:
            body = await request.json()
        except ValueError:
            body = {}

        service_data = {"entity_id": entity_id}

        # Add transition if provided
        if body.get("transition"):
            service_data["transition"] = body["transition"]

        try:
            await hass.services.async_call(
                SCENE_DOMAIN,
                "turn_on",
                service_data,
                blocking=True,
            )
        except Exception as err:
            _LOGGER.exception("Error activating scene: %s", err)
            return self.json_message(
                f"Error activating scene: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json({
            "id": scene_id,
            "entity_id": entity_id,
            "activated": True,
            "message": "Scene activated",
        })
