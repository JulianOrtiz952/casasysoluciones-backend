from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.v1.exceptions import APIError
from api.v1.pagination import StandardResultsSetPagination
from api.v1.permissions import IsTenant
from api.v1.serializers.tickets import (
    TicketAttachmentSerializer,
    TicketAttachmentUploadSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketHistorySerializer,
    TicketListSerializer,
    TicketReportProblemSerializer,
)
from pot.models import CustomUser, PropertyHistory, Ticket, TicketHistory
from pot.services import ticket_service
from pot.services.property_service import registrar_evento_propiedad
from pot.services.ticket_service import TicketServiceError, registrar_historial_ticket


def _handle_service_error(exc):
    status_map = {
        'not_found': status.HTTP_404_NOT_FOUND,
        'not_tenant': status.HTTP_403_FORBIDDEN,
        'not_assigned': status.HTTP_403_FORBIDDEN,
        'not_authorized': status.HTTP_403_FORBIDDEN,
        'no_evidence': status.HTTP_400_BAD_REQUEST,
        'property_not_associated': status.HTTP_400_BAD_REQUEST,
        'property_id_required': status.HTTP_400_BAD_REQUEST,
        'no_active_properties': status.HTTP_400_BAD_REQUEST,
        'not_editable': status.HTTP_400_BAD_REQUEST,
        'max_attachments': status.HTTP_400_BAD_REQUEST,
        'invalid_image': status.HTTP_400_BAD_REQUEST,
    }
    raise APIError(
        exc.code,
        exc.message,
        status_code=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
        details=exc.details,
    ) from exc


class TenantTicketViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """HU-05: creación de tickets por arrendatario (RF-13 a RF-17)."""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Ticket.objects.none()
        if user.is_staff_operative():
            return (
                Ticket.objects.all()
                .select_related('property', 'tenant')
                .prefetch_related('attachments', 'assigned_technicians')
                .order_by('-created_at')
            )
        if user.role == CustomUser.Role.TECHNICIAN:
            return (
                Ticket.objects.filter(assigned_technicians=user)
                .select_related('property', 'tenant')
                .prefetch_related('attachments', 'assigned_technicians')
                .order_by('-created_at')
            )
        return (
            Ticket.objects.filter(tenant=user)
            .select_related('property', 'tenant')
            .prefetch_related('attachments', 'assigned_technicians')
            .order_by('-created_at')
        )

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return TicketDetailSerializer
        if self.action == 'attachments':
            return TicketAttachmentUploadSerializer
        if self.action in ('create', 'draft'):
            return TicketCreateSerializer
        return TicketListSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        page = self.paginate_queryset(queryset)
        serializer = TicketListSerializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        return self._create_ticket(request, ticket_status=Ticket.Status.OPEN, notify=True)

    @action(detail=False, methods=['post'], url_path='draft')
    def draft(self, request):
        return self._create_ticket(request, ticket_status=Ticket.Status.DRAFT, notify=False)

    def _create_ticket(self, request, *, ticket_status, notify):
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            ticket = ticket_service.crear_ticket_arrendatario(
                request.user,
                property_id=data.get('property_id'),
                description=data['description'],
                damage_type=data['damage_type'],
                damage_type_other=data.get('damage_type_other', ''),
                priority=data['priority'],
                status=ticket_status,
                title=data.get('title'),
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        if notify:
            ticket_service.notificar_apertura_ticket(ticket, request)
        return Response(TicketDetailSerializer(ticket).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='attachments')
    def attachments(self, request, pk=None):
        serializer = TicketAttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            attachment = ticket_service.agregar_adjunto_ticket(
                request.user,
                pk,
                serializer.validated_data['image'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(
            TicketAttachmentSerializer(attachment).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        try:
            ticket = ticket_service.confirmar_ticket_reparacion(request.user, pk)
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(TicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['post'], url_path='save-final-conditions')
    def save_final_conditions(self, request, pk=None):
        """
        Allows an assigned technician to save final space conditions for CLOSURE tickets.
        Payload: { "conditions": [{"space_name": "...", "condition": "GOOD|REGULAR|BAD", "observations": "..."}] }
        """
        try:
            ticket = Ticket.objects.get(pk=pk)
        except Ticket.DoesNotExist:
            raise APIError('not_found', 'Ticket no encontrado.', status_code=status.HTTP_404_NOT_FOUND)

        user = request.user
        is_assigned_tech = ticket.assigned_technicians.filter(pk=user.pk).exists()
        if not is_assigned_tech and not user.is_staff_operative():
            raise APIError('not_authorized', 'Solo el técnico asignado puede guardar las condiciones finales.', status_code=status.HTTP_403_FORBIDDEN)

        if ticket.damage_type != Ticket.DamageType.CLOSURE:
            raise APIError('not_closure', 'Este endpoint solo aplica a tickets de Cierre de Contrato.', status_code=status.HTTP_400_BAD_REQUEST)

        conditions = request.data.get('conditions')
        if not isinstance(conditions, list) or len(conditions) == 0:
            raise APIError('invalid_conditions', 'Debes proveer un array de condiciones con al menos un espacio.', status_code=status.HTTP_400_BAD_REQUEST)

        valid_conditions = {'GOOD', 'REGULAR', 'BAD'}
        for item in conditions:
            if not isinstance(item, dict):
                raise APIError('invalid_conditions', 'Cada elemento debe ser un objeto.', status_code=status.HTTP_400_BAD_REQUEST)
            if not item.get('space_name'):
                raise APIError('invalid_conditions', 'Cada espacio debe tener un nombre.', status_code=status.HTTP_400_BAD_REQUEST)
            if item.get('condition') not in valid_conditions:
                raise APIError('invalid_conditions', f'Condición inválida: {item.get("condition")}. Use GOOD, REGULAR o BAD.', status_code=status.HTTP_400_BAD_REQUEST)
            items = item.get('items')
            if items is not None and not isinstance(items, list):
                raise APIError('invalid_conditions', 'El campo items debe ser una lista si está presente.', status_code=status.HTTP_400_BAD_REQUEST)

        condition_display_map = {'GOOD': 'Bueno', 'REGULAR': 'Regular', 'BAD': 'Malo'}
        normalized = [
            {
                'space_name': item['space_name'],
                'condition': item['condition'],
                'condition_display': condition_display_map[item['condition']],
                'observations': item.get('observations', ''),
                'items': item.get('items', []),
            }
            for item in conditions
        ]

        ticket.final_space_conditions = normalized
        ticket.save(update_fields=['final_space_conditions', 'updated_at'])
        return Response(TicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Allows an admin/assistant to reject a closure or client ticket with a reason."""
        serializer = TicketReportProblemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ticket = ticket_service.rechazar_ticket_por_admin(
                request.user,
                pk,
                serializer.validated_data['reason'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(TicketDetailSerializer(ticket).data)


    @action(detail=True, methods=['post'], url_path='report-problem')
    def report_problem(self, request, pk=None):
        serializer = TicketReportProblemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ticket = ticket_service.reportar_problema_reparacion(
                request.user,
                pk,
                serializer.validated_data['reason'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(TicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['patch', 'post'], url_path='update-status')
    def update_status(self, request, pk=None):
        user = request.user
        if not user.is_staff_operative():
            return Response(
                {'error': 'No tiene permisos para cambiar el estado de este ticket.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            ticket = Ticket.objects.prefetch_related('assigned_technicians').get(pk=pk)
        except Ticket.DoesNotExist:
            return Response({'error': 'Ticket no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
            
        status_val = request.data.get('status')
        if not status_val or status_val not in dict(Ticket.Status.choices):
            return Response(
                {'error': f'Estado no válido. Opciones: {list(dict(Ticket.Status.choices).keys())}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if status_val == Ticket.Status.REJECTED:
            rejection_reason = request.data.get('rejection_reason')
            if not rejection_reason or not rejection_reason.strip():
                return Response(
                    {'error': 'La descripción del rechazo es obligatoria para rechazar un ticket.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            ticket.rejection_reason = rejection_reason.strip()

        old_status = ticket.status
        assigned_contractor = request.data.get('assigned_contractor_name')
        assigned_technicians_ids = request.data.get('assigned_technicians')
        
        ticket.status = status_val
        if assigned_contractor is not None:
            old_contractor = ticket.assigned_contractor_name
            ticket.assigned_contractor_name = assigned_contractor.strip()
            if old_contractor != ticket.assigned_contractor_name:
                registrar_historial_ticket(
                    ticket,
                    TicketHistory.Action.CONTRACTOR_ASSIGNED,
                    f'Contratista actualizado por {user.email}',
                    created_by=user,
                    old_value=old_contractor,
                    new_value=ticket.assigned_contractor_name,
                )
            
        if assigned_technicians_ids is not None:
            if isinstance(assigned_technicians_ids, str):
                if assigned_technicians_ids.strip() in ('', 'null', '[]'):
                    ids_list = []
                else:
                    try:
                        import json
                        ids_list = json.loads(assigned_technicians_ids)
                        if not isinstance(ids_list, list):
                            ids_list = [int(assigned_technicians_ids)]
                    except ValueError:
                        ids_list = [int(x.strip()) for x in assigned_technicians_ids.split(',') if x.strip()]
            elif isinstance(assigned_technicians_ids, list):
                ids_list = [int(x) for x in assigned_technicians_ids]
            elif isinstance(assigned_technicians_ids, int):
                ids_list = [assigned_technicians_ids]
            elif assigned_technicians_ids in (None, 0):
                ids_list = []
            else:
                ids_list = []

            tech_users = []
            for tid in ids_list:
                try:
                    tech = CustomUser.objects.get(pk=tid, role=CustomUser.Role.TECHNICIAN)
                    tech_users.append(tech)
                except CustomUser.DoesNotExist:
                    return Response(
                        {'error': f'El técnico con ID {tid} no existe o no tiene el rol de técnico.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            old_techs = list(ticket.assigned_technicians.all())
            old_tech_names = ", ".join([f"{u.first_name} {u.last_name}" for u in old_techs])
            new_tech_names = ", ".join([f"{u.first_name} {u.last_name}" for u in tech_users])

            if set(old_techs) != set(tech_users):
                ticket.assigned_technicians.set(tech_users)
                registrar_historial_ticket(
                    ticket,
                    TicketHistory.Action.TECHNICIAN_ASSIGNED,
                    f'Técnicos asignados actualizados por {user.email}',
                    created_by=user,
                    old_value=old_tech_names,
                    new_value=new_tech_names,
                )
            
        ticket.save()

        # Register status change in history
        if old_status != status_val:
            history_desc = f'Estado cambiado por {user.email}'
            if status_val == Ticket.Status.REJECTED:
                history_desc = f'Ticket rechazado por {user.email}. Motivo: {ticket.rejection_reason}'
            registrar_historial_ticket(
                ticket,
                TicketHistory.Action.STATUS_CHANGE,
                history_desc,
                created_by=user,
                old_value=old_status,
                new_value=status_val,
            )
        
        # Log event on property
        description_prop = f'Ticket {ticket.public_code} actualizado a estado {ticket.get_status_display()} por {user.email}'
        if status_val == Ticket.Status.REJECTED:
            description_prop = f'Ticket {ticket.public_code} rechazado por {user.email}. Motivo: {ticket.rejection_reason}'
        registrar_evento_propiedad(
            property_obj=ticket.property,
            event_type=PropertyHistory.EventType.STATUS_CHANGE,
            description=description_prop,
            created_by=user,
            related_user=ticket.tenant,
            details={
                'ticket_id': ticket.id,
                'public_code': ticket.public_code,
                'new_status': status_val,
                'rejection_reason': ticket.rejection_reason if status_val == Ticket.Status.REJECTED else '',
                'assigned_contractor': ticket.assigned_contractor_name,
                'assigned_technicians': [u.id for u in ticket.assigned_technicians.all()],
            },
        )
        
        return Response(TicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        """Return the change history for a specific ticket."""
        try:
            ticket = Ticket.objects.get(pk=pk)
        except Ticket.DoesNotExist:
            return Response({'error': 'Ticket no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        # Verify user has access to this ticket
        if not user.is_staff_operative() and user.role != CustomUser.Role.TECHNICIAN:
            if ticket.tenant_id != user.pk:
                return Response({'error': 'No tiene acceso a este ticket.'}, status=status.HTTP_403_FORBIDDEN)
        elif user.role == CustomUser.Role.TECHNICIAN:
            if not ticket.assigned_technicians.filter(id=user.pk).exists():
                return Response({'error': 'No tiene acceso a este ticket.'}, status=status.HTTP_403_FORBIDDEN)

        history_entries = ticket.history.select_related('created_by').all()
        serializer = TicketHistorySerializer(history_entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='technician-attachments')
    def technician_attachments(self, request, pk=None):
        """Allow assigned technician to upload repair evidence."""
        serializer = TicketAttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            attachment = ticket_service.agregar_adjunto_tecnico(
                request.user,
                pk,
                serializer.validated_data['image'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(
            TicketAttachmentSerializer(attachment).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='complete')
    def complete(self, request, pk=None):
        """Mark ticket as completed by assigned technician (requires evidence)."""
        try:
            ticket = ticket_service.completar_ticket_tecnico(request.user, pk)
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(TicketDetailSerializer(ticket).data)
