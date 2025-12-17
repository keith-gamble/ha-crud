"""Views for ha_crud component."""

from .areas import (
    AreaDetailView,
    AreaListView,
    FloorDetailView,
    FloorListView,
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
from .services import (
    DomainServiceListView,
    ServiceDetailView,
    ServiceListView,
)

__all__ = [
    # Dashboard views
    "DashboardListView",
    "DashboardDetailView",
    "DashboardConfigView",
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
]
