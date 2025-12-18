"""HTTP views for log reading REST API."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from http import HTTPStatus
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import API_BASE_PATH_LOGS

_LOGGER = logging.getLogger(__name__)

# Default limits
DEFAULT_LOG_LIMIT = 100
MAX_LOG_LIMIT = 1000


class LogListView(HomeAssistantView):
    """View to list recent log entries."""

    url = API_BASE_PATH_LOGS
    name = "api:config_mcp:logs"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list recent log entries.

        Query params:
            level: Filter by log level (debug, info, warning, error, critical)
            source: Filter by source/logger name (substring match)
            limit: Maximum number of entries to return (default: 100, max: 1000)
            since: ISO timestamp to get logs since

        Returns:
            200: JSON array of log entries
        """
        hass: HomeAssistant = request.app["hass"]

        # Parse query parameters
        level_filter = request.query.get("level", "").lower()
        source_filter = request.query.get("source", "").lower()
        limit = min(int(request.query.get("limit", DEFAULT_LOG_LIMIT)), MAX_LOG_LIMIT)
        since_str = request.query.get("since")

        since_dt = None
        if since_str:
            try:
                since_dt = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
            except ValueError:
                return self.json_message(
                    "Invalid 'since' timestamp format. Use ISO format.",
                    HTTPStatus.BAD_REQUEST,
                    "invalid_timestamp",
                )

        # Get system log entries
        entries = await _get_log_entries(
            hass,
            level_filter=level_filter,
            source_filter=source_filter,
            limit=limit,
            since=since_dt,
        )

        return self.json({
            "count": len(entries),
            "entries": entries,
        })


class LogErrorsView(HomeAssistantView):
    """View to list only error/warning log entries."""

    url = API_BASE_PATH_LOGS + "/errors"
    name = "api:config_mcp:logs:errors"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - list error/warning log entries.

        Query params:
            source: Filter by source/logger name (substring match)
            limit: Maximum number of entries to return (default: 100, max: 1000)
            since: ISO timestamp to get logs since

        Returns:
            200: JSON array of error/warning log entries
        """
        hass: HomeAssistant = request.app["hass"]

        # Parse query parameters
        source_filter = request.query.get("source", "").lower()
        limit = min(int(request.query.get("limit", DEFAULT_LOG_LIMIT)), MAX_LOG_LIMIT)
        since_str = request.query.get("since")

        since_dt = None
        if since_str:
            try:
                since_dt = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
            except ValueError:
                return self.json_message(
                    "Invalid 'since' timestamp format. Use ISO format.",
                    HTTPStatus.BAD_REQUEST,
                    "invalid_timestamp",
                )

        # Get error/warning entries
        entries = await _get_log_entries(
            hass,
            level_filter=None,
            source_filter=source_filter,
            limit=limit,
            since=since_dt,
            errors_only=True,
        )

        return self.json({
            "count": len(entries),
            "entries": entries,
        })


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

            # The system_log stores entries in a deque
            if hasattr(system_log, "records"):
                records = list(system_log.records)
            elif isinstance(system_log, Mapping) and "records" in system_log:
                records = list(system_log["records"])
            else:
                # Try to get from the handler directly
                records = []
                for handler in logging.root.handlers:
                    if hasattr(handler, "records"):
                        records = list(handler.records)
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

                # Apply filters
                if errors_only and record.levelno < logging.WARNING:
                    continue

                if level_filter:
                    target_level = level_map.get(level_filter.lower())
                    if target_level and record.levelno != target_level:
                        continue

                if source_filter and source_filter not in record.name.lower():
                    continue

                # Get timestamp
                timestamp = datetime.fromtimestamp(record.created)
                if since and timestamp < since:
                    continue

                entry = {
                    "timestamp": timestamp.isoformat(),
                    "level": record.levelname,
                    "source": record.name,
                    "message": record.getMessage(),
                }

                # Add exception info if present
                if record.exc_info:
                    import traceback
                    entry["exception"] = "".join(
                        traceback.format_exception(*record.exc_info)
                    )

                entries.append(entry)

    except Exception as err:
        _LOGGER.warning("Could not get system log entries: %s", err)
        # Fall back to an empty list with a status message
        entries.append({
            "timestamp": datetime.now().isoformat(),
            "level": "WARNING",
            "source": "config_mcp.logs",
            "message": f"Could not retrieve system logs: {err}",
        })

    return entries
