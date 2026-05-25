from rest_framework.routers import DefaultRouter

from api.v1.views.inventories import InventoryViewSet

router = DefaultRouter()
router.register(r'inventories', InventoryViewSet, basename='v1-inventories')
router.register(r'inventarios', InventoryViewSet, basename='v1-inventarios-es')

urlpatterns = router.urls
