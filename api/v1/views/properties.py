from django.db import models
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.v1.exceptions import APIError
from api.v1.pagination import StandardResultsSetPagination
from api.v1.permissions import IsStaffOperative
from api.v1.serializers.properties import (
    PropertyCreateSerializer,
    PropertyDetailSerializer,
    PropertyHistorySerializer,
    PropertyListSerializer,
    PropertyUpdateSerializer,
)
from pot.models import Property
from pot.services import property_service
from pot.services.property_service import PropertyServiceError


def _handle_service_error(exc):
    status_map = {
        'address_exists': status.HTTP_400_BAD_REQUEST,
        'address_required': status.HTTP_400_BAD_REQUEST,
    }
    raise APIError(
        exc.code,
        exc.message,
        status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
        details=exc.details,
    ) from exc


class PropertyViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStaffOperative]
    pagination_class = StandardResultsSetPagination
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        qs = Property.objects.all().order_by('-created_at')
        prop_status = self.request.query_params.get('status')
        if prop_status:
            qs = qs.filter(status=prop_status)
        prop_type = self.request.query_params.get('type')
        if prop_type:
            qs = qs.filter(type=prop_type)
        city = (self.request.query_params.get('city') or '').strip()
        if city:
            qs = qs.filter(city__icontains=city)
        search = (self.request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                models.Q(address__icontains=search)
                | models.Q(code__icontains=search)
                | models.Q(owner_name__icontains=search)
            )
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PropertyDetailSerializer
        if self.action == 'create':
            return PropertyCreateSerializer
        if self.action in ('partial_update', 'update'):
            return PropertyUpdateSerializer
        return PropertyListSerializer

    def create(self, request, *args, **kwargs):
        serializer = PropertyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            prop = property_service.crear_propiedad(request.user, **serializer.validated_data)
        except PropertyServiceError as exc:
            _handle_service_error(exc)
        return Response(PropertyDetailSerializer(prop).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        prop = self.get_object()
        serializer = PropertyUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data:
            return Response(PropertyDetailSerializer(prop).data)
        try:
            property_service.actualizar_propiedad(prop, request.user, **serializer.validated_data)
        except PropertyServiceError as exc:
            _handle_service_error(exc)
        prop.refresh_from_db()
        return Response(PropertyDetailSerializer(prop).data)

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        return Response(property_service.estadisticas_propiedades())

    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        prop = self.get_object()
        fecha_desde = request.query_params.get('date_from') or request.query_params.get('fecha_desde')
        fecha_hasta = request.query_params.get('date_to') or request.query_params.get('fecha_hasta')
        tipo_evento = request.query_params.get('event_type') or request.query_params.get('tipo_evento')
        tenant_id = request.query_params.get('tenant_id')
        if tenant_id:
            try:
                tenant_id = int(tenant_id)
            except (TypeError, ValueError):
                raise APIError(
                    'invalid_tenant_id',
                    'tenant_id debe ser un entero.',
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
        events = property_service.obtener_historial_filtrado(
            prop,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            tipo_evento=tipo_evento or None,
            tenant_id=tenant_id,
        )
        page = self.paginate_queryset(events)
        serializer = PropertyHistorySerializer(page if page is not None else events, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
