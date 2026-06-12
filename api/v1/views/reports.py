from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.response import Response
from rest_framework.views import APIView

from api.v1.permissions import IsAdmin
from pot.models import Property, Ticket


class ReportsView(APIView):
    """Reporte avanzado para administradores con métricas por período."""

    permission_classes = [IsAdmin]

    PERIOD_DAYS = {
        '7d': 7,
        '30d': 30,
        '90d': 90,
        '365d': 365,
    }

    @extend_schema(
        tags=['Admin'],
        summary='Obtener datos de reportes',
        description='Retorna métricas detalladas de tickets e inmuebles filtradas por período.',
        parameters=[
            OpenApiParameter(
                name='period',
                description='Período del reporte: 7d, 30d, 90d, 365d',
                required=False,
                type=str,
                default='30d',
            ),
        ],
    )
    def get(self, request):
        period = request.query_params.get('period', '30d')
        days = self.PERIOD_DAYS.get(period, 30)
        now = timezone.now()
        start_date = now - timedelta(days=days)

        # ---- KPIs principales ----
        tickets_en_periodo = Ticket.objects.filter(created_at__gte=start_date)
        total = tickets_en_periodo.count()
        resueltos = tickets_en_periodo.filter(
            status__in=[Ticket.Status.CLOSED]
        ).count()
        urgentes = tickets_en_periodo.filter(priority=Ticket.Priority.HIGH).count()
        tasa_resolucion = round((resueltos / total * 100), 1) if total > 0 else 0

        # Tiempo promedio de resolución (días) — tickets cerrados en el período
        tickets_cerrados = tickets_en_periodo.filter(status=Ticket.Status.CLOSED)
        tiempos = []
        for t in tickets_cerrados.only('created_at', 'updated_at'):
            delta = (t.updated_at - t.created_at).total_seconds() / 86400
            tiempos.append(delta)
        tiempo_promedio = round(sum(tiempos) / len(tiempos), 1) if tiempos else 0

        # ---- Tickets por mes (últimos 6 meses) ----
        tickets_por_mes = []
        for i in range(5, -1, -1):
            # Primer día del mes
            ref = now - timedelta(days=30 * i)
            mes_inicio = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Último día del mes
            if mes_inicio.month == 12:
                mes_fin = mes_inicio.replace(year=mes_inicio.year + 1, month=1)
            else:
                mes_fin = mes_inicio.replace(month=mes_inicio.month + 1)

            count = Ticket.objects.filter(
                created_at__gte=mes_inicio,
                created_at__lt=mes_fin,
            ).count()
            resueltos_mes = Ticket.objects.filter(
                created_at__gte=mes_inicio,
                created_at__lt=mes_fin,
                status=Ticket.Status.CLOSED,
            ).count()
            tickets_por_mes.append({
                'mes': mes_inicio.strftime('%b %Y'),
                'total': count,
                'resueltos': resueltos_mes,
            })

        # ---- Tickets por tipo de daño ----
        tipos_raw = (
            tickets_en_periodo
            .values('damage_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        tipos = []
        for item in tipos_raw:
            label = dict(Ticket.DamageType.choices).get(item['damage_type'], item['damage_type'])
            tipos.append({
                'tipo': item['damage_type'],
                'label': label,
                'count': item['count'],
                'porcentaje': round(item['count'] / total * 100, 1) if total > 0 else 0,
            })

        # ---- Top 5 inmuebles con más tickets ----
        top_inmuebles_raw = (
            tickets_en_periodo
            .values('property__address', 'property__code')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )
        top_inmuebles = [
            {
                'inmueble': item['property__address'],
                'codigo': item['property__code'],
                'tickets': item['count'],
            }
            for item in top_inmuebles_raw
        ]

        # ---- Distribución de estados ----
        estados_raw = (
            tickets_en_periodo
            .values('status')
            .annotate(count=Count('id'))
        )
        estados = {
            item['status']: item['count'] for item in estados_raw
        }

        # ---- Distribución por prioridad ----
        prioridades_raw = (
            tickets_en_periodo
            .values('priority')
            .annotate(count=Count('id'))
        )
        prioridades = {
            item['priority']: item['count'] for item in prioridades_raw
        }

        # ---- Tickets detallados para CSV ----
        tickets_csv = []
        for t in tickets_en_periodo.select_related('property', 'tenant').order_by('-created_at')[:200]:
            tickets_csv.append({
                'codigo': t.public_code or f'TK-{t.pk:05d}',
                'inmueble': t.property.address if t.property else '',
                'tipo': t.get_damage_type_display(),
                'prioridad': t.get_priority_display(),
                'estado': t.get_status_display(),
                'inquilino': t.tenant.email if t.tenant else '',
                'fecha': t.created_at.strftime('%Y-%m-%d'),
            })

        return Response({
            'periodo': period,
            'dias': days,
            'kpis': {
                'total_tickets': total,
                'tickets_resueltos': resueltos,
                'tickets_urgentes': urgentes,
                'tasa_resolucion': tasa_resolucion,
                'tiempo_promedio_dias': tiempo_promedio,
            },
            'tickets_por_mes': tickets_por_mes,
            'tickets_por_tipo': tipos,
            'top_inmuebles': top_inmuebles,
            'estados': estados,
            'prioridades': prioridades,
            'tickets_csv': tickets_csv,
        })
