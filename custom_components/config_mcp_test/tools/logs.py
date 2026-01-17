"""MCP Tools for Log Reading.

Each tool registers itself using the @mcp_tool decorator.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import CONF_LOGS_READ
from ..mcp_registry import mcp_tool

_LOGGER = logging.getLogger(__name__)

# Default limits
DEFAULT_LOG_LIMIT = 100
MAX_LOG_LIMIT = 1000


@mcp_tool(
    name="ha_get_logs",
    description=(
        "Get recent Home Assistant log entries. Useful for debugging and verifying "
        "that configuration changes (automations, scripts, etc.) are working correctly. "
        "Returns timestamped log entries with level, source, and message."
    ),
    schema={
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "description": "Filter by log level: 'debug', 'info', 'warning', 'error', or 'critical'",
                "enum": ["debug", "info", "warning", "error", "critical"],
            },
            "source": {
                "type": "string",
                "description": "Filter by source/logger name (substring match, e.g., 'automation', 'script', 'homeassistant.components.light')",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of entries to return (default: 100, max: 1000)",
                "default": 100,
                "minimum": 1,
                "maximum": 1000,
            },
            "since": {
                "type": "string",
                "description": "ISO timestamp to get logs since (e.g., '2024-01-15T10:30:00')",
            },
        },
        "required": [],
    },
    permission=CONF_LOGS_READ,
)
async def get_logs(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get recent log entries from Home Assistant."""
    level_filter = arguments.get("level", "").lower() if arguments.get("level") else None
    source_filter = arguments.get("source", "").lower() if arguments.get("source") else None
    limit = min(int(arguments.get("limit", DEFAULT_LOG_LIMIT)), MAX_LOG_LIMIT)
    since_str = arguments.get("since")

    since_dt = None
    if since_str:
        try:
            since_dt = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid 'since' timestamp format: {since_str}. Use ISO format.")

    entries = await _get_log_entries(
        hass,
        level_filter=level_filter,
        source_filter=source_filter,
        limit=limit,
        since=since_dt,
    )

    return {
        "count": len(entries),
        "entries": entries,
    }


@mcp_tool(
    name="ha_get_error_logs",
    description=(
        "Get recent Home Assistant error and warning log entries. A quick way to check "
        "for problems after making configuration changes. Returns only WARNING, ERROR, "
        "and CRITICAL level entries."
    ),
    schema={
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Filter by source/logger name (substring match, e.g., 'automation', 'script')",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of entries to return (default: 100, max: 1000)",
                "default": 100,
                "minimum": 1,
                "maximum": 1000,
            },
            "since": {
                "type": "string",
                "description": "ISO timestamp to get logs since (e.g., '2024-01-15T10:30:00')",
            },
        },
        "required": [],
    },
    permission=CONF_LOGS_READ,
)
async def get_error_logs(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    """Get recent error/warning log entries."""
    source_filter = arguments.get("source", "").lower() if arguments.get("source") else None
    limit = min(int(arguments.get("limit", DEFAULT_LOG_LIMIT)), MAX_LOG_LIMIT)
    since_str = arguments.get("since")

    since_dt = None
    if since_str:
        try:
            since_dt = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid 'since' timestamp format: {since_str}. Use ISO format.")

    entries = await _get_log_entries(
        hass,
        level_filter=None,
        source_filter=source_filter,
        limit=limit,
        since=since_dt,
        errors_only=True,
    )

    return {
        "count": len(entries),
        "entries": entries,
    }


async def _get_log_entries(
    hass: HomeAssistant,
    level_filter: str | None = None,
    source_filter: str | None = None,
    limit: int = DEFAULT_LOG_LIMIT,
    since: datetime | None = None,
    errors_only: bool = False,
) -> list[dict[str, Any]]:
    """Get log entries from the system log.

    Args:
        hass: Home Assistant instance
        level_filter: Filter by specific log level
        source_filter: Filter by source (substring match)
        limit: Maximum entries to return
        since: Only entries after this timestamp
        errors_only: If True, only return warning/error/critical

    Returns:
        List of log entry dictionaries
    """
    entries: list[dict[str, Any]] = []

    # Try to access system_log component
    try:
        from homeassistant.components.system_log import DOMAIN as SYSTEM_LOG_DOMAIN

        if SYSTEM_LOG_DOMAIN in hass.data:
            system_log = hass.data[SYSTEM_LOG_DOMAIN]

            # The system_log handler stores entries in a DedupStore (OrderedDict)
            # Access via .records.to_list() or .records.values()
            if hasattr(system_log, "records"):
                store = system_log.records
                if hasattr(store, "to_list"):
                    # to_list() returns dicts, but we need the values for filtering
                    records = list(store.values())
                elif hasattr(store, "values"):
                    records = list(store.values())
                else:
                    records = list(store)
            elif isinstance(system_log, Mapping) and "records" in system_log:
                records = list(system_log["records"].values() if hasattr(system_log["records"], "values") else system_log["records"])
            else:
                # Try to get from the handler directly
                records = []
                for handler in logging.root.handlers:
                    if hasattr(handler, "records"):
                        store = handler.records
                        if hasattr(store, "values"):
                            records = list(store.values())
                        else:
                            records = list(store)
                        break

            # Level mapping
            level_map = {
                "debug": logging.DEBUG,
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
                "critical": logging.CRITICAL,
            }

            for record in reversed(records):
                if len(entries) >= limit:
                    break

                # Handle different record types:
                # - logging.LogRecord: has levelno (int), levelname, getMessage(), created, exc_info
                # - HA LogEntry: has level (str), name, message (deque), timestamp, exception
                if hasattr(record, "levelno"):
                    # logging.LogRecord format
                    level_no = record.levelno
                    level_name = record.levelname
                    source = record.name
                    message = record.getMessage()
                    timestamp = datetime.fromtimestamp(record.created)
                    exc_text = None
                    if record.exc_info:
                        import traceback
                        exc_text = "".join(traceback.format_exception(*record.exc_info))
                elif hasattr(record, "level") and hasattr(record, "message"):
                    # Home Assistant LogEntry format (from system_log)
                    level_name = record.level
                    level_no = level_map.get(level_name.lower(), 0)
                    source = record.name
                    # message is a deque of strings, join them
                    if hasattr(record.message, "__iter__") and not isinstance(record.message, str):
                        message = " | ".join(str(m) for m in record.message)
                    else:
                        message = str(record.message)
                    # timestamp may be a float (unix timestamp) or datetime
                    raw_ts = record.timestamp if hasattr(record, "timestamp") else None
                    if isinstance(raw_ts, (int, float)):
                        timestamp = datetime.fromtimestamp(raw_ts)
                    elif isinstance(raw_ts, datetime):
                        timestamp = raw_ts
                    else:
                        timestamp = datetime.now()
                    exc_text = record.exception if hasattr(record, "exception") else None
                else:
                    # Unknown format, skip
                    continue

                # Apply filters
                if errors_only and level_no < logging.WARNING:
                    continue

                if level_filter:
                    target_level = level_map.get(level_filter.lower())
                    if target_level and level_no != target_level:
                        continue

                if source_filter and source_filter not in source.lower():
                    continue

                if since and timestamp < since:
                    continue

                entry = {
                    "timestamp": timestamp.isoformat(),
                    "level": level_name,
                    "source": source,
                    "message": message,
                }

                # Add exception info if present
                if exc_text:
                    entry["exception"] = exc_text

                entries.append(entry)

    except Exception as err:
        _LOGGER.warning("Could not get system log entries: %s", err)
        # Return an error entry to indicate the problem
        entries.append({
            "timestamp": datetime.now().isoformat(),
            "level": "WARNING",
            "source": "config_mcp.logs",
            "message": f"Could not retrieve system logs: {err}",
        })

    return entries
