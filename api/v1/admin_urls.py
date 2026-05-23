from django.urls import path

from api.v1.views.admin import ImportExcelView

urlpatterns = [
    path('import/excel/', ImportExcelView.as_view(), name='v1-admin-import-excel'),
]
