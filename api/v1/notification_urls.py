from rest_framework.routers import DefaultRouter

from api.v1.views.notifications import NotificationViewSet

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='v1-notifications')

urlpatterns = router.urls
