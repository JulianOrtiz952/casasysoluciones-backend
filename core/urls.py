"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenRefreshView

from api.views import CustomTokenObtainPairView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('pot.urls')),
    path('api/v1/', include('api.v1.urls')),
    path('api/v1/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema-i1'),
    path('api/v1/schema/swagger/', SpectacularSwaggerView.as_view(url_name='schema-i1'), name='swagger-i1'),
    path('api/v1/schema/redoc/', SpectacularRedocView.as_view(url_name='schema-i1'), name='redoc-i1'),
]

if settings.DEBUG and getattr(settings, 'MEDIA_ROOT', None):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
