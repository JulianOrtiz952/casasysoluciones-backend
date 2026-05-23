from rest_framework.routers import DefaultRouter

from api.v1.views.properties import PropertyViewSet

router = DefaultRouter()
router.register(r'properties', PropertyViewSet, basename='v1-properties')

urlpatterns = router.urls
