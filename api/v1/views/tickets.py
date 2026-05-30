import csv
import io

from django.db import models
from django.http import HttpResponse
from django.utils.dateparse import parse_date, parse_datetime
from openpyxl import Workbook
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.v1.exceptions import APIError
from api.v1.pagination import StandardResultsSetPagination
from api.v1.permissions import IsStaffOperative, IsTenant
from api.v1.serializers.tickets import (
    StaffTicketDetailSerializer,
    StaffTicketListSerializer,
    TicketAssignSerializer,
    TicketAttachmentSerializer,
    TicketAttachmentUploadSerializer,
    TicketCommentCreateSerializer,
    TicketCommentSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketDisputeSerializer,
    TicketInfoRequestSerializer,
    TicketListSerializer,
    TicketRejectSerializer,
    TicketRepairEvidenceUploadSerializer,
    TicketStatusChangeSerializer,
    TicketStatusLogSerializer,
)
from pot.models import Ticket
from pot.services import ticket_service
from pot.services.ticket_service import TicketServiceError


def _handle_service_error(exc):
    status_map = {
        'not_found': status.HTTP_404_NOT_FOUND,
        'not_tenant': status.HTTP_403_FORBIDDEN,
        'not_staff': status.HTTP_403_FORBIDDEN,
        'property_not_associated': status.HTTP_400_BAD_REQUEST,
        'property_id_required': status.HTTP_400_BAD_REQUEST,
        'no_active_properties': status.HTTP_400_BAD_REQUEST,
        'not_editable': status.HTTP_400_BAD_REQUEST,
        'max_attachments': status.HTTP_400_BAD_REQUEST,
        'max_repair_evidence': status.HTTP_400_BAD_REQUEST,
        'invalid_image': status.HTTP_400_BAD_REQUEST,
        'invalid_transition': status.HTTP_400_BAD_REQUEST,
        'invalid_status': status.HTTP_400_BAD_REQUEST,
        'status_not_active': status.HTTP_400_BAD_REQUEST,
        'reason_too_short': status.HTTP_400_BAD_REQUEST,
        'justification_required': status.HTTP_400_BAD_REQUEST,
        'repair_evidence_required': status.HTTP_400_BAD_REQUEST,
        'contractor_required': status.HTTP_400_BAD_REQUEST,
        'use_assign': status.HTTP_400_BAD_REQUEST,
        'use_reject': status.HTTP_400_BAD_REQUEST,
        'same_status': status.HTTP_400_BAD_REQUEST,
        'no_repair_evidence': status.HTTP_400_BAD_REQUEST,
        'confirmation_not_pending': status.HTTP_400_BAD_REQUEST,
        'already_confirmed': status.HTTP_400_BAD_REQUEST,
        'note_too_short': status.HTTP_400_BAD_REQUEST,
        'ticket_closed': status.HTTP_400_BAD_REQUEST,
        'message_too_short': status.HTTP_400_BAD_REQUEST,
        'no_tenant': status.HTTP_400_BAD_REQUEST,
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

    permission_classes = [IsAuthenticated, IsTenant]
    pagination_class = StandardResultsSetPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return (
            Ticket.objects.filter(tenant=self.request.user)
            .select_related('property')
            .prefetch_related('attachments')
            .order_by('-created_at')
        )

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return TicketDetailSerializer
        if self.action == 'attachments':
            return TicketAttachmentUploadSerializer
        if self.action == 'dispute':
            return TicketDisputeSerializer
        if self.action in ('create', 'draft'):
            return TicketCreateSerializer
        return TicketListSerializer

    def retrieve(self, request, *args, **kwargs):
        try:
            ticket = ticket_service.obtener_ticket_arrendatario(request.user, kwargs['pk'])
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(TicketDetailSerializer(ticket).data)

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

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        try:
            ticket = ticket_service.confirmar_reparacion_arrendatario(request.user, pk)
        except TicketServiceError as exc:
            _handle_service_error(exc)
        ticket = ticket_service.obtener_ticket_arrendatario(request.user, ticket.pk)
        return Response(TicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def dispute(self, request, pk=None):
        serializer = TicketDisputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ticket = ticket_service.disputar_reparacion_arrendatario(
                request.user,
                pk,
                note=serializer.validated_data['note'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        ticket = ticket_service.obtener_ticket_arrendatario(request.user, ticket.pk)
        return Response(TicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['get', 'post'], url_path='comments')
    def comments(self, request, pk=None):
        if request.method == 'GET':
            try:
                comments = ticket_service.listar_comentarios_ticket(request.user, pk)
            except TicketServiceError as exc:
                _handle_service_error(exc)
            return Response(TicketCommentSerializer(comments, many=True).data)
        serializer = TicketCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            comment = ticket_service.agregar_comentario_ticket(
                request.user,
                pk,
                body=serializer.validated_data['body'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(
            TicketCommentSerializer(comment).data,
            status=status.HTTP_201_CREATED,
        )


class StaffTicketViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """HU-06: gestión de tickets por personal operativo (RF-18 a RF-21, RF-29 parcial)."""

    permission_classes = [IsAuthenticated, IsStaffOperative]
    pagination_class = StandardResultsSetPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    lookup_value_regex = r'[0-9]+'

    def get_queryset(self):
        qs = (
            Ticket.objects.exclude(status=Ticket.Status.DRAFT)
            .select_related('property', 'tenant')
            .prefetch_related('attachments')
            .order_by('-created_at')
        )
        params = self.request.query_params
        ticket_status = params.get('status')
        if ticket_status:
            qs = qs.filter(status=ticket_status)
        priority = params.get('priority')
        if priority:
            qs = qs.filter(priority=priority)
        damage_type = params.get('damage_type')
        if damage_type:
            qs = qs.filter(damage_type=damage_type)
        property_id = params.get('property_id')
        if property_id:
            qs = qs.filter(property_id=property_id)
        tenant_id = params.get('tenant_id')
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        date_from = params.get('date_from')
        if date_from:
            dt = parse_date(date_from) or parse_datetime(date_from)
            if dt:
                qs = qs.filter(created_at__gte=dt)
        date_to = params.get('date_to')
        if date_to:
            dt = parse_date(date_to) or parse_datetime(date_to)
            if dt:
                if hasattr(dt, 'hour'):
                    qs = qs.filter(created_at__lte=dt)
                else:
                    qs = qs.filter(created_at__date__lte=dt)
        search = (params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                models.Q(public_code__icontains=search)
                | models.Q(description__icontains=search)
                | models.Q(property__code__icontains=search)
            )
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return StaffTicketDetailSerializer
        return StaffTicketListSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance = (
            Ticket.objects.select_related('property', 'tenant')
            .prefetch_related('attachments', 'status_logs__changed_by')
            .get(pk=instance.pk)
        )
        serializer = StaffTicketDetailSerializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='status')
    def change_status(self, request, pk=None):
        serializer = TicketStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            ticket = ticket_service.cambiar_estado_ticket(
                request.user,
                pk,
                new_status=data['status'],
                note=data.get('note', ''),
                force_close=data.get('force_close', False),
                justification=data.get('justification', ''),
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        ticket = ticket_service.obtener_ticket_staff(request.user, ticket.pk)
        return Response(StaffTicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        serializer = TicketRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ticket = ticket_service.rechazar_ticket(
                request.user,
                pk,
                reason=serializer.validated_data['reason'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        ticket_service.notificar_rechazo_ticket(ticket, request)
        ticket = ticket_service.obtener_ticket_staff(request.user, ticket.pk)
        return Response(StaffTicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        serializer = TicketAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            ticket = ticket_service.asignar_maestro_ticket(
                request.user,
                pk,
                contractor_name=data['contractor_name'],
                visit_note=data.get('visit_note', ''),
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        ticket = ticket_service.obtener_ticket_staff(request.user, ticket.pk)
        return Response(StaffTicketDetailSerializer(ticket).data)

    @action(detail=True, methods=['post'], url_path='repair-evidence')
    def repair_evidence(self, request, pk=None):
        serializer = TicketRepairEvidenceUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            attachment = ticket_service.agregar_evidencia_reparacion(
                request.user,
                pk,
                serializer.validated_data['image'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        ticket = ticket_service.obtener_ticket_staff(request.user, pk)
        return Response(
            {
                'attachment': TicketAttachmentSerializer(attachment).data,
                'ticket': StaffTicketDetailSerializer(ticket).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['get'])
    def stats(self, request):
        return Response(ticket_service.obtener_estadisticas_tickets())

    @action(detail=False, methods=['get'])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        fmt = (request.query_params.get('export_format') or 'csv').lower()
        rows = ticket_service.exportar_tickets_queryset(queryset)

        if fmt == 'xlsx':
            wb = Workbook()
            ws = wb.active
            ws.title = 'Tickets'
            for row in rows:
                ws.append(row)
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            response = HttpResponse(
                buf.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = 'attachment; filename="tickets.xlsx"'
            return response

        output = io.StringIO()
        writer = csv.writer(output)
        for row in rows:
            writer.writerow(row)
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="tickets.csv"'
        return response

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        try:
            logs = ticket_service.obtener_timeline_ticket(request.user, pk)
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(TicketStatusLogSerializer(logs, many=True).data)

    @action(detail=True, methods=['get', 'post'], url_path='comments')
    def comments(self, request, pk=None):
        if request.method == 'GET':
            try:
                comments = ticket_service.listar_comentarios_ticket(request.user, pk)
            except TicketServiceError as exc:
                _handle_service_error(exc)
            return Response(TicketCommentSerializer(comments, many=True).data)
        serializer = TicketCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            comment = ticket_service.agregar_comentario_ticket(
                request.user,
                pk,
                body=serializer.validated_data['body'],
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(
            TicketCommentSerializer(comment).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='request-info')
    def request_info(self, request, pk=None):
        serializer = TicketInfoRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            comment = ticket_service.solicitar_info_adicional_ticket(
                request.user,
                pk,
                message=serializer.validated_data['message'],
                request=request,
            )
        except TicketServiceError as exc:
            _handle_service_error(exc)
        return Response(
            TicketCommentSerializer(comment).data,
            status=status.HTTP_201_CREATED,
        )
