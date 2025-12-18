"""Custom exceptions for Configuration MCP Server component."""

from homeassistant.exceptions import HomeAssistantError


class DashboardNotFoundError(HomeAssistantError):
    """Raised when dashboard is not found."""

    def __init__(self, dashboard_id: str) -> None:
        """Initialize exception."""
        super().__init__(f"Dashboard '{dashboard_id}' not found")
        self.dashboard_id = dashboard_id


class DashboardExistsError(HomeAssistantError):
    """Raised when dashboard already exists."""

    def __init__(self, dashboard_id: str) -> None:
        """Initialize exception."""
        super().__init__(f"Dashboard '{dashboard_id}' already exists")
        self.dashboard_id = dashboard_id


class DashboardReadOnlyError(HomeAssistantError):
    """Raised when attempting to modify a YAML dashboard."""

    def __init__(self, dashboard_id: str) -> None:
        """Initialize exception."""
        super().__init__(f"Dashboard '{dashboard_id}' is YAML-based and read-only")
        self.dashboard_id = dashboard_id


class InvalidConfigError(HomeAssistantError):
    """Raised when dashboard configuration is invalid."""

    def __init__(self, message: str) -> None:
        """Initialize exception."""
        super().__init__(message)
