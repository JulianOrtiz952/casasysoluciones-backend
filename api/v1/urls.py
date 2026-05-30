from django.urls import include, path

from api.v1.views.catalogs import CatalogView

urlpatterns = [
    path('auth/', include('api.v1.auth_urls')),
    path('admin/', include('api.v1.admin_urls')),
    path('', include('api.v1.user_urls')),
    path('', include('api.v1.property_urls')),
    path('', include('api.v1.inventory_urls')),
    path('', include('api.v1.contract_urls')),
    path('', include('api.v1.ticket_urls')),
    path('', include('api.v1.notification_urls')),
    path('', include('api.v1.report_urls')),
    path('catalogs/', CatalogView.as_view(), name='v1-catalogs'),
    path('legacy/', include('api.legacy_urls')),
    path('', include('api.legacy_urls')),
]
