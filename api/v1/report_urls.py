from django.urls import path

from api.v1.views.reports import (
    GlobalSearchView,
    PropertiesWithOpenTicketsView,
    PropertyRepairHistoryView,
    ReportSummaryView,
    ReportsExportExcelView,
    TenantsWithActiveTicketsView,
    TicketTrafficLightView,
)

urlpatterns = [
    path(
        'reports/ticket-traffic-light/',
        TicketTrafficLightView.as_view(),
        name='v1-reports-ticket-traffic-light',
    ),
    path('reports/summary/', ReportSummaryView.as_view(), name='v1-reports-summary'),
    path(
        'reports/properties-with-open-tickets/',
        PropertiesWithOpenTicketsView.as_view(),
        name='v1-reports-properties-open-tickets',
    ),
    path(
        'reports/tenants-with-active-tickets/',
        TenantsWithActiveTicketsView.as_view(),
        name='v1-reports-tenants-active-tickets',
    ),
    path(
        'reports/properties/<int:property_id>/repair-history/',
        PropertyRepairHistoryView.as_view(),
        name='v1-reports-property-repair-history',
    ),
    path(
        'reports/export/excel/',
        ReportsExportExcelView.as_view(),
        name='v1-reports-export-excel',
    ),
    path('search/', GlobalSearchView.as_view(), name='v1-global-search'),
]
