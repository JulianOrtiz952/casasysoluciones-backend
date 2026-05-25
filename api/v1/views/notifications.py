from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.v1.exceptions import APIError
from api.v1.pagination import StandardResultsSetPagination
from api.v1.serializers.notifications import NotificationSerializer
from pot.services import notification_service


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """HU-08: notificaciones in-app del usuario autenticado."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        unread_only = self.request.query_params.get('unread') in ('1', 'true', 'yes')
        return notification_service.listar_notificaciones_usuario(
            self.request.user,
            unread_only=unread_only,
        )

    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        count = notification_service.contar_no_leidas_usuario(request.user)
        return Response({'unread_count': count})

    @action(detail=True, methods=['patch'], url_path='read')
    def mark_read(self, request, pk=None):
        notification = notification_service.marcar_notificacion_leida(request.user, pk)
        if notification is None:
            raise APIError('not_found', 'Notificación no encontrada.', status_code=status.HTTP_404_NOT_FOUND)
        return Response(NotificationSerializer(notification).data)
