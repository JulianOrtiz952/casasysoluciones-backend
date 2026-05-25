from rest_framework.routers import DefaultRouter

from api.v1.views.tickets import StaffTicketViewSet, TenantTicketViewSet

tenant_router = DefaultRouter()
tenant_router.register(r'tickets/mine', TenantTicketViewSet, basename='v1-tickets-mine')

staff_router = DefaultRouter()
staff_router.register(r'tickets', StaffTicketViewSet, basename='v1-tickets')

# Rutas tenant antes que staff para que /tickets/mine/ no se interprete como pk=mine
urlpatterns = tenant_router.urls + staff_router.urls
