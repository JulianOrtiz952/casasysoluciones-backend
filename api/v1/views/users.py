from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from api.v1.exceptions import APIError
from api.v1.permissions import IsAdmin
from api.v1.serializers.users import (
    DeactivateSerializer,
    RoleChangeSerializer,
    TenantListSerializer,
    TenantPropertyAssociateSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserListSerializer,
    UserUpdateSerializer,
)
from pot.models import CustomUser, Property
from pot.services import user_service
from pot.services.user_service import UserServiceError


def _handle_service_error(exc):
    status_map = {
        'email_exists': status.HTTP_400_BAD_REQUEST,
        'document_exists': status.HTTP_400_BAD_REQUEST,
        'property_already_rented': status.HTTP_409_CONFLICT,
        'properties_required': status.HTTP_400_BAD_REQUEST,
        'invalid_properties': status.HTTP_400_BAD_REQUEST,
        'not_tenant': status.HTTP_400_BAD_REQUEST,
        'association_not_found': status.HTTP_404_NOT_FOUND,
        'already_inactive': status.HTTP_400_BAD_REQUEST,
        'email_immutable': status.HTTP_400_BAD_REQUEST,
    }
    raise APIError(
        exc.code,
        exc.message,
        status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
        details=exc.details,
    ) from exc


class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdmin]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        qs = CustomUser.objects.all().order_by('-created_at')
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role=role)
        active = self.request.query_params.get('active')
        if active == '1':
            qs = qs.filter(is_active=True)
        elif active == '0':
            qs = qs.filter(is_active=False)
        search = (self.request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                models.Q(email__icontains=search)
                | models.Q(first_name__icontains=search)
                | models.Q(last_name__icontains=search)
                | models.Q(document_number__icontains=search)
                | models.Q(public_code__icontains=search)
            )
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return UserDetailSerializer
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ('partial_update', 'update'):
            return UserUpdateSerializer
        return UserListSerializer

    def create(self, request, *args, **kwargs):
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        property_ids = data.pop('property_ids')
        try:
            user, _temp = user_service.crear_arrendatario(
                request.user,
                property_ids=property_ids,
                request=request,
                **data,
            )
        except UserServiceError as exc:
            _handle_service_error(exc)
        output = UserDetailSerializer(user)
        return Response(output.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        target = self.get_object()
        serializer = UserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            user_service.actualizar_usuario(target, request.user, **serializer.validated_data)
        except UserServiceError as exc:
            _handle_service_error(exc)
        return Response(UserDetailSerializer(target).data)

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        return Response(user_service.estadisticas_usuarios())

    @action(detail=True, methods=['patch'], url_path='role')
    def change_role(self, request, pk=None):
        target = self.get_object()
        serializer = RoleChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_role = serializer.validated_data['role']
        confirm = serializer.validated_data.get('confirm', False)

        if target.pk == request.user.pk and new_role != CustomUser.Role.ADMIN:
            raise APIError(
                'cannot_demote_self',
                'No puedes cambiar tu propio rol de administrador.',
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated, warning = user_service.cambiar_rol_usuario(
                target,
                new_role,
                request.user,
                confirm=confirm,
                request=request,
            )
        except UserServiceError as exc:
            _handle_service_error(exc)

        if warning:
            return Response(warning, status=status.HTTP_409_CONFLICT)

        return Response(UserDetailSerializer(updated).data)

    @action(detail=True, methods=['post'], url_path='deactivate')
    def deactivate(self, request, pk=None):
        target = self.get_object()
        if target.pk == request.user.pk:
            raise APIError(
                'cannot_deactivate_self',
                'No puedes desactivar tu propia cuenta.',
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        confirm = serializer.validated_data.get('confirm', False)

        try:
            updated, warning = user_service.desactivar_usuario(target, request.user, confirm=confirm)
        except UserServiceError as exc:
            _handle_service_error(exc)

        if warning:
            return Response(warning, status=status.HTTP_409_CONFLICT)

        return Response(UserDetailSerializer(updated).data)


class TenantViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdmin]
    serializer_class = TenantListSerializer

    def get_queryset(self):
        qs = CustomUser.objects.filter(role=CustomUser.Role.TENANT).order_by('-created_at')
        active = self.request.query_params.get('active')
        if active == '1':
            qs = qs.filter(is_active=True)
        elif active == '0':
            qs = qs.filter(is_active=False)
        search = (self.request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                models.Q(email__icontains=search)
                | models.Q(first_name__icontains=search)
                | models.Q(last_name__icontains=search)
                | models.Q(document_number__icontains=search)
            )
        return qs

    @action(detail=True, methods=['post'], url_path='properties')
    def associate_property(self, request, pk=None):
        tenant = self.get_object()
        serializer = TenantPropertyAssociateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        prop = get_object_or_404(Property, pk=serializer.validated_data['property_id'])
        try:
            user_service.asociar_inmueble_arrendatario(tenant, prop, request.user, request=request)
        except UserServiceError as exc:
            _handle_service_error(exc)
        return Response(TenantListSerializer(tenant).data, status=status.HTTP_200_OK)


class TenantPropertyDissociateView(APIView):
    permission_classes = [IsAdmin]

    def delete(self, request, tenant_id, property_id):
        tenant = get_object_or_404(CustomUser, pk=tenant_id, role=CustomUser.Role.TENANT)
        prop = get_object_or_404(Property, pk=property_id)
        try:
            user_service.desasociar_inmueble_arrendatario(tenant, prop, request.user)
        except UserServiceError as exc:
            _handle_service_error(exc)
        return Response(TenantListSerializer(tenant).data, status=status.HTTP_200_OK)
