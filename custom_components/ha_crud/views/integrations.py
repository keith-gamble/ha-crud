"""HTTP views for integration discovery REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integrations

from ..const import (
    API_BASE_PATH_INTEGRATIONS,
)

_LOGGER = logging.getLogger(__name__)

# Error code
ERR_INTEGRATION_NOT_FOUND = "integration_not_found"


class IntegrationListView(HomeAssistantView):
    """View to list all active integrations."""

    url = API_BASE_PATH_INTEGRATIONS
    name = "api:ha_crud:integrations"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all active integrations.

        Returns:
            200: JSON array of integration data
        """
        hass: HomeAssistant = request.app["hass"]

        # Get registries
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        # Get all config entries grouped by domain
        domain_entries: dict[str, list] = {}
        for entry in hass.config_entries.async_entries():
            if entry.domain not in domain_entries:
                domain_entries[entry.domain] = []
            domain_entries[entry.domain].append(entry)

        # Count devices per integration
        domain_device_counts: dict[str, int] = {}
        for device in device_registry.devices.values():
            if device.disabled:
                continue
            # Get integration from identifiers
            for identifier in device.identifiers:
                if isinstance(identifier, (tuple, list)) and len(identifier) >= 1:
                    domain = identifier[0]
                    domain_device_counts[domain] = domain_device_counts.get(domain, 0) + 1
                    break

        # Count entities per integration (by platform)
        domain_entity_counts: dict[str, int] = {}
        for entity in entity_registry.entities.values():
            if entity.disabled:
                continue
            platform = entity.platform
            domain_entity_counts[platform] = domain_entity_counts.get(platform, 0) + 1

        # Get integration info
        integration_domains = list(domain_entries.keys())
        integrations_info = await async_get_integrations(hass, integration_domains)

        integrations = []
        for domain, entries in sorted(domain_entries.items()):
            # Determine overall state
            states = [entry.state.value for entry in entries]
            if all(s == "loaded" for s in states):
                overall_state = "loaded"
            elif any(s == "loaded" for s in states):
                overall_state = "partial"
            else:
                overall_state = states[0] if states else "unknown"

            # Get integration name from loader
            integration_info = integrations_info.get(domain)
            if integration_info and not isinstance(integration_info, Exception):
                name = integration_info.name
            else:
                name = domain.replace("_", " ").title()

            integrations.append({
                "domain": domain,
                "name": name,
                "config_entries": len(entries),
                "device_count": domain_device_counts.get(domain, 0),
                "entity_count": domain_entity_counts.get(domain, 0),
                "state": overall_state,
            })

        # Sort by name
        integrations.sort(key=lambda x: x["name"].lower())

        return self.json(integrations)


class IntegrationDetailView(HomeAssistantView):
    """View to get single integration details."""

    url = API_BASE_PATH_INTEGRATIONS + "/{domain}"
    name = "api:ha_crud:integration"
    requires_auth = True

    async def get(self, request: web.Request, domain: str) -> web.Response:
        """Handle GET request - get integration details.

        Path params:
            domain: The integration domain (e.g., 'hue', 'zwave_js')

        Returns:
            200: Integration details with config entries, devices, entities
            404: Integration not found
        """
        hass: HomeAssistant = request.app["hass"]

        # Get config entries for this domain
        entries = hass.config_entries.async_entries(domain)
        if not entries:
            return self.json_message(
                f"Integration '{domain}' not found or has no config entries",
                HTTPStatus.NOT_FOUND,
                ERR_INTEGRATION_NOT_FOUND,
            )

        # Get registries
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        # Get integration info
        integrations_info = await async_get_integrations(hass, [domain])
        integration_info = integrations_info.get(domain)

        if integration_info and not isinstance(integration_info, Exception):
            name = integration_info.name
            documentation = f"https://www.home-assistant.io/integrations/{domain}"
        else:
            name = domain.replace("_", " ").title()
            documentation = None

        # Build config entries data
        config_entries_data = []
        for entry in entries:
            config_entries_data.append({
                "entry_id": entry.entry_id,
                "title": entry.title,
                "state": entry.state.value,
                "source": entry.source,
                "unique_id": entry.unique_id,
                "disabled_by": entry.disabled_by.value if entry.disabled_by else None,
            })

        # Get devices for this integration
        devices = []
        for device in device_registry.devices.values():
            if device.disabled:
                continue
            # Check if device belongs to this integration
            is_this_integration = False
            for identifier in device.identifiers:
                if isinstance(identifier, (tuple, list)) and len(identifier) >= 1:
                    if identifier[0] == domain:
                        is_this_integration = True
                        break
            if is_this_integration:
                devices.append({
                    "id": device.id,
                    "name": device.name_by_user or device.name,
                    "model": device.model,
                })

        # Count entities by domain for this integration
        entity_domains: dict[str, int] = {}
        for entity in entity_registry.entities.values():
            if entity.disabled:
                continue
            if entity.platform == domain:
                entity_domain = entity.entity_id.split(".")[0]
                entity_domains[entity_domain] = entity_domains.get(entity_domain, 0) + 1

        # Build response
        integration_data: dict[str, Any] = {
            "domain": domain,
            "name": name,
            "documentation": documentation,
            "config_entries": config_entries_data,
            "devices": sorted(devices, key=lambda x: (x.get("name") or "").lower()),
            "entity_domains": dict(sorted(entity_domains.items())),
            "device_count": len(devices),
            "entity_count": sum(entity_domains.values()),
        }

        return self.json(integration_data)
