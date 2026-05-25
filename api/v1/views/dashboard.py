from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from api.v1.permissions import IsAdmin
from pot.models import CustomUser, Property, Ticket


class DashboardStatsView(APIView):
    """Estadísticas generales para el dashboard administrativo."""

    permission_classes = [IsAdmin]

    @extend_schema(
        tags=['Admin'],
        summary='Obtener estadísticas del dashboard',
        description='Retorna conteos de inmuebles, inquilinos y tickets para el resumen general.',
    )
    def get(self, request):
        # Propiedades
        total_inmuebles = Property.objects.count()
        disponibles = Property.objects.filter(status=Property.Status.AVAILABLE).count()

        # Inquilinos
        inquilinos_activos = CustomUser.objects.filter(role=CustomUser.Role.TENANT, is_active=True).count()

        # Tickets
        tickets_abiertos = Ticket.objects.exclude(status=Ticket.Status.CLOSED).count()
        tickets_urgentes = Ticket.objects.filter(priority=Ticket.Priority.HIGH).exclude(status=Ticket.Status.CLOSED).count()

        # Tickets por estado
        stats_estado = Ticket.objects.values('status').annotate(count=Count('id'))
        
        # Tickets por prioridad
        stats_prioridad = Ticket.objects.values('priority').annotate(count=Count('id'))

        # Tickets recientes (últimos 5)
        recent_tickets = Ticket.objects.select_related('property').order_by('-created_at')[:5]
        recent_tickets_data = [
            {
                'id': t.public_code or f'TK-{t.pk:05d}',
                'inmueble': t.property.address,
                'tipo': t.get_damage_type_display(),
                'prioridad': t.priority,
                'estado': t.status,
                'fecha': t.created_at.strftime('%d %b %Y'),
            }
            for t in recent_tickets
        ]

        data = {
            'overview': {
                'total_inmuebles': total_inmuebles,
                'disponibles': disponibles,
                'inquilinos_activos': inquilinos_activos,
                'tickets_abiertos': tickets_abiertos,
                'tickets_urgentes': tickets_urgentes,
            },
            'tickets_by_status': {s['status']: s['count'] for s in stats_estado},
            'tickets_by_priority': {p['priority']: p['count'] for p in stats_prioridad},
            'recent_tickets': recent_tickets_data,
        }

        return Response(data)
