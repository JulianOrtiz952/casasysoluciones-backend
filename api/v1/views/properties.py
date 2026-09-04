from django.db import models
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action
from rest_framework.response import Response

from api.v1.exceptions import APIError
from api.v1.pagination import StandardResultsSetPagination
from api.v1.permissions import IsStaffOperative, IsStaffOperativeOrReadOnly
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
    pagination_class = StandardResultsSetPagination
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_permissions(self):
        if self.action == 'mine':
            return [IsAuthenticated()]
        if self.action in ('list', 'retrieve'):
            if not self.request.user or not self.request.user.is_authenticated:
                return [AllowAny()]
        return [IsStaffOperative()]

    def get_queryset(self):
        if not self.request.user or not self.request.user.is_authenticated:
            qs = Property.objects.filter(status=Property.Status.AVAILABLE, is_active=True).order_by('-created_at')
        else:
            qs = Property.objects.all().order_by('-created_at')
            if self.action == 'list':
                include_inactive = self.request.query_params.get('include_inactive', '').lower() in ('1', 'true', 'yes')
                if not include_inactive:
                    qs = qs.filter(is_active=True)
            
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
        validated_data = serializer.validated_data
        images = request.FILES.getlist('images')
        if images:
            validated_data['images'] = images
        try:
            prop = property_service.crear_propiedad(request.user, **validated_data)
        except PropertyServiceError as exc:
            _handle_service_error(exc)
        return Response(PropertyDetailSerializer(prop).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        prop = self.get_object()
        serializer = PropertyUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        images = request.FILES.getlist('images')
        if images:
            validated_data['images'] = images

        if hasattr(request.data, 'getlist'):
            deleted_ids_raw = request.data.getlist('deleted_image_ids') or request.data.get('deleted_image_ids')
        elif hasattr(request.data, 'get'):
            deleted_ids_raw = request.data.get('deleted_image_ids')
        else:
            deleted_ids_raw = None

        if deleted_ids_raw:
            clean_ids = []
            if isinstance(deleted_ids_raw, str):
                import json
                try:
                    parsed = json.loads(deleted_ids_raw)
                    if isinstance(parsed, list):
                        clean_ids = [int(x) for x in parsed]
                except Exception:
                    clean_ids = [int(x) for x in deleted_ids_raw.split(',') if str(x).strip().isdigit()]
            elif isinstance(deleted_ids_raw, list):
                for item in deleted_ids_raw:
                    if isinstance(item, int):
                        clean_ids.append(item)
                    elif isinstance(item, str) and str(item).isdigit():
                        clean_ids.append(int(item))
            if clean_ids:
                validated_data['deleted_image_ids'] = clean_ids

        set_cover_id = request.data.get('set_cover_image_id') if hasattr(request.data, 'get') else None
        if set_cover_id and str(set_cover_id).isdigit():
            validated_data['set_cover_image_id'] = int(set_cover_id)

        # Check validation: cannot deactivate if there is an active tenant
        if 'is_active' in validated_data and not validated_data['is_active']:
            if prop.get_active_tenant() is not None:
                raise APIError(
                    'cannot_deactivate_rented_property',
                    'No se puede desactivar un inmueble con un arrendatario activo.',
                    status_code=status.HTTP_400_BAD_REQUEST
                )
                
        try:
            property_service.actualizar_propiedad(prop, request.user, **validated_data)
        except PropertyServiceError as exc:
            _handle_service_error(exc)
        prop.refresh_from_db()
        return Response(PropertyDetailSerializer(prop).data)

    @action(detail=True, methods=['post'], url_path='images')
    def upload_images(self, request, pk=None):
        prop = self.get_object()
        images = request.FILES.getlist('images') or request.FILES.getlist('image')
        if not images:
            raise APIError('no_images_provided', 'No se proporcionaron imágenes.', status_code=status.HTTP_400_BAD_REQUEST)
        try:
            property_service.agregar_imagenes(prop, images)
        except PropertyServiceError as exc:
            _handle_service_error(exc)
        prop.refresh_from_db()
        return Response(PropertyDetailSerializer(prop).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], url_path=r'images/(?P<image_id>\d+)')
    def delete_image(self, request, pk=None, image_id=None):
        prop = self.get_object()
        try:
            property_service.eliminar_imagen(prop, image_id)
        except PropertyServiceError as exc:
            _handle_service_error(exc)
        prop.refresh_from_db()
        return Response(PropertyDetailSerializer(prop).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path=r'images/(?P<image_id>\d+)/set_cover')
    def set_cover_image(self, request, pk=None, image_id=None):
        prop = self.get_object()
        try:
            property_service.establecer_portada(prop, image_id)
        except PropertyServiceError as exc:
            _handle_service_error(exc)
        prop.refresh_from_db()
        return Response(PropertyDetailSerializer(prop).data, status=status.HTTP_200_OK)

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

    @action(detail=False, methods=['get'], url_path='mine', permission_classes=[IsAuthenticated])
    def mine(self, request):
        user = request.user
        if user.role == 'TENANT':
            qs = Property.objects.filter(
                tenant_associations__user=user,
                tenant_associations__dissociated_at__isnull=True
            ).distinct().order_by('-created_at')
        else:
            qs = Property.objects.all().order_by('-created_at')
        
        serializer = PropertyListSerializer(qs, many=True)
        return Response(serializer.data)
