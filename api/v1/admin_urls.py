from django.urls import path

from api.v1.views.admin import ImportExcelView
from api.v1.views.dashboard import DashboardStatsView

urlpatterns = [
    path('import/excel/', ImportExcelView.as_view(), name='v1-admin-import-excel'),
    path('dashboard-stats/', DashboardStatsView.as_view(), name='v1-admin-dashboard-stats'),
]
