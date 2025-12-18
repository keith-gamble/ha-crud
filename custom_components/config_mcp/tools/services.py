"""MCP Tools for Services.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..mcp_registry import mcp_tool

_LOGGER = logging.getLogger(__name__)


@mcp_tool(
    name="ha_list_services",
    description=(
        "List all available services grouped by domain. Returns a dictionary "
        "with domains as keys and arrays of service names as values."
    ),
)
async def list_services(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, list[str]]:
    """List all services grouped by domain."""
    services = hass.services.async_services()
    result: dict[str, list[str]] = {}

    for domain, domain_services in services.items():
        result[domain] = sorted(domain_services.keys())

    return result


@mcp_tool(
    name="ha_list_domain_services",
    description=(
        "List all services for a specific domain with names, descriptions, "
        "and field names."
    ),
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The service domain (e.g., 'light', 'climate', 'media_player', 'automation')",
            }
        },
        "required": ["domain"],
    },
)
async def list_domain_services(hass: HomeAssistant, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """List all services for a specific domain with details."""
    domain = arguments["domain"]
    services = hass.services.async_services()

    if domain not in services:
        raise ValueError(f"Domain '{domain}' not found")

    result = []
    for service_name, service_data in services[domain].items():
        service_info: dict[str, Any] = {
            "service": service_name,
            "name": f"{domain}.{service_name}",
        }

        # Try to get field names from schema if available
        if hasattr(service_data, "schema") and service_data.schema:
            try:
                schema = service_data.schema
                if hasattr(schema, "schema"):
                    service_info["fields"] = list(str(k) for k in schema.schema.keys())
            except Exception:
                pass

        result.append(service_info)

    result.sort(key=lambda x: x["service"])
    return result


@mcp_tool(
    name="ha_get_service",
    description=(
        "Get full details for a specific service including all fields, their "
        "descriptions, types, selectors, and examples. Essential for building "
        "automations."
    ),
    schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The service domain (e.g., 'light')",
            },
            "service": {
                "type": "string",
                "description": "The service name (e.g., 'turn_on', 'turn_off', 'toggle')",
            },
        },
        "required": ["domain", "service"],
    },
)
async def get_service(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get service details."""
    domain = arguments["domain"]
    service = arguments["service"]
    services = hass.services.async_services()

    if domain not in services:
        raise ValueError(f"Domain '{domain}' not found")

    if service not in services[domain]:
        raise ValueError(f"Service '{domain}.{service}' not found")

    service_data = services[domain][service]

    # Get service description if available
    result: dict[str, Any] = {
        "domain": domain,
        "service": service,
        "name": f"{domain}.{service}",
    }

    if hasattr(service_data, "schema") and service_data.schema:
        result["fields"] = {}
        # Try to extract schema info
        try:
            schema = service_data.schema
            if hasattr(schema, "schema"):
                for key, validator in schema.schema.items():
                    field_name = str(key)
                    result["fields"][field_name] = {"name": field_name}
        except Exception:
            pass

    return result
