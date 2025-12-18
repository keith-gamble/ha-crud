"""Views for Configuration MCP Server component."""

from .areas import (
    AreaDetailView,
    AreaListView,
    FloorDetailView,
    FloorListView,
)
from .automations import (
    AutomationDetailView,
    AutomationListView,
    AutomationTriggerView,
)
from .dashboards import (
    DashboardConfigView,
    DashboardDetailView,
    DashboardListView,
)
from .devices import (
    DeviceDetailView,
    DeviceListView,
)
from .entities import (
    DomainEntitiesView,
    DomainListView,
    EntityDetailView,
    EntityListView,
)
from .integrations import (
    IntegrationDetailView,
    IntegrationListView,
)
from .scenes import (
    SceneActivateView,
    SceneDetailView,
    SceneListView,
)
from .scripts import (
    ScriptDetailView,
    ScriptListView,
    ScriptRunView,
    ScriptStopView,
)
from .services import (
    DomainServiceListView,
    ServiceDetailView,
    ServiceListView,
)
from .resources import (
    ResourceListView,
)
from .logs import (
    LogErrorsView,
    LogListView,
)

__all__ = [
    # Dashboard views
    "DashboardListView",
    "DashboardDetailView",
    "DashboardConfigView",
    # Automation views
    "AutomationListView",
    "AutomationDetailView",
    "AutomationTriggerView",
    # Scene views
    "SceneListView",
    "SceneDetailView",
    "SceneActivateView",
    # Script views
    "ScriptListView",
    "ScriptDetailView",
    "ScriptRunView",
    "ScriptStopView",
    # Entity views
    "EntityListView",
    "EntityDetailView",
    "DomainListView",
    "DomainEntitiesView",
    # Device views
    "DeviceListView",
    "DeviceDetailView",
    # Area/Floor views
    "AreaListView",
    "AreaDetailView",
    "FloorListView",
    "FloorDetailView",
    # Integration views
    "IntegrationListView",
    "IntegrationDetailView",
    # Service views
    "ServiceListView",
    "DomainServiceListView",
    "ServiceDetailView",
    # Resource views (Lovelace custom cards)
    "ResourceListView",
    # Log views
    "LogListView",
    "LogErrorsView",
]
