"""MCP Server implementation for Configuration MCP Server component.

This module provides an MCP (Model Context Protocol) server that exposes
the config_mcp API functionality as MCP tools, allowing AI assistants to
interact directly with Home Assistant dashboards, entities, devices, etc.

Tools are registered using the @mcp_tool decorator in the tools/ package,
making it easy to add new tools without modifying this file.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_OPTIONS,
    DOMAIN,
    MCP_SERVER_NAME,
)
from .mcp_registry import get_registered_tools, call_tool as registry_call_tool

_LOGGER = logging.getLogger(__name__)


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
        for entry_id in hass.data[DOMAIN]:
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


def create_mcp_server(hass: HomeAssistant) -> Server:
    """Create and configure the MCP server with all registered tools.

    This version uses the tool registry - tools self-register using the
    @mcp_tool decorator in the tools/ package.

    Note: Tools are pre-registered at component startup (in async_setup_entry)
    to avoid blocking the event loop. This function just uses them.

    Args:
        hass: Home Assistant instance

    Returns:
        Configured MCP Server instance
    """
    from .mcp_registry import tool_count as get_tool_count

    # Tools should already be registered at startup, just log the count
    current_count = get_tool_count()
    if current_count == 0:
        # Fallback: if tools weren't pre-registered, do it now (will trigger warning)
        _LOGGER.warning("MCP tools were not pre-registered, registering now (may block)")
        from .tools import register_all_tools
        current_count = register_all_tools()

    _LOGGER.debug("MCP server using %d registered tools", current_count)

    server = Server(MCP_SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return list of available tools from the registry."""
        tools = []
        for tool_def in get_registered_tools():
            tools.append(Tool(
                name=tool_def.name,
                description=tool_def.description,
                inputSchema=tool_def.schema,
            ))
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle tool calls using the registry."""
        try:
            result = await registry_call_tool(
                hass=hass,
                name=name,
                arguments=arguments,
                check_permission=check_permission,
            )
            return [TextContent(type="text", text=json.dumps(result, default=str))]
        except PermissionError as e:
            _LOGGER.warning("Permission denied for MCP tool %s: %s", name, e)
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
        except ValueError as e:
            _LOGGER.warning("Invalid request for MCP tool %s: %s", name, e)
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
        except Exception as e:
            _LOGGER.exception("Error handling MCP tool call %s: %s", name, e)
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    return server
