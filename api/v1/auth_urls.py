from django.urls import path

from api.v1.views.auth import (
    FirstPasswordChangeView,
    LoginView,
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RefreshView,
)

urlpatterns = [
    path('login/', LoginView.as_view(), name='v1-auth-login'),
    path('refresh/', RefreshView.as_view(), name='v1-auth-refresh'),
    path('logout/', LogoutView.as_view(), name='v1-auth-logout'),
    path('me/', MeView.as_view(), name='v1-auth-me'),
    path('reset/', PasswordResetRequestView.as_view(), name='v1-auth-reset'),
    path('reset/confirm/', PasswordResetConfirmView.as_view(), name='v1-auth-reset-confirm'),
    path('first-change/', FirstPasswordChangeView.as_view(), name='v1-auth-first-change'),
]
