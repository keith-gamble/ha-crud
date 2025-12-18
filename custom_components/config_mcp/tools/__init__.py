"""MCP Tools Package.

This package contains all MCP tool implementations. Each module in this
package can define tools using the @mcp_tool decorator, and they will
be automatically discovered and registered.

Structure:
    tools/
    ├── __init__.py      # Auto-discovery logic
    ├── dashboards.py    # Dashboard tools
    ├── resources.py     # Lovelace resource tools
    ├── entities.py      # Entity discovery tools
    ├── devices.py       # Device discovery tools
    ├── areas.py         # Area/Floor tools
    ├── integrations.py  # Integration tools
    ├── services.py      # Service tools
    ├── automations.py   # Automation CRUD tools
    ├── scripts.py       # Script CRUD tools
    └── scenes.py        # Scene CRUD tools

Usage:
    # In mcp_server.py or __init__.py:
    from .tools import register_all_tools

    # This imports all tool modules, triggering @mcp_tool decorators
    register_all_tools()
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# List of tool modules to load (in order)
TOOL_MODULES = [
    "dashboards",
    "resources",
    "entities",
    "devices",
    "areas",
    "integrations",
    "services",
    "automations",
    "scripts",
    "scenes",
    "logs",
]


def register_all_tools() -> int:
    """Import all tool modules to trigger @mcp_tool registration.

    Returns:
        Number of tools registered
    """
    from ..mcp_registry import tool_count

    initial_count = tool_count()

    for module_name in TOOL_MODULES:
        try:
            importlib.import_module(f".{module_name}", package=__name__)
            _LOGGER.debug("Loaded tool module: %s", module_name)
        except ImportError as err:
            _LOGGER.debug("Tool module not found (optional): %s - %s", module_name, err)
        except Exception as err:
            _LOGGER.warning("Error loading tool module %s: %s", module_name, err)

    final_count = tool_count()
    _LOGGER.info("Registered %d MCP tools", final_count - initial_count)

    return final_count - initial_count


def discover_tool_modules() -> list[str]:
    """Auto-discover all Python modules in the tools directory.

    Returns:
        List of module names found
    """
    tools_dir = Path(__file__).parent
    modules = []

    for file in tools_dir.glob("*.py"):
        if file.name.startswith("_"):
            continue
        modules.append(file.stem)

    return sorted(modules)
