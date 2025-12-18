"""MCP Tool Registry - Decorator-based tool registration.

This module provides a clean way for tools to self-register with their
metadata, eliminating the need for centralized tool definitions.

Usage:
    from .mcp_registry import mcp_tool, get_registered_tools, call_registered_tool

    @mcp_tool(
        name="ha_list_resources",
        description="List all Lovelace resources...",
        schema={
            "type": "object",
            "properties": {},
            "required": []
        },
        permission="dashboards_read"  # Optional permission check
    )
    async def list_resources(hass: HomeAssistant, arguments: dict) -> Any:
        # Implementation here
        return []
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Type alias for tool handlers
ToolHandler = Callable[[HomeAssistant, dict[str, Any]], Awaitable[Any]]


@dataclass
class ToolDefinition:
    """Definition of an MCP tool."""

    name: str
    description: str
    handler: ToolHandler
    schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
        "required": []
    })
    permission: str | None = None  # Optional permission key to check


# Global registry of tools
_TOOL_REGISTRY: dict[str, ToolDefinition] = {}


def mcp_tool(
    name: str,
    description: str,
    schema: dict[str, Any] | None = None,
    permission: str | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator to register a function as an MCP tool.

    Args:
        name: Unique tool name (e.g., "ha_list_dashboards")
        description: Human-readable description of what the tool does
        schema: JSON schema for input parameters
        permission: Optional permission key to check before execution

    Example:
        @mcp_tool(
            name="ha_list_dashboards",
            description="List all Lovelace dashboards",
            permission="dashboards_read"
        )
        async def list_dashboards(hass, arguments):
            return await _list_dashboards(hass)
    """
    def decorator(func: ToolHandler) -> ToolHandler:
        tool_def = ToolDefinition(
            name=name,
            description=description,
            handler=func,
            schema=schema or {"type": "object", "properties": {}, "required": []},
            permission=permission,
        )
        _TOOL_REGISTRY[name] = tool_def
        _LOGGER.debug("Registered MCP tool: %s", name)
        return func

    return decorator


def get_registered_tools() -> list[ToolDefinition]:
    """Get all registered tools.

    Returns:
        List of ToolDefinition objects
    """
    return list(_TOOL_REGISTRY.values())


def get_tool(name: str) -> ToolDefinition | None:
    """Get a specific tool by name.

    Args:
        name: Tool name

    Returns:
        ToolDefinition or None if not found
    """
    return _TOOL_REGISTRY.get(name)


async def call_tool(
    hass: HomeAssistant,
    name: str,
    arguments: dict[str, Any],
    check_permission: Callable[[HomeAssistant, str], bool] | None = None,
) -> Any:
    """Call a registered tool by name.

    Args:
        hass: Home Assistant instance
        name: Tool name
        arguments: Tool arguments
        check_permission: Optional function to check permissions

    Returns:
        Tool result

    Raises:
        ValueError: If tool not found
        PermissionError: If permission check fails
    """
    tool = _TOOL_REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"Unknown tool: {name}")

    # Check permission if required
    if tool.permission and check_permission:
        if not check_permission(hass, tool.permission):
            raise PermissionError(f"Permission '{tool.permission}' is disabled")

    return await tool.handler(hass, arguments)


def clear_registry() -> None:
    """Clear all registered tools. Useful for testing."""
    _TOOL_REGISTRY.clear()


def tool_count() -> int:
    """Get the number of registered tools."""
    return len(_TOOL_REGISTRY)
