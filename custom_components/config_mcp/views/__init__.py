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
    EntityUsageView,
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
from .categories import (
    CategoryDetailView,
    CategoryScopeListView,
    LabelDetailView,
    LabelListView,
)
from .helpers import (
    HelperDetailView,
    HelperListView,
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
    "EntityUsageView",
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
    # Category/Label views
    "CategoryScopeListView",
    "CategoryDetailView",
    "LabelListView",
    "LabelDetailView",
    # Helper views
    "HelperListView",
    "HelperDetailView",
]
