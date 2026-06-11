from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.v1.exceptions import APIError
from api.v1.pagination import StandardResultsSetPagination
from api.v1.permissions import CanAccessInventory, IsAdmin, IsStaffOperative, IsTenant
from api.v1.serializers.inventories import (
    InventoryCreateSerializer,
    InventoryDetailSerializer,
    InventoryListSerializer,
    InventoryObservationSerializer,
    InventoryPhotoUploadSerializer,
    InventorySpaceBulkSerializer,
    InventorySpaceCreateSerializer,
    InventoryStep1Serializer,
    SpaceTemplateQuerySerializer,
)
from pot.models import CustomUser, Inventory, InventorySpace, InventorySpacePhoto
from pot.services import inventory_service
from pot.services.inventory_service import InventoryServiceError


def _handle_service_error(exc):
    status_map = {
        'property_not_found': status.HTTP_404_NOT_FOUND,
        'tenant_not_found': status.HTTP_404_NOT_FOUND,
        'not_owner': status.HTTP_403_FORBIDDEN,
        'initial_already_accepted': status.HTTP_409_CONFLICT,
        'tenant_not_associated': status.HTTP_400_BAD_REQUEST,
        'duplicate_inventory': status.HTTP_409_CONFLICT,
        'not_editable': status.HTTP_400_BAD_REQUEST,
        'invalid_status': status.HTTP_400_BAD_REQUEST,
        'spaces_required': status.HTTP_400_BAD_REQUEST,
        'incomplete_review': status.HTTP_400_BAD_REQUEST,
        'invalid_property_type': status.HTTP_400_BAD_REQUEST,
        'invalid_image': status.HTTP_400_BAD_REQUEST,
    }
    raise APIError(
        exc.code,
        exc.message,
        status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
        details=exc.details,
    ) from exc


class InventoryViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    pagination_class = StandardResultsSetPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = Inventory.objects.select_related('property', 'tenant').prefetch_related(
            'spaces__photos',
            'tenant_observations',
        )
        if self.request.user.is_staff_operative() or self.request.user.role == CustomUser.Role.TECHNICIAN:
            inv_type = self.request.query_params.get('type') or self.request.query_params.get('inventory_type')
            if inv_type:
                qs = qs.filter(inventory_type=inv_type)
            inv_status = self.request.query_params.get('status')
            if inv_status:
                qs = qs.filter(status=inv_status)
            property_id = self.request.query_params.get('property_id')
            if property_id:
                qs = qs.filter(property_id=property_id)
            tenant_id = self.request.query_params.get('tenant_id')
            if tenant_id:
                qs = qs.filter(tenant_id=tenant_id)
            return qs.order_by('-created_at')
        if self.request.user.role == CustomUser.Role.TENANT:
            return qs.filter(tenant=self.request.user).order_by('-created_at')
        return qs.none()

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return InventoryDetailSerializer
        return InventoryListSerializer

    def get_permissions(self):
        if self.action in ('mine', 'sign', 'observations'):
            return [IsAuthenticated(), IsTenant()]
        if self.action in (
            'create',
            'finalize',
            'save_draft',
            'update_step_1',
            'replace_spaces',
            'add_space',
            'delete_space',
            'upload_photo',
            'delete_photo',
            'resolve_observations',
        ):
            return [IsAuthenticated(), IsStaffOperative()]
        if self.action == 'space_templates':
            return [IsAuthenticated()]
        if self.action in ('pdf',):
            return [IsAuthenticated(), CanAccessInventory()]
        if self.action == 'list':
            return [IsAuthenticated()]
        if self.action == 'retrieve':
            return [IsAuthenticated(), CanAccessInventory()]
        return [IsAuthenticated()]

    def list(self, request, *args, **kwargs):
        if not request.user.is_staff_operative() and request.user.role != CustomUser.Role.TENANT:
            raise APIError('forbidden', 'Sin permiso.', status_code=status.HTTP_403_FORBIDDEN)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self.check_object_permissions(request, instance)
        return Response(InventoryDetailSerializer(instance).data)

    @action(detail=False, methods=['get'], url_path='mine')
    def mine(self, request):
        qs = Inventory.objects.filter(
            tenant=request.user,
            status=Inventory.Status.PENDING_SIGNATURE,
        ).select_related('property').order_by('-created_at')
        serializer = InventoryListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='space-templates')
    def space_templates(self, request):
        ser = SpaceTemplateQuerySerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        try:
            templates = inventory_service.obtener_plantillas_espacios(ser.validated_data['property_type'])
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        return Response({'property_type': ser.validated_data['property_type'], 'spaces': templates})

    def create(self, request):
        if not request.user.is_staff_operative():
            raise APIError('forbidden', 'Sin permiso.', status_code=status.HTTP_403_FORBIDDEN)
        serializer = InventoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            inv = inventory_service.crear_inventario_inicial(
                request.user,
                property_id=data['property_id'],
                tenant_id=data['tenant_id'],
                delivery_date=data['delivery_date'],
                observations=data.get('observations'),
                inventory_type=data.get('inventory_type', Inventory.Type.INITIAL),
            )
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        return Response(InventoryDetailSerializer(inv).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'], url_path='step/1')
    def update_step_1(self, request, pk=None):
        inv = self.get_object()
        serializer = InventoryStep1Serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            inventory_service.actualizar_paso_1(inv, **serializer.validated_data)
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        return Response(InventoryDetailSerializer(inv).data)

    @action(detail=True, methods=['put'], url_path='step/2/spaces')
    def replace_spaces(self, request, pk=None):
        inv = self.get_object()
        serializer = InventorySpaceBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            inventory_service.reemplazar_espacios(inv, serializer.validated_data['spaces'])
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        return Response(InventoryDetailSerializer(inv).data)

    @action(detail=True, methods=['post'], url_path='save-draft')
    def save_draft(self, request, pk=None):
        inv = self.get_object()
        try:
            inventory_service.guardar_borrador(inv)
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        return Response(InventoryDetailSerializer(inv).data)

    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        inv = self.get_object()
        try:
            inventory_service.finalizar_inventario(inv, request)
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        return Response(InventoryDetailSerializer(inv).data)

    @action(detail=True, methods=['post'], url_path='resolve-observations')
    def resolve_observations(self, request, pk=None):
        inv = self.get_object()
        if request.user.role != CustomUser.Role.ADMIN:
            raise APIError('forbidden', 'Solo administradores pueden resolver observaciones.', status_code=status.HTTP_403_FORBIDDEN)
        try:
            inventory_service.resolver_observaciones(inv, request)
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        return Response(InventoryDetailSerializer(inv).data)

    @action(detail=True, methods=['post'])
    def sign(self, request, pk=None):
        inv = get_object_or_404(Inventory, pk=pk)
        if inv.tenant_id != request.user.pk:
            raise APIError('not_owner', 'No es su inventario.', status_code=status.HTTP_403_FORBIDDEN)
        try:
            inventory_service.firmar_inventario(inv, request.user, request)
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        return Response(InventoryDetailSerializer(inv).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        user = request.user
        if not user.is_staff_operative() and user.role != CustomUser.Role.ADMIN:
            raise APIError('forbidden', 'Solo personal administrativo puede aprobar este inventario.', status_code=status.HTTP_403_FORBIDDEN)
        
        inv = get_object_or_404(Inventory, pk=pk)
        if inv.inventory_type != Inventory.Type.FINAL:
            raise APIError('invalid_type', 'Solo se pueden aprobar inventarios de tipo FINAL.', status_code=status.HTTP_400_BAD_REQUEST)
        
        if inv.status != Inventory.Status.PENDING_APPROVAL:
            raise APIError('invalid_status', 'El inventario no está pendiente de aprobación.', status_code=status.HTTP_400_BAD_REQUEST)

        # Approve the inventory
        inv.status = Inventory.Status.ACCEPTED
        inv.signed_at = timezone.now()
        inv.signed_by = user
        inv.save()

        # Dissociate the tenant (releases the property to AVAILABLE)
        from pot.services import user_service
        from pot.services.user_service import UserServiceError
        try:
            user_service.desasociar_inmueble_arrendatario(inv.tenant, inv.property, user)
        except UserServiceError as exc:
            if exc.code != 'association_not_found':
                raise APIError('dissociation_error', str(exc), status_code=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            raise APIError('dissociation_error', str(exc), status_code=status.HTTP_400_BAD_REQUEST)

        # Find the active closure ticket for this property and tenant and close it
        from pot.models import Ticket, TicketHistory
        from pot.services.ticket_service import registrar_historial_ticket
        from pot.services.property_service import registrar_evento_propiedad
        from pot.models import PropertyHistory

        closure_ticket = Ticket.objects.filter(
            property=inv.property,
            tenant=inv.tenant,
            damage_type=Ticket.DamageType.CLOSURE,
            status__in=[Ticket.Status.OPEN, Ticket.Status.ACCEPTED, Ticket.Status.IN_PROGRESS]
        ).first()

        if closure_ticket:
            old_status = closure_ticket.status
            closure_ticket.status = Ticket.Status.CLOSED
            closure_ticket.save()
            
            registrar_evento_propiedad(
                property_obj=inv.property,
                event_type=PropertyHistory.EventType.TICKET_CLOSED,
                description=f'Ticket de cierre {closure_ticket.public_code} cerrado tras aprobación de inventario final',
                created_by=user,
                related_user=inv.tenant,
                details={
                    'ticket_id': closure_ticket.id,
                    'public_code': closure_ticket.public_code,
                    'inventory_id': inv.id,
                }
            )
            registrar_historial_ticket(
                closure_ticket,
                TicketHistory.Action.CONFIRMED,
                f'Ticket de cierre finalizado tras aprobación del inventario final por {user.email}',
                created_by=user,
                old_value=old_status,
                new_value=Ticket.Status.CLOSED,
            )

        inv.refresh_from_db()
        return Response(InventoryDetailSerializer(inv).data)

    @action(detail=True, methods=['post'])
    def observations(self, request, pk=None):
        inv = get_object_or_404(Inventory, pk=pk)
        serializer = InventoryObservationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            inventory_service.registrar_observaciones_arrendatario(
                inv,
                request.user,
                serializer.validated_data['observation_text'],
            )
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        return Response(InventoryDetailSerializer(inv).data)

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        inv = self.get_object()
        self.check_object_permissions(request, inv)
        if inv.spaces.count() < 1:
            raise APIError(
                'spaces_required',
                'Agrega al menos un espacio antes de generar el PDF.',
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        pdf_buffer = inventory_service.generar_pdf_inventario(inv)
        inventory_service.registrar_log_generacion_pdf(inv, request.user)
        filename = f'INVENTORY-{inv.property.code}-{timezone.now().strftime("%Y%m%d")}.pdf'
        response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=['post'], url_path='spaces')
    def add_space(self, request, pk=None):
        inv = self.get_object()
        serializer = InventorySpaceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            space = inventory_service.agregar_espacio(inv, **serializer.validated_data)
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        data = InventoryDetailSerializer(inv).data
        data['created_space_id'] = space.pk
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'spaces/(?P<space_id>[^/.]+)')
    def delete_space(self, request, pk=None, space_id=None):
        inv = self.get_object()
        space = get_object_or_404(InventorySpace, pk=space_id, inventory=inv)
        try:
            inventory_service.eliminar_espacio(space)
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        inv.refresh_from_db()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True,
        methods=['post'],
        url_path=r'spaces/(?P<space_id>[^/.]+)/photos',
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_photo(self, request, pk=None, space_id=None):
        inv = self.get_object()
        space = get_object_or_404(InventorySpace, pk=space_id, inventory=inv)
        serializer = InventoryPhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            photo = inventory_service.subir_foto_espacio(
                space,
                image=serializer.validated_data['image'],
                description=serializer.validated_data.get('description'),
                uploaded_by=request.user,
            )
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        from api.v1.serializers.inventories import InventorySpacePhotoSerializer

        return Response(InventorySpacePhotoSerializer(photo).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=['delete'],
        url_path=r'spaces/(?P<space_id>[^/.]+)/photos/(?P<photo_id>[^/.]+)',
    )
    def delete_photo(self, request, pk=None, space_id=None, photo_id=None):
        inv = self.get_object()
        space = get_object_or_404(InventorySpace, pk=space_id, inventory=inv)
        photo = get_object_or_404(InventorySpacePhoto, pk=photo_id, space=space)
        try:
            inventory_service.eliminar_foto(photo)
        except InventoryServiceError as exc:
            _handle_service_error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
