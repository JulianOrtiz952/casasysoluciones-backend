from django.db import transaction

from pot.models import CustomUser, Property, PropertyHistory, Ticket, TicketAttachment
from pot.services.inventory_service import validar_archivo_imagen
from pot.services.property_service import registrar_evento_propiedad

MAX_TICKET_ATTACHMENTS = 5


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
    ticket.status = Ticket.Status.CLOSED
    ticket.tenant_confirmed_at = timezone.now()
    ticket.save()
    
    registrar_evento_propiedad(
        property_obj=ticket.property,
        event_type=PropertyHistory.EventType.TICKET_CLOSED,
        description=f'Ticket {ticket.public_code} confirmado y cerrado por el inquilino',
        created_by=user,
        related_user=ticket.tenant,
        details={
            'ticket_id': ticket.id,
            'public_code': ticket.public_code,
            'confirmed_at': ticket.tenant_confirmed_at.isoformat(),
        },
    )
    return ticket


@transaction.atomic
def reportar_problema_reparacion(user, ticket_id, reason):
    ticket = obtener_ticket_por_usuario(user, ticket_id)
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
    return ticket

