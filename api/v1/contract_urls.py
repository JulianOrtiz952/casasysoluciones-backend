from rest_framework.routers import DefaultRouter

from api.v1.views.contracts import ContractViewSet

router = DefaultRouter()
router.register(r'contracts', ContractViewSet, basename='v1-contracts')

urlpatterns = router.urls
