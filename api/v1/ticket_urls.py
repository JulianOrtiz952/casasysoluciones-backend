from rest_framework.routers import DefaultRouter

from api.v1.views.tickets import TenantTicketViewSet

router = DefaultRouter()
router.register(r'tickets/mine', TenantTicketViewSet, basename='v1-tickets-mine')
router.register(r'tickets', TenantTicketViewSet, basename='v1-tickets')

urlpatterns = router.urls
