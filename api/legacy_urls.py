from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ChangePasswordView,
    HistorialAlquilerViewSet,
    InmuebleViewSet,
    InquilinoViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register(r'inmuebles', InmuebleViewSet)
router.register(r'inquilinos', InquilinoViewSet)
router.register(r'historial_alquiler', HistorialAlquilerViewSet)
router.register(r'usuarios', UserViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change_password'),
]
