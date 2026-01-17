"""HTTP views for service discovery REST API."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import API_BASE_PATH_SERVICES

_LOGGER = logging.getLogger(__name__)

# Error codes
ERR_SERVICE_NOT_FOUND = "service_not_found"
ERR_DOMAIN_NOT_FOUND = "domain_not_found"


class ServiceListView(HomeAssistantView):
    """View to list all services grouped by domain."""

    url = API_BASE_PATH_SERVICES
    name = "api:config_mcp:services"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list all services by domain.

        Returns:
            200: JSON object with domains as keys and service lists as values
        """
        hass: HomeAssistant = request.app["hass"]

        services_by_domain: dict[str, list[str]] = {}

        for domain in sorted(hass.services.async_services().keys()):
            services = list(hass.services.async_services()[domain].keys())
            services_by_domain[domain] = sorted(services)

        return self.json(services_by_domain)


class DomainServiceListView(HomeAssistantView):
    """View to list services for a specific domain."""

    url = API_BASE_PATH_SERVICES + "/{domain}"
    name = "api:config_mcp:services:domain"
    requires_auth = True

    async def get(self, request: web.Request, domain: str) -> web.Response:
        """Handle GET request - list services for a domain.

        Path params:
            domain: The service domain (e.g., 'light', 'climate')

        Returns:
            200: JSON array of service info for the domain
            404: Domain not found
        """
        hass: HomeAssistant = request.app["hass"]

        all_services = hass.services.async_services()
        if domain not in all_services:
            return self.json_message(
                f"Service domain '{domain}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DOMAIN_NOT_FOUND,
            )

        # Get service descriptions
        descriptions = await _get_service_descriptions(hass, domain)

        services = []
        for service_name in sorted(all_services[domain].keys()):
            service_info: dict[str, Any] = {
                "service": service_name,
                "domain": domain,
            }

            # Add description info if available
            if descriptions and service_name in descriptions:
                desc = descriptions[service_name]
                service_info["name"] = desc.get("name", service_name.replace("_", " ").title())
                service_info["description"] = desc.get("description", "")
                service_info["fields"] = list(desc.get("fields", {}).keys())

            services.append(service_info)

        return self.json(services)


class ServiceDetailView(HomeAssistantView):
    """View to get single service details."""

    url = API_BASE_PATH_SERVICES + "/{domain}/{service}"
    name = "api:config_mcp:service"
    requires_auth = True

    async def get(self, request: web.Request, domain: str, service: str) -> web.Response:
        """Handle GET request - get service details.

        Path params:
            domain: The service domain (e.g., 'light')
            service: The service name (e.g., 'turn_on')

        Returns:
            200: Service details with fields and parameters
            404: Service not found
        """
        hass: HomeAssistant = request.app["hass"]

        all_services = hass.services.async_services()
        if domain not in all_services:
            return self.json_message(
                f"Service domain '{domain}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_DOMAIN_NOT_FOUND,
            )

        if service not in all_services[domain]:
            return self.json_message(
                f"Service '{domain}.{service}' not found",
                HTTPStatus.NOT_FOUND,
                ERR_SERVICE_NOT_FOUND,
            )

        # Get service descriptions
        descriptions = await _get_service_descriptions(hass, domain)

        service_data: dict[str, Any] = {
            "domain": domain,
            "service": service,
        }

        if descriptions and service in descriptions:
            desc = descriptions[service]
            service_data["name"] = desc.get("name", service.replace("_", " ").title())
            service_data["description"] = desc.get("description", "")

            # Add target info if available
            if "target" in desc:
                service_data["target"] = desc["target"]

            # Add fields with full details
            fields = desc.get("fields", {})
            service_data["fields"] = {}
            for field_name, field_info in fields.items():
                field_data: dict[str, Any] = {
                    "name": field_info.get("name", field_name.replace("_", " ").title()),
                    "description": field_info.get("description", ""),
                }
                if "example" in field_info:
                    field_data["example"] = field_info["example"]
                if "default" in field_info:
                    field_data["default"] = field_info["default"]
                if "required" in field_info:
                    field_data["required"] = field_info["required"]
                if "selector" in field_info:
                    field_data["selector"] = field_info["selector"]
                if "advanced" in field_info:
                    field_data["advanced"] = field_info["advanced"]

                service_data["fields"][field_name] = field_data

        return self.json(service_data)


async def _get_service_descriptions(hass: HomeAssistant, domain: str) -> dict[str, Any] | None:
    """Get service descriptions for a domain.

    Args:
        hass: Home Assistant instance
        domain: Service domain

    Returns:
        Dictionary of service descriptions or None
    """
    try:
        from homeassistant.helpers.service import async_get_all_descriptions

        all_descriptions = await async_get_all_descriptions(hass)
        return all_descriptions.get(domain)
    except Exception as err:
        _LOGGER.debug("Could not get service descriptions for %s: %s", domain, err)
        return None
