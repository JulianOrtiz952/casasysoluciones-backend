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
    TicketListSerializer,
)
from pot.models import Ticket
from pot.services import ticket_service
from pot.services.ticket_service import TicketServiceError


def _handle_service_error(exc):
    status_map = {
        'not_found': status.HTTP_404_NOT_FOUND,
        'not_tenant': status.HTTP_403_FORBIDDEN,
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
