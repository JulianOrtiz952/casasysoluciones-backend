from django.db import transaction

from pot.models import CustomUser, Property, PropertyHistory, Ticket, TicketAttachment, TicketHistory
from pot.services.inventory_service import validar_archivo_imagen
from pot.services.property_service import registrar_evento_propiedad

MAX_TICKET_ATTACHMENTS = 10


def registrar_historial_ticket(ticket, action, description, created_by=None, old_value='', new_value=''):
    """Register a history event on a ticket."""
    return TicketHistory.objects.create(
        ticket=ticket,
        action=action,
        description=description,
        old_value=old_value or '',
        new_value=new_value or '',
        created_by=created_by,
    )


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

    registrar_historial_ticket(
        ticket,
        TicketHistory.Action.CREATED,
        f'Ticket creado por {tenant.email}',
        created_by=tenant,
        new_value=status,
    )

    return ticket


def obtener_ticket_arrendatario(tenant, ticket_id):
    try:
        ticket = Ticket.objects.select_related('property', 'tenant').prefetch_related(
            'attachments',
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
        uploaded_by=tenant,
    )
    return attachment


def notificar_apertura_ticket(ticket, request=None):
    from pot.services.email_service import enviar_notificacion_ticket_apertura

    enviar_notificacion_ticket_apertura(ticket, request)


from django.utils import timezone

def obtener_ticket_por_usuario(user, ticket_id):
    try:
        if user.is_staff_operative():
            return Ticket.objects.select_related('property', 'tenant').prefetch_related(
                'attachments'
            ).get(pk=ticket_id)
        else:
            return Ticket.objects.select_related('property', 'tenant').prefetch_related(
                'attachments'
            ).get(pk=ticket_id, tenant=user)
    except Ticket.DoesNotExist:
        raise TicketServiceError('not_found', 'Ticket no encontrado.') from None


@transaction.atomic
def confirmar_ticket_reparacion(user, ticket_id):
    ticket = obtener_ticket_por_usuario(user, ticket_id)

    # Tickets de Cierre de Contrato: solo admin/asistente pueden aprobar
    is_closure = ticket.damage_type == Ticket.DamageType.CLOSURE
    if is_closure:
        if not user.is_staff_operative():
            raise TicketServiceError(
                'not_authorized',
                'Solo un administrador o asistente puede aprobar un ticket de Cierre de Contrato.',
            )
    else:
        # La aprobación de tickets de reparación depende únicamente del administrador
        raise TicketServiceError(
            'not_authorized',
            'La aprobación de tickets de reparación depende únicamente del administrador.',
        )

    old_status = ticket.status
    ticket.status = Ticket.Status.CLOSED
    ticket.tenant_confirmed_at = timezone.now()
    ticket.save()

    if is_closure:
        description_close = f'Ticket {ticket.public_code} aprobado y cerrado por {user.email} (administrador/asistente). Arrendamiento finalizado.'
    else:
        description_close = f'Ticket {ticket.public_code} confirmado y cerrado por el inquilino'

    registrar_evento_propiedad(
        property_obj=ticket.property,
        event_type=PropertyHistory.EventType.TICKET_CLOSED,
        description=description_close,
        created_by=user,
        related_user=ticket.tenant,
        details={
            'ticket_id': ticket.id,
            'public_code': ticket.public_code,
            'confirmed_at': ticket.tenant_confirmed_at.isoformat(),
        },
    )
    registrar_historial_ticket(
        ticket,
        TicketHistory.Action.CONFIRMED,
        f'Cierre aprobado por {user.email}' if is_closure else f'Reparación confirmada por {user.email}',
        created_by=user,
        old_value=old_status,
        new_value=Ticket.Status.CLOSED,
    )

    # Si es ticket de cierre, desasociar el inmueble del inquilino
    if is_closure and ticket.tenant:
        try:
            from pot.services.user_service import desasociar_inmueble_arrendatario
            desasociar_inmueble_arrendatario(ticket.tenant, ticket.property, user)
        except Exception as exc:
            # Loguear pero no bloquear el cierre del ticket
            import logging
            logging.getLogger(__name__).error(
                'Error al desasociar inmueble tras cierre de contrato: %s', exc
            )

    return ticket


@transaction.atomic
def reportar_problema_reparacion(user, ticket_id, reason):
    ticket = obtener_ticket_por_usuario(user, ticket_id)
    old_status = ticket.status
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.rejection_reason = reason.strip()
    ticket.save()
    
    registrar_evento_propiedad(
        property_obj=ticket.property,
        event_type=PropertyHistory.EventType.STATUS_CHANGE,
        description=f'Inquilino reportó problema con reparación del ticket {ticket.public_code}: {reason}',
        created_by=user,
        related_user=ticket.tenant,
        details={
            'ticket_id': ticket.id,
            'public_code': ticket.public_code,
            'rejection_reason': reason,
        },
    )
    registrar_historial_ticket(
        ticket,
        TicketHistory.Action.PROBLEM_REPORTED,
        f'Problema reportado por {user.email}: {reason}',
        created_by=user,
        old_value=old_status,
        new_value=Ticket.Status.IN_PROGRESS,
    )
    return ticket


@transaction.atomic
def agregar_adjunto_tecnico(user, ticket_id, image_file):
    """Allow the assigned technician to upload repair evidence."""
    try:
        ticket = Ticket.objects.prefetch_related(
            'attachments', 'assigned_technicians',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise TicketServiceError('not_found', 'Ticket no encontrado.') from None

    if not ticket.assigned_technicians.filter(id=user.pk).exists():
        raise TicketServiceError(
            'not_assigned',
            'Solo el técnico asignado puede subir evidencias a este ticket.',
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
        uploaded_by=user,
    )
    registrar_historial_ticket(
        ticket,
        TicketHistory.Action.ATTACHMENT_ADDED,
        f'Evidencia de reparación agregada por técnico {user.email}',
        created_by=user,
    )
    return attachment
    
@transaction.atomic
def completar_ticket_tecnico(user, ticket_id):
    """Mark a ticket as completed by the assigned technician.
    Requires at least one attachment uploaded by the technician."""
    try:
        ticket = Ticket.objects.select_related(
            'property', 'tenant'
        ).prefetch_related('assigned_technicians').get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise TicketServiceError('not_found', 'Ticket no encontrado.') from None

    if not ticket.assigned_technicians.filter(id=user.pk).exists():
        raise TicketServiceError(
            'not_assigned',
            'Solo el técnico asignado puede completar este ticket.',
        )

    tech_attachments = ticket.attachments.filter(uploaded_by__in=ticket.assigned_technicians.all()).count()
    if tech_attachments == 0:
        raise TicketServiceError(
            'no_evidence',
            'Debe adjuntar al menos una evidencia de la reparación antes de completar el ticket.',
        )

    # Validar si hubo rechazo previo del administrador
    last_rejection = ticket.history.filter(
        action=TicketHistory.Action.STATUS_CHANGE,
        new_value=Ticket.Status.IN_PROGRESS,
        description__icontains='reparación rechazada por administrador'
    ).first()
    if last_rejection:
        new_attachments_count = ticket.attachments.filter(
            uploaded_by__in=ticket.assigned_technicians.all(),
            uploaded_at__gt=last_rejection.created_at
        ).count()
        if new_attachments_count == 0:
            raise TicketServiceError(
                'no_new_evidence',
                'Debe adjuntar al menos una nueva evidencia de la reparación después del rechazo del administrador.'
            )

    old_status = ticket.status
    ticket.status = Ticket.Status.PENDING_ADMIN
    ticket.save()

    registrar_evento_propiedad(
        property_obj=ticket.property,
        event_type=PropertyHistory.EventType.STATUS_CHANGE,
        description=f'Técnico {user.email} completó la reparación del ticket {ticket.public_code}. Estado: Pendiente de Aprobación Admin',
        created_by=user,
        related_user=ticket.tenant,
        details={
            'ticket_id': ticket.id,
            'public_code': ticket.public_code,
            'technician': user.email,
        },
    )
    is_closure = ticket.damage_type == Ticket.DamageType.CLOSURE
    pending_msg = (
        f'Inventario final completado por técnico {user.email}. Pendiente aprobación del administrador.'
        if is_closure
        else f'Reparación completada por técnico {user.email}. Pendiente visto bueno del administrador.'
    )
    registrar_historial_ticket(
        ticket,
        TicketHistory.Action.COMPLETED_BY_TECHNICIAN,
        pending_msg,
        created_by=user,
        old_value=old_status,
        new_value=Ticket.Status.PENDING_ADMIN,
    )
    return ticket


@transaction.atomic
def aprobar_reparacion_admin(user, ticket_id):
    """Allow an admin or assistant to approve the completed ticket."""
    if not user.is_staff_operative():
        raise TicketServiceError(
            'not_authorized',
            'Solo administradores o asistentes pueden aprobar la reparación.',
        )

    ticket = obtener_ticket_por_usuario(user, ticket_id)
    if ticket.status != Ticket.Status.PENDING_ADMIN:
        raise TicketServiceError(
            'invalid_status',
            'El ticket debe estar en estado Pendiente de Admin para ser aprobado.',
        )

    old_status = ticket.status
    
    # Si es ticket de cierre (CLOSURE), la aprobación admin lo cierra directamente
    if ticket.damage_type == Ticket.DamageType.CLOSURE:
        return confirmar_ticket_reparacion(user, ticket_id)

    ticket.status = Ticket.Status.CLOSED
    ticket.tenant_confirmed_at = timezone.now()
    ticket.save()

    registrar_evento_propiedad(
        property_obj=ticket.property,
        event_type=PropertyHistory.EventType.TICKET_CLOSED,
        description=f'Administrador {user.email} aprobó la reparación y cerró el ticket {ticket.public_code}.',
        created_by=user,
        related_user=ticket.tenant,
        details={
            'ticket_id': ticket.id,
            'public_code': ticket.public_code,
            'admin': user.email,
            'confirmed_at': ticket.tenant_confirmed_at.isoformat(),
        },
    )

    registrar_historial_ticket(
        ticket,
        TicketHistory.Action.CONFIRMED,
        f'Reparación aprobada y ticket cerrado por administrador {user.email}.',
        created_by=user,
        old_value=old_status,
        new_value=Ticket.Status.CLOSED,
    )
    return ticket


@transaction.atomic
def rechazar_reparacion_admin(user, ticket_id, reason):
    """Allow an admin or assistant to reject the completed ticket work, sending it back to IN_PROGRESS."""
    if not user.is_staff_operative():
        raise TicketServiceError(
            'not_authorized',
            'Solo administradores o asistentes pueden rechazar la reparación.',
        )

    ticket = obtener_ticket_por_usuario(user, ticket_id)
    if ticket.status != Ticket.Status.PENDING_ADMIN:
        raise TicketServiceError(
            'invalid_status',
            'El ticket debe estar en estado Pendiente de Admin para ser rechazado.',
        )

    cleaned_reason = (reason or '').strip()
    if not cleaned_reason:
        raise TicketServiceError(
            'reason_required',
            'La descripción del rechazo es obligatoria.',
        )

    old_status = ticket.status
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.rejection_reason = cleaned_reason
    ticket.save()

    registrar_evento_propiedad(
        property_obj=ticket.property,
        event_type=PropertyHistory.EventType.STATUS_CHANGE,
        description=f'Administrador {user.email} rechazó la reparación del ticket {ticket.public_code}. Retorna a En Proceso. Motivo: {cleaned_reason}',
        created_by=user,
        related_user=ticket.tenant,
        details={
            'ticket_id': ticket.id,
            'public_code': ticket.public_code,
            'rejection_reason': cleaned_reason,
            'admin': user.email,
        },
    )

    registrar_historial_ticket(
        ticket,
        TicketHistory.Action.STATUS_CHANGE,
        f'Reparación rechazada por administrador {user.email}. Motivo: {cleaned_reason}',
        created_by=user,
        old_value=old_status,
        new_value=Ticket.Status.IN_PROGRESS,
    )
    return ticket
@transaction.atomic
def rechazar_ticket_por_admin(user, ticket_id, reason):
    """Allow an admin or assistant to reject a ticket with a mandatory reason."""
    if not user.is_staff_operative():
        raise TicketServiceError(
            'not_authorized',
            'Solo administradores o asistentes pueden rechazar tickets.',
        )

    ticket = obtener_ticket_por_usuario(user, ticket_id)

    cleaned_reason = (reason or '').strip()
    if not cleaned_reason:
        raise TicketServiceError(
            'reason_required',
            'La descripción del rechazo es obligatoria.',
        )

    old_status = ticket.status
    ticket.status = Ticket.Status.REJECTED
    ticket.rejection_reason = cleaned_reason
    ticket.save()

    is_closure = ticket.damage_type == Ticket.DamageType.CLOSURE
    description_reject = (
        f'Solicitud de cierre del ticket {ticket.public_code} rechazada por administrador {user.email}. Motivo: {cleaned_reason}'
        if is_closure
        else f'Ticket {ticket.public_code} rechazado por {user.email}. Motivo: {cleaned_reason}'
    )

    registrar_evento_propiedad(
        property_obj=ticket.property,
        event_type=PropertyHistory.EventType.STATUS_CHANGE,
        description=description_reject,
        created_by=user,
        related_user=ticket.tenant,
        details={
            'ticket_id': ticket.id,
            'public_code': ticket.public_code,
            'rejection_reason': cleaned_reason,
            'old_status': old_status,
            'new_status': Ticket.Status.REJECTED,
        },
    )

    registrar_historial_ticket(
        ticket,
        TicketHistory.Action.STATUS_CHANGE,
        f'Ticket rechazado por {user.email}. Motivo: {cleaned_reason}',
        created_by=user,
        old_value=old_status,
        new_value=Ticket.Status.REJECTED,
    )

    return ticket


