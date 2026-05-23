from rest_framework import permissions

from pot.models import CustomUser


class IsAuthenticated(permissions.IsAuthenticated):
    pass


class IsAdmin(permissions.BasePermission):
    message = 'Solo administradores pueden realizar esta acción.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == CustomUser.Role.ADMIN)


class IsStaffOperative(permissions.BasePermission):
    message = 'Solo personal operativo (admin o asistente) puede realizar esta acción.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_staff_operative())


class IsTenant(permissions.BasePermission):
    message = 'Solo arrendatarios pueden realizar esta acción.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == CustomUser.Role.TENANT)


class IsStaffOperativeOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff_operative()
        )
