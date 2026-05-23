from django.urls import path
from rest_framework.routers import DefaultRouter

from api.v1.views.users import TenantPropertyDissociateView, TenantViewSet, UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='v1-users')
router.register(r'tenants', TenantViewSet, basename='v1-tenants')

urlpatterns = router.urls + [
    path(
        'tenants/<int:tenant_id>/properties/<int:property_id>/',
        TenantPropertyDissociateView.as_view(),
        name='v1-tenant-property-dissociate',
    ),
]
