"""HTTP views for Lovelace resources (custom cards) REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import (
    API_BASE_PATH_RESOURCES,
    CONF_DASHBOARDS_READ,
    LOVELACE_DATA,
)
from .dashboards import check_permission

if TYPE_CHECKING:
    from homeassistant.components.lovelace import LovelaceData

_LOGGER = logging.getLogger(__name__)


def get_lovelace_data(hass: HomeAssistant):
    """Get lovelace data from hass.data."""
    return hass.data.get(LOVELACE_DATA)


class ResourceListView(HomeAssistantView):
    """View to list all Lovelace resources (custom cards, modules, etc.).

    This is a read-only discovery endpoint that lists custom frontend
    resources installed via HACS or manually configured.
    """

    url = API_BASE_PATH_RESOURCES
    name = "api:config_mcp:resources"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all Lovelace resources.

        Returns a list of custom resources (cards, modules, CSS) that are
        registered with Lovelace. This is useful for understanding what
        custom cards are available when generating dashboards.

        Returns:
            200: JSON array of resource metadata including:
                - id: Unique resource identifier
                - type: Resource type (module, js, css, html)
                - url: Path to the resource file
            403: Permission denied (requires dashboard read permission)
        """
        hass: HomeAssistant = request.app["hass"]

        # Check read permission (reuse dashboard read permission since
        # resources are part of Lovelace/dashboards)
        if not check_permission(hass, CONF_DASHBOARDS_READ):
            return self.json_message(
                "Dashboard read permission is disabled",
                HTTPStatus.FORBIDDEN,
            )

        lovelace_data = get_lovelace_data(hass)

        if not lovelace_data:
            return self.json([])

        resources = []

        try:
            # Get resources from the lovelace data
            # resources can be either ResourceYAMLCollection or ResourceStorageCollection
            resource_collection = lovelace_data.resources

            # Ensure storage collection is loaded if it has a load method
            if hasattr(resource_collection, 'loaded') and not resource_collection.loaded:
                if hasattr(resource_collection, 'async_load'):
                    await resource_collection.async_load()
                    resource_collection.loaded = True

            # async_items() is actually a synchronous method (decorated with @callback)
            items = resource_collection.async_items()

            for item in items:
                resource_data = {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "url": item.get("url"),
                }
                resources.append(resource_data)

        except AttributeError as err:
            _LOGGER.warning(
                "Could not access lovelace resources collection: %s", err
            )
            # Try fallback method - accessing the data directly
            try:
                if hasattr(lovelace_data, 'resources'):
                    resource_obj = lovelace_data.resources
                    if hasattr(resource_obj, 'data'):
                        # StorageCollection stores items in .data dict
                        for item_id, item in resource_obj.data.items():
                            resource_data = {
                                "id": item_id,
                                "type": item.get("type"),
                                "url": item.get("url"),
                            }
                            resources.append(resource_data)
                    elif hasattr(resource_obj, 'async_get_info'):
                        # Try getting info which may contain resource count
                        info = await resource_obj.async_get_info()
                        _LOGGER.debug("Resources info: %s", info)
            except Exception as inner_err:
                _LOGGER.warning(
                    "Fallback method for resources also failed: %s", inner_err
                )
        except Exception as err:
            _LOGGER.warning(
                "Error getting lovelace resources: %s", err
            )

        return self.json(resources)
