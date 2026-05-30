"""Reportes administrativos HU-09 (RF-29, RF-30). Solo consumo desde API con rol ADMIN."""

from datetime import datetime

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from pot.models import CustomUser, Property, Ticket
from pot.services.ticket_service import (
    ACTIVE_STATUSES,
    calcular_traffic_light,
    exportar_tickets_queryset,
    obtener_estadisticas_tickets,
    pending_resolution_queryset,
)


class ReportServiceError(Exception):
    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def _parse_filter_date(value):
    if not value:
        return None
    dt = parse_datetime(value)
    if dt is not None:
        return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
    d = parse_date(value)
    if d is not None:
        return timezone.make_aware(datetime.combine(d, datetime.min.time()))
    return None


def filtrar_tickets_reporte(*, property_id=None, tenant_id=None, date_from=None, date_to=None):
    qs = Ticket.objects.exclude(status=Ticket.Status.DRAFT)
    if property_id:
        qs = qs.filter(property_id=property_id)
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    if date_from:
        dt = _parse_filter_date(date_from)
        if dt:
            qs = qs.filter(created_at__gte=dt)
    if date_to:
        dt = _parse_filter_date(date_to)
        if dt:
            if hasattr(dt, 'hour'):
                qs = qs.filter(created_at__lte=dt)
            else:
                qs = qs.filter(created_at__date__lte=dt)
    return qs


def _report_filters(**kwargs):
    return {
        'property_id': kwargs.get('property_id') or None,
        'tenant_id': kwargs.get('tenant_id') or None,
        'date_from': kwargs.get('date_from') or None,
        'date_to': kwargs.get('date_to') or None,
    }


def obtener_semaforo_consolidado(**filters):
    """RF-29: semáforo y pendientes por resolver (opcionalmente filtrados)."""
    base = filtrar_tickets_reporte(**_report_filters(**filters))
    stats = obtener_estadisticas_tickets(base)
    return {
        'pending_resolution': stats['pending_resolution'],
        'traffic_light': stats['traffic_light'],
        'urgent': stats['urgent'],
        'open': stats['open'],
        'accepted': stats['accepted'],
        'in_progress': stats['in_progress'],
    }


def obtener_resumen_reportes(**filters):
    """Resumen con conteos y gráficos por estado, prioridad y tipo de daño."""
    qs = filtrar_tickets_reporte(**_report_filters(**filters))
    pending_qs = pending_resolution_queryset(qs)
    by_status = dict(qs.values('status').annotate(c=Count('id')).values_list('status', 'c'))
    by_priority = dict(qs.values('priority').annotate(c=Count('id')).values_list('priority', 'c'))
    by_damage_type = dict(qs.values('damage_type').annotate(c=Count('id')).values_list('damage_type', 'c'))
    return {
        'total_tickets': qs.count(),
        'pending_resolution': pending_qs.count(),
        'traffic_light': calcular_traffic_light(pending_qs),
        'by_status': by_status,
        'by_priority': by_priority,
        'by_damage_type': by_damage_type,
        'filters_applied': {k: v for k, v in _report_filters(**filters).items() if v},
    }


def listar_inmuebles_con_tickets_abiertos(**filters):
    """RF-30: inmuebles arrendados con al menos un ticket activo."""
    ticket_qs = filtrar_tickets_reporte(**_report_filters(**filters)).filter(status__in=ACTIVE_STATUSES)
    property_ids = ticket_qs.values_list('property_id', flat=True).distinct()
    props = Property.objects.filter(id__in=property_ids, status=Property.Status.RENTED).order_by('code')
    if filters.get('property_id'):
        props = props.filter(pk=filters['property_id'])
    results = []
    for prop in props:
        tenant = prop.get_active_tenant()
        open_count = ticket_qs.filter(property_id=prop.pk).count()
        results.append({
            'property_id': prop.pk,
            'property_code': prop.code,
            'address': prop.address,
            'city': prop.city,
            'status': prop.status,
            'open_tickets_count': open_count,
            'tenant': _tenant_brief(tenant),
        })
    return results


def listar_inquilinos_con_tickets_activos(**filters):
    """RF-30: arrendatarios con tickets en estados activos."""
    ticket_qs = filtrar_tickets_reporte(**_report_filters(**filters)).filter(
        status__in=ACTIVE_STATUSES,
        tenant__isnull=False,
    )
    tenant_ids = ticket_qs.values_list('tenant_id', flat=True).distinct()
    tenants = CustomUser.objects.filter(pk__in=tenant_ids, role=CustomUser.Role.TENANT).order_by('last_name', 'first_name')
    if filters.get('tenant_id'):
        tenants = tenants.filter(pk=filters['tenant_id'])
    results = []
    for tenant in tenants:
        tenant_tickets = ticket_qs.filter(tenant_id=tenant.pk)
        property_ids = tenant_tickets.values_list('property_id', flat=True).distinct()
        properties = Property.objects.filter(pk__in=property_ids).values('id', 'code', 'address')
        results.append({
            'tenant_id': tenant.pk,
            'public_code': tenant.public_code,
            'full_name': tenant.get_full_name() or tenant.email,
            'email': tenant.email,
            'document_number': tenant.document_number or '',
            'active_tickets_count': tenant_tickets.count(),
            'properties': list(properties),
        })
    return results


def obtener_historial_reparaciones_inmueble(property_id, **filters):
    """RF-30: tickets cerrados (reparaciones finalizadas) de un inmueble."""
    try:
        prop = Property.objects.get(pk=property_id)
    except Property.DoesNotExist as exc:
        raise ReportServiceError('property_not_found', 'Inmueble no encontrado.') from exc

    qs = (
        Ticket.objects.filter(property=prop, status=Ticket.Status.CLOSED)
        .select_related('tenant')
        .order_by('-updated_at')
    )
    tenant_id = filters.get('tenant_id')
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    date_from = filters.get('date_from')
    if date_from:
        dt = _parse_filter_date(date_from)
        if dt:
            qs = qs.filter(updated_at__gte=dt)
    date_to = filters.get('date_to')
    if date_to:
        dt = _parse_filter_date(date_to)
        if dt:
            if hasattr(dt, 'hour'):
                qs = qs.filter(updated_at__lte=dt)
            else:
                qs = qs.filter(updated_at__date__lte=dt)

    repairs = []
    for ticket in qs:
        repairs.append({
            'ticket_id': ticket.pk,
            'public_code': ticket.public_code,
            'title': ticket.title,
            'damage_type': ticket.damage_type,
            'damage_type_display': ticket.get_damage_type_display(),
            'priority': ticket.priority,
            'priority_display': ticket.get_priority_display(),
            'assigned_contractor_name': ticket.assigned_contractor_name,
            'tenant': _tenant_brief(ticket.tenant),
            'closed_automatically': ticket.closed_automatically,
            'tenant_confirmed_at': ticket.tenant_confirmed_at,
            'created_at': ticket.created_at,
            'closed_at': ticket.updated_at,
        })
    return {
        'property_id': prop.pk,
        'property_code': prop.code,
        'address': prop.address,
        'repairs_count': len(repairs),
        'repairs': repairs,
    }


def exportar_reporte_excel(**filters):
    """Filas para export Excel de tickets según filtros de reporte."""
    qs = filtrar_tickets_reporte(**_report_filters(**filters))
    return exportar_tickets_queryset(qs)


def busqueda_global(query, *, limit=20):
    """Búsqueda global de inmuebles, arrendatarios y tickets (admin)."""
    q = (query or '').strip()
    if len(q) < 2:
        raise ReportServiceError('query_too_short', 'La búsqueda debe tener al menos 2 caracteres.')

    per_type = max(1, limit // 3)
    properties = list(
        Property.objects.filter(
            Q(code__icontains=q) | Q(address__icontains=q) | Q(owner_name__icontains=q),
        ).values('id', 'code', 'address', 'status')[:per_type],
    )
    tenants = list(
        CustomUser.objects.filter(
            role=CustomUser.Role.TENANT,
        )
        .filter(
            Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(document_number__icontains=q)
            | Q(public_code__icontains=q),
        )
        .values('id', 'public_code', 'email', 'first_name', 'last_name', 'document_number')[:per_type],
    )
    tickets = list(
        Ticket.objects.exclude(status=Ticket.Status.DRAFT)
        .filter(
            Q(public_code__icontains=q)
            | Q(description__icontains=q)
            | Q(property__code__icontains=q),
        )
        .select_related('property')
        .values('id', 'public_code', 'status', 'property__code')[:per_type],
    )
    return {
        'query': q,
        'properties': properties,
        'tenants': tenants,
        'tickets': [
            {
                'id': t['id'],
                'public_code': t['public_code'],
                'status': t['status'],
                'property_code': t['property__code'],
            }
            for t in tickets
        ],
    }


def _tenant_brief(tenant):
    if not tenant:
        return None
    return {
        'id': tenant.pk,
        'public_code': tenant.public_code,
        'full_name': tenant.get_full_name() or tenant.email,
        'email': tenant.email,
    }
