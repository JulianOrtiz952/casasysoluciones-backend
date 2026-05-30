from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from pot.models import (
    CustomUser,
    Property,
    PropertyHistory,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketStatusLog,
)
from pot.services.inventory_service import validar_archivo_imagen
from pot.services.property_service import registrar_evento_propiedad

MAX_TICKET_ATTACHMENTS = 5
MAX_REPAIR_EVIDENCE_ATTACHMENTS = 10
MIN_REJECTION_REASON_LENGTH = 20
MIN_FORCE_CLOSE_JUSTIFICATION_LENGTH = 20
MIN_DISPUTE_NOTE_LENGTH = 10
MIN_COMMENT_LENGTH = 1
MIN_INFO_REQUEST_LENGTH = 10
STALE_TICKET_DAYS = 3
CONFIRMATION_REMINDER_HOURS_BEFORE = 24

ACTIVE_STATUSES = frozenset({
    Ticket.Status.OPEN,
    Ticket.Status.ACCEPTED,
    Ticket.Status.IN_PROGRESS,
})

ALLOWED_STATUS_TRANSITIONS = {
    Ticket.Status.OPEN: {Ticket.Status.ACCEPTED, Ticket.Status.REJECTED},
    Ticket.Status.ACCEPTED: {Ticket.Status.IN_PROGRESS, Ticket.Status.REJECTED, Ticket.Status.CLOSED},
    Ticket.Status.IN_PROGRESS: {Ticket.Status.CLOSED, Ticket.Status.REJECTED},
}


class TicketServiceError(Exception):
    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def obtener_inmuebles_activos_arrendatario(tenant):
    return Property.objects.filter(
        tenant_associations__user=tenant,
        tenant_associations__dissociated_at__isnull=True,
    ).distinct()


def resolver_inmueble_ticket(tenant, property_id=None):
    properties = list(obtener_inmuebles_activos_arrendatario(tenant))
    if not properties:
        raise TicketServiceError(
            'no_active_properties',
            'No tiene inmuebles activos asociados.',
        )
    if len(properties) == 1:
        if property_id is not None and int(property_id) != properties[0].pk:
            raise TicketServiceError(
                'property_not_associated',
                'El inmueble indicado no está asociado a su cuenta.',
                {'property_id': property_id},
            )
        return properties[0]
    if property_id is None:
        raise TicketServiceError(
            'property_id_required',
            'Debe indicar property_id: tiene más de un inmueble activo.',
            {'properties': [{'id': p.pk, 'code': p.code} for p in properties]},
        )
    prop = next((p for p in properties if p.pk == int(property_id)), None)
    if not prop:
        raise TicketServiceError(
            'property_not_associated',
            'El inmueble indicado no está asociado a su cuenta.',
            {'property_id': property_id},
        )
    return prop


def validar_datos_ticket(*, damage_type, damage_type_other, priority, description):
    if damage_type not in dict(Ticket.DamageType.choices):
        raise TicketServiceError('invalid_damage_type', 'Tipo de daño no válido.')
    if damage_type == Ticket.DamageType.OTHER:
        other = (damage_type_other or '').strip()
        if len(other) < 3:
            raise TicketServiceError(
                'damage_type_other_required',
                'Indique la categoría cuando el tipo es Otro.',
            )
    if priority not in dict(Ticket.Priority.choices):
        raise TicketServiceError('invalid_priority', 'Prioridad no válida.')
    if not (description or '').strip():
        raise TicketServiceError('description_required', 'La descripción es obligatoria.')


@transaction.atomic
def crear_ticket_arrendatario(
    tenant,
    *,
    property_id=None,
    description,
    damage_type,
    damage_type_other='',
    priority,
    status,
    title=None,
):
    if tenant.role != CustomUser.Role.TENANT:
        raise TicketServiceError('not_tenant', 'Solo arrendatarios pueden crear tickets.')
    if status not in (Ticket.Status.OPEN, Ticket.Status.DRAFT):
        raise TicketServiceError('invalid_status', 'Estado inicial no permitido.')

    validar_datos_ticket(
        damage_type=damage_type,
        damage_type_other=damage_type_other,
        priority=priority,
        description=description,
    )
    property_obj = resolver_inmueble_ticket(tenant, property_id)
    ticket_title = (title or '').strip() or Ticket.DamageType(damage_type).label

    ticket = Ticket.objects.create(
        property=property_obj,
        tenant=tenant,
        title=ticket_title[:200],
        description=description.strip(),
        damage_type=damage_type,
        damage_type_other=(damage_type_other or '').strip(),
        priority=priority,
        status=status,
    )

    if status == Ticket.Status.OPEN:
        registrar_evento_propiedad(
            property_obj=property_obj,
            event_type=PropertyHistory.EventType.TICKET_CREATED,
            description=f'Ticket {ticket.public_code} abierto por arrendatario',
            created_by=tenant,
            related_user=tenant,
            details={
                'ticket_id': ticket.id,
                'public_code': ticket.public_code,
                'damage_type': damage_type,
                'priority': priority,
            },
        )

    return ticket


def obtener_ticket_arrendatario(tenant, ticket_id):
    try:
        ticket = Ticket.objects.select_related('property', 'tenant').prefetch_related(
            'attachments',
            'status_logs__changed_by',
        ).get(pk=ticket_id, tenant=tenant)
    except Ticket.DoesNotExist:
        raise TicketServiceError('not_found', 'Ticket no encontrado.') from None
    return ticket


@transaction.atomic
def agregar_adjunto_ticket(tenant, ticket_id, image_file):
    ticket = obtener_ticket_arrendatario(tenant, ticket_id)
    if not ticket.is_editable_by_tenant():
        raise TicketServiceError(
            'not_editable',
            'No se pueden agregar adjuntos en el estado actual del ticket.',
        )
    count = ticket.attachments.count()
    if count >= MAX_TICKET_ATTACHMENTS:
        raise TicketServiceError(
            'max_attachments',
            f'Máximo {MAX_TICKET_ATTACHMENTS} archivos por ticket.',
            {'max': MAX_TICKET_ATTACHMENTS, 'current': count},
        )
    ok, err = validar_archivo_imagen(image_file)
    if not ok:
        raise TicketServiceError('invalid_image', err or 'Archivo no válido.')

    attachment = TicketAttachment.objects.create(
        ticket=ticket,
        image=image_file,
        attachment_type=TicketAttachment.AttachmentType.TENANT,
        uploaded_by=tenant,
    )
    return attachment


def notificar_apertura_ticket(ticket, request=None):
    from pot.services.email_service import enviar_notificacion_ticket_apertura

    enviar_notificacion_ticket_apertura(ticket, request)


def _require_staff(user):
    if not user or not user.is_authenticated or not user.is_staff_operative():
        raise TicketServiceError('not_staff', 'Solo personal operativo puede gestionar tickets.')


def _add_business_days(start_dt, days):
    current = start_dt
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def _registrar_log(ticket, *, from_status, to_status, action, changed_by, note=''):
    TicketStatusLog.objects.create(
        ticket=ticket,
        from_status=from_status or '',
        to_status=to_status,
        action=action,
        note=(note or '').strip(),
        changed_by=changed_by,
    )


def obtener_ticket_staff(staff, ticket_id):
    _require_staff(staff)
    try:
        return (
            Ticket.objects.select_related('property', 'tenant')
            .prefetch_related('attachments', 'status_logs')
            .get(pk=ticket_id)
        )
    except Ticket.DoesNotExist:
        raise TicketServiceError('not_found', 'Ticket no encontrado.') from None


def _validar_transicion(ticket, new_status, *, force_close=False):
    if new_status not in dict(Ticket.Status.choices):
        raise TicketServiceError('invalid_status', 'Estado no válido.')
    if ticket.status == new_status:
        raise TicketServiceError('same_status', 'El ticket ya está en ese estado.')
    if ticket.status not in ACTIVE_STATUSES and not force_close:
        raise TicketServiceError(
            'status_not_active',
            'No se puede cambiar el estado de un ticket cerrado, rechazado o borrador.',
        )
    allowed = ALLOWED_STATUS_TRANSITIONS.get(ticket.status, set())
    if new_status not in allowed:
        raise TicketServiceError(
            'invalid_transition',
            f'No se puede pasar de {ticket.get_status_display()} a {Ticket.Status(new_status).label}.',
            {'from': ticket.status, 'to': new_status},
        )
    if new_status == Ticket.Status.IN_PROGRESS:
        raise TicketServiceError(
            'use_assign',
            'Use la asignación de maestro para pasar a En proceso.',
        )
    if new_status == Ticket.Status.REJECTED:
        raise TicketServiceError(
            'use_reject',
            'Use el endpoint de rechazo con motivo obligatorio.',
        )
    if new_status == Ticket.Status.CLOSED:
        if not force_close and not ticket.has_repair_evidence():
            raise TicketServiceError(
                'repair_evidence_required',
                'Debe adjuntar evidencia de reparación antes de cerrar, o usar cierre forzado con justificación.',
            )


@transaction.atomic
def cambiar_estado_ticket(staff, ticket_id, *, new_status, note='', force_close=False, justification=''):
    ticket = obtener_ticket_staff(staff, ticket_id)
    justification = (justification or '').strip()
    if force_close:
        if new_status != Ticket.Status.CLOSED:
            raise TicketServiceError('invalid_status', 'Cierre forzado solo aplica a estado Cerrado.')
        if len(justification) < MIN_FORCE_CLOSE_JUSTIFICATION_LENGTH:
            raise TicketServiceError(
                'justification_required',
                f'La justificación debe tener al menos {MIN_FORCE_CLOSE_JUSTIFICATION_LENGTH} caracteres.',
            )
        if ticket.status not in ACTIVE_STATUSES:
            raise TicketServiceError('status_not_active', 'El ticket no admite cierre forzado.')
    else:
        _validar_transicion(ticket, new_status)

    old_status = ticket.status
    ticket.status = new_status
    update_fields = ['status', 'updated_at']
    if new_status == Ticket.Status.CLOSED:
        if force_close:
            ticket.closed_automatically = False
            update_fields.append('closed_automatically')
        registrar_evento_propiedad(
            property_obj=ticket.property,
            event_type=PropertyHistory.EventType.TICKET_CLOSED,
            description=f'Ticket {ticket.public_code} cerrado por personal',
            created_by=staff,
            related_user=ticket.tenant,
            details={'ticket_id': ticket.id, 'public_code': ticket.public_code, 'force_close': force_close},
        )
    ticket.save(update_fields=update_fields)
    action = TicketStatusLog.Action.FORCE_CLOSE if force_close else TicketStatusLog.Action.STATUS_CHANGE
    log_note = justification if force_close else note
    _registrar_log(
        ticket,
        from_status=old_status,
        to_status=new_status,
        action=action,
        changed_by=staff,
        note=log_note,
    )
    return ticket


@transaction.atomic
def rechazar_ticket(staff, ticket_id, *, reason):
    ticket = obtener_ticket_staff(staff, ticket_id)
    reason = (reason or '').strip()
    if len(reason) < MIN_REJECTION_REASON_LENGTH:
        raise TicketServiceError(
            'reason_too_short',
            f'El motivo de rechazo debe tener al menos {MIN_REJECTION_REASON_LENGTH} caracteres.',
        )
    if ticket.status not in ACTIVE_STATUSES:
        raise TicketServiceError('status_not_active', 'Solo se pueden rechazar tickets activos.')

    old_status = ticket.status
    ticket.status = Ticket.Status.REJECTED
    ticket.rejection_reason = reason
    ticket.save(update_fields=['status', 'rejection_reason', 'updated_at'])
    _registrar_log(
        ticket,
        from_status=old_status,
        to_status=Ticket.Status.REJECTED,
        action=TicketStatusLog.Action.REJECT,
        changed_by=staff,
        note=reason,
    )
    return ticket


@transaction.atomic
def asignar_maestro_ticket(staff, ticket_id, *, contractor_name, visit_note=''):
    ticket = obtener_ticket_staff(staff, ticket_id)
    contractor_name = (contractor_name or '').strip()
    if len(contractor_name) < 2:
        raise TicketServiceError('contractor_required', 'El nombre del maestro/subcontratado es obligatorio.')
    if ticket.status != Ticket.Status.ACCEPTED:
        raise TicketServiceError(
            'invalid_status',
            'Solo se puede asignar maestro a tickets en estado Aceptado.',
        )

    old_status = ticket.status
    ticket.assigned_contractor_name = contractor_name
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.save(update_fields=['assigned_contractor_name', 'status', 'updated_at'])
    note = contractor_name
    if visit_note:
        note = f'{contractor_name} — {visit_note.strip()}'
    _registrar_log(
        ticket,
        from_status=old_status,
        to_status=Ticket.Status.IN_PROGRESS,
        action=TicketStatusLog.Action.ASSIGN,
        changed_by=staff,
        note=note,
    )
    return ticket


@transaction.atomic
def agregar_evidencia_reparacion(staff, ticket_id, image_file):
    ticket = obtener_ticket_staff(staff, ticket_id)
    if ticket.status != Ticket.Status.IN_PROGRESS:
        raise TicketServiceError(
            'invalid_status',
            'La evidencia de reparación solo se adjunta en tickets En proceso.',
        )
    count = ticket.attachments.filter(
        attachment_type=TicketAttachment.AttachmentType.REPAIR_EVIDENCE,
    ).count()
    if count >= MAX_REPAIR_EVIDENCE_ATTACHMENTS:
        raise TicketServiceError(
            'max_repair_evidence',
            f'Máximo {MAX_REPAIR_EVIDENCE_ATTACHMENTS} archivos de evidencia por ticket.',
            {'max': MAX_REPAIR_EVIDENCE_ATTACHMENTS},
        )
    ok, err = validar_archivo_imagen(image_file)
    if not ok:
        raise TicketServiceError('invalid_image', err or 'Archivo no válido.')

    attachment = TicketAttachment.objects.create(
        ticket=ticket,
        image=image_file,
        attachment_type=TicketAttachment.AttachmentType.REPAIR_EVIDENCE,
        uploaded_by=staff,
    )
    if not ticket.confirmation_deadline_at:
        ticket.confirmation_deadline_at = _add_business_days(timezone.now(), 1)
        ticket.save(update_fields=['confirmation_deadline_at', 'updated_at'])
    _registrar_log(
        ticket,
        from_status=ticket.status,
        to_status=ticket.status,
        action=TicketStatusLog.Action.REPAIR_EVIDENCE,
        changed_by=staff,
        note='Evidencia de reparación adjuntada',
    )
    return attachment


def _traffic_light_bucket(ticket, *, stale_cutoff):
    if not ticket.is_pending_resolution():
        return 'grey'
    if ticket.updated_at < stale_cutoff:
        return 'grey'
    if ticket.priority == Ticket.Priority.HIGH:
        return 'red'
    if ticket.priority == Ticket.Priority.MEDIUM:
        return 'yellow'
    return 'green'


def pending_resolution_queryset(base_qs=None):
    """Tickets abiertos, aceptados sin maestro o en proceso (RF-29)."""
    qs = base_qs if base_qs is not None else Ticket.objects.all()
    return qs.filter(
        Q(status=Ticket.Status.OPEN)
        | Q(status=Ticket.Status.IN_PROGRESS)
        | Q(status=Ticket.Status.ACCEPTED, assigned_contractor_name=''),
    )


def calcular_traffic_light(pending_qs):
    stale_cutoff = timezone.now() - timedelta(days=STALE_TICKET_DAYS)
    traffic_light = {'red': 0, 'yellow': 0, 'green': 0, 'grey': 0}
    for ticket in pending_qs.only('status', 'priority', 'updated_at', 'assigned_contractor_name'):
        bucket = _traffic_light_bucket(ticket, stale_cutoff=stale_cutoff)
        traffic_light[bucket] += 1
    return traffic_light


def obtener_estadisticas_tickets(base_qs=None):
    base = base_qs if base_qs is not None else Ticket.objects.all()
    pending_qs = pending_resolution_queryset(base)
    traffic_light = calcular_traffic_light(pending_qs)

    status_counts = dict(
        base.values('status').annotate(c=Count('id')).values_list('status', 'c'),
    )
    return {
        'open': status_counts.get(Ticket.Status.OPEN, 0),
        'accepted': status_counts.get(Ticket.Status.ACCEPTED, 0),
        'in_progress': status_counts.get(Ticket.Status.IN_PROGRESS, 0),
        'rejected': status_counts.get(Ticket.Status.REJECTED, 0),
        'closed': status_counts.get(Ticket.Status.CLOSED, 0),
        'urgent': pending_qs.filter(priority=Ticket.Priority.HIGH).count(),
        'pending_resolution': pending_qs.count(),
        'traffic_light': traffic_light,
    }


def exportar_tickets_queryset(queryset):
    """Filas para export CSV/Excel: encabezados y datos."""
    headers = [
        'Radicado',
        'Inmueble',
        'Arrendatario',
        'Estado',
        'Prioridad',
        'Tipo daño',
        'Maestro',
        'Creado',
    ]
    rows = [headers]
    for t in queryset.select_related('property', 'tenant').order_by('-created_at'):
        tenant_label = ''
        if t.tenant:
            tenant_label = t.tenant.get_full_name() or t.tenant.email
        rows.append([
            t.public_code or str(t.pk),
            t.property.code,
            tenant_label,
            t.get_status_display(),
            t.get_priority_display(),
            t.get_damage_type_display(),
            t.assigned_contractor_name or '',
            t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '',
        ])
    return rows


def notificar_rechazo_ticket(ticket, request=None):
    from pot.services.email_service import enviar_notificacion_ticket_rechazado

    enviar_notificacion_ticket_rechazado(ticket, request)


def _validar_ticket_confirmacion_arrendatario(ticket):
    if ticket.status != Ticket.Status.IN_PROGRESS:
        raise TicketServiceError(
            'invalid_status',
            'Solo puede confirmar o disputar tickets en proceso con evidencia de reparación.',
        )
    if not ticket.has_repair_evidence():
        raise TicketServiceError(
            'no_repair_evidence',
            'Aún no hay evidencia de reparación para revisar.',
        )
    if not ticket.confirmation_deadline_at:
        raise TicketServiceError(
            'confirmation_not_pending',
            'El ticket no está pendiente de confirmación del arrendatario.',
        )
    if ticket.tenant_confirmed_at:
        raise TicketServiceError('already_confirmed', 'El ticket ya fue confirmado.')


@transaction.atomic
def confirmar_reparacion_arrendatario(tenant, ticket_id):
    ticket = obtener_ticket_arrendatario(tenant, ticket_id)
    _validar_ticket_confirmacion_arrendatario(ticket)

    old_status = ticket.status
    now = timezone.now()
    ticket.status = Ticket.Status.CLOSED
    ticket.tenant_confirmed_at = now
    ticket.closed_automatically = False
    ticket.save(
        update_fields=['status', 'tenant_confirmed_at', 'closed_automatically', 'updated_at'],
    )
    _registrar_log(
        ticket,
        from_status=old_status,
        to_status=Ticket.Status.CLOSED,
        action=TicketStatusLog.Action.TENANT_CONFIRM,
        changed_by=tenant,
        note='Reparación confirmada por arrendatario',
    )
    registrar_evento_propiedad(
        property_obj=ticket.property,
        event_type=PropertyHistory.EventType.TICKET_CLOSED,
        description=f'Ticket {ticket.public_code} cerrado por confirmación del arrendatario',
        created_by=tenant,
        related_user=tenant,
        details={
            'ticket_id': ticket.id,
            'public_code': ticket.public_code,
            'tenant_confirmed': True,
        },
    )
    return ticket


@transaction.atomic
def disputar_reparacion_arrendatario(tenant, ticket_id, *, note=''):
    ticket = obtener_ticket_arrendatario(tenant, ticket_id)
    _validar_ticket_confirmacion_arrendatario(ticket)
    note = (note or '').strip()
    if len(note) < MIN_DISPUTE_NOTE_LENGTH:
        raise TicketServiceError(
            'note_too_short',
            f'Indique el motivo de inconformidad (mínimo {MIN_DISPUTE_NOTE_LENGTH} caracteres).',
        )

    old_status = ticket.status
    ticket.status = Ticket.Status.ACCEPTED
    ticket.assigned_contractor_name = ''
    ticket.confirmation_deadline_at = None
    ticket.confirmation_reminder_sent_at = None
    ticket.tenant_confirmed_at = None
    ticket.save(
        update_fields=[
            'status',
            'assigned_contractor_name',
            'confirmation_deadline_at',
            'confirmation_reminder_sent_at',
            'tenant_confirmed_at',
            'updated_at',
        ],
    )
    _registrar_log(
        ticket,
        from_status=old_status,
        to_status=Ticket.Status.ACCEPTED,
        action=TicketStatusLog.Action.TENANT_DISPUTE,
        changed_by=tenant,
        note=note,
    )
    return ticket


def obtener_timeline_ticket(staff, ticket_id):
    ticket = obtener_ticket_staff(staff, ticket_id)
    return ticket.status_logs.select_related('changed_by').order_by('created_at')


@transaction.atomic
def cerrar_tickets_confirmacion_vencida():
    """RF-23: cierra tickets IN_PROGRESS sin respuesta del arrendatario tras el plazo."""
    now = timezone.now()
    qs = Ticket.objects.filter(
        status=Ticket.Status.IN_PROGRESS,
        confirmation_deadline_at__lte=now,
        tenant_confirmed_at__isnull=True,
    ).select_related('property', 'tenant')
    closed = 0
    for ticket in qs:
        if not ticket.has_repair_evidence():
            continue
        old_status = ticket.status
        ticket.status = Ticket.Status.CLOSED
        ticket.closed_automatically = True
        ticket.save(update_fields=['status', 'closed_automatically', 'updated_at'])
        _registrar_log(
            ticket,
            from_status=old_status,
            to_status=Ticket.Status.CLOSED,
            action=TicketStatusLog.Action.AUTO_CLOSE,
            changed_by=None,
            note='Cierre automático por vencimiento del plazo de confirmación (1 día hábil)',
        )
        registrar_evento_propiedad(
            property_obj=ticket.property,
            event_type=PropertyHistory.EventType.TICKET_CLOSED,
            description=f'Ticket {ticket.public_code} cerrado automáticamente',
            created_by=None,
            related_user=ticket.tenant,
            details={
                'ticket_id': ticket.id,
                'public_code': ticket.public_code,
                'closed_automatically': True,
            },
        )
        closed += 1
    return closed


def enviar_recordatorios_confirmacion_ticket(request=None):
    """RF-23: recordatorio ~24 h antes del vencimiento del plazo de confirmación."""
    from pot.services.email_service import enviar_recordatorio_confirmacion_ticket

    now = timezone.now()
    window_start = now + timedelta(hours=CONFIRMATION_REMINDER_HOURS_BEFORE - 1)
    window_end = now + timedelta(hours=CONFIRMATION_REMINDER_HOURS_BEFORE + 1)
    qs = Ticket.objects.filter(
        status=Ticket.Status.IN_PROGRESS,
        confirmation_deadline_at__gte=window_start,
        confirmation_deadline_at__lte=window_end,
        confirmation_reminder_sent_at__isnull=True,
        tenant_confirmed_at__isnull=True,
    ).select_related('tenant', 'property')
    sent = 0
    for ticket in qs:
        if not ticket.has_repair_evidence() or not ticket.tenant:
            continue
        enviar_recordatorio_confirmacion_ticket(ticket, request)
        ticket.confirmation_reminder_sent_at = now
        ticket.save(update_fields=['confirmation_reminder_sent_at', 'updated_at'])
        sent += 1
    return sent


def _obtener_ticket_para_comunicacion(user, ticket_id):
    if user.is_staff_operative():
        return obtener_ticket_staff(user, ticket_id)
    if user.role == CustomUser.Role.TENANT:
        return obtener_ticket_arrendatario(user, ticket_id)
    raise TicketServiceError('not_found', 'Ticket no encontrado.')


def _validar_ticket_abierto_para_mensaje(ticket):
    if ticket.status == Ticket.Status.CLOSED:
        raise TicketServiceError(
            'ticket_closed',
            'No se pueden enviar mensajes en un ticket cerrado.',
        )


def listar_comentarios_ticket(user, ticket_id):
    ticket = _obtener_ticket_para_comunicacion(user, ticket_id)
    return (
        TicketComment.objects.filter(ticket=ticket)
        .select_related('author')
        .order_by('created_at')
    )


@transaction.atomic
def agregar_comentario_ticket(user, ticket_id, *, body):
    ticket = _obtener_ticket_para_comunicacion(user, ticket_id)
    _validar_ticket_abierto_para_mensaje(ticket)
    text = (body or '').strip()
    if len(text) < MIN_COMMENT_LENGTH:
        raise TicketServiceError(
            'message_too_short',
            f'El mensaje debe tener al menos {MIN_COMMENT_LENGTH} carácter.',
        )
    comment = TicketComment.objects.create(
        ticket=ticket,
        author=user,
        body=text,
        message_type=TicketComment.MessageType.NORMAL,
    )
    _notificar_nuevo_comentario(ticket, comment, author=user)
    return comment


@transaction.atomic
def solicitar_info_adicional_ticket(staff, ticket_id, *, message, request=None):
    """RF-25: solicitud de información (solo staff); notificación alta + email."""
    _require_staff(staff)
    ticket = obtener_ticket_staff(staff, ticket_id)
    _validar_ticket_abierto_para_mensaje(ticket)
    if ticket.status == Ticket.Status.DRAFT:
        raise TicketServiceError('not_found', 'Ticket no encontrado.')
    text = (message or '').strip()
    if len(text) < MIN_INFO_REQUEST_LENGTH:
        raise TicketServiceError(
            'message_too_short',
            f'La solicitud debe tener al menos {MIN_INFO_REQUEST_LENGTH} caracteres.',
            {'min_length': MIN_INFO_REQUEST_LENGTH},
        )
    if not ticket.tenant_id:
        raise TicketServiceError(
            'no_tenant',
            'El ticket no tiene arrendatario asociado.',
        )
    comment = TicketComment.objects.create(
        ticket=ticket,
        author=staff,
        body=text,
        message_type=TicketComment.MessageType.INFO_REQUEST,
    )
    from pot.services import notification_service
    from pot.services.email_service import enviar_solicitud_info_ticket

    notification_service.notificar_arrendatario_ticket_comentario(
        ticket,
        comment,
        high_priority=True,
    )
    enviar_solicitud_info_ticket(ticket, text, request=request)
    return comment


def _notificar_nuevo_comentario(ticket, comment, *, author):
    from pot.services import notification_service

    if author.is_staff_operative():
        notification_service.notificar_arrendatario_ticket_comentario(ticket, comment)
    elif author.role == CustomUser.Role.TENANT:
        notification_service.notificar_staff_ticket_comentario(ticket, comment)
