from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import InmuebleViewSet, InquilinoViewSet, HistorialAlquilerViewSet

router = DefaultRouter()
router.register(r'inmuebles', InmuebleViewSet)
router.register(r'inquilinos', InquilinoViewSet)
router.register(r'historial_alquiler', HistorialAlquilerViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
