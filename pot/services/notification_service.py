from django.utils import timezone

from pot.models import CustomUser, Notification, Ticket, TicketComment


def crear_notificacion(
    *,
    recipient,
    notification_type,
    title,
    body='',
    priority=Notification.Priority.NORMAL,
    ticket=None,
    ticket_comment=None,
):
    return Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        priority=priority,
        title=title,
        body=(body or '').strip(),
        ticket=ticket,
        ticket_comment=ticket_comment,
    )


def listar_notificaciones_usuario(user, *, unread_only=False):
    qs = Notification.objects.filter(recipient=user).select_related('ticket', 'ticket_comment')
    if unread_only:
        qs = qs.filter(is_read=False)
    return qs


def contar_no_leidas_usuario(user):
    return Notification.objects.filter(recipient=user, is_read=False).count()


def marcar_notificacion_leida(user, notification_id):
    try:
        notification = Notification.objects.get(pk=notification_id, recipient=user)
    except Notification.DoesNotExist:
        return None
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=['is_read', 'read_at'])
    return notification


def notificar_staff_ticket_comentario(ticket, comment):
    """In-app a admin y asistentes activos (sin email)."""
    staff_users = CustomUser.objects.filter(
        role__in=(CustomUser.Role.ADMIN, CustomUser.Role.ASSISTANT),
        is_active=True,
    )
    code = ticket.public_code or str(ticket.pk)
    author_name = ''
    if comment.author:
        author_name = comment.author.get_full_name() or comment.author.email
    title = f'Nuevo mensaje en ticket {code}'
    body = f'{author_name}: {comment.body[:300]}'
    for staff in staff_users:
        crear_notificacion(
            recipient=staff,
            notification_type=Notification.NotificationType.TICKET_COMMENT,
            title=title,
            body=body,
            priority=Notification.Priority.NORMAL,
            ticket=ticket,
            ticket_comment=comment,
        )


def notificar_arrendatario_ticket_comentario(ticket, comment, *, high_priority=False):
    if not ticket.tenant or not ticket.tenant.is_active:
        return
    code = ticket.public_code or str(ticket.pk)
    author_name = ''
    if comment.author:
        author_name = comment.author.get_full_name() or comment.author.email
    priority = (
        Notification.Priority.HIGH
        if high_priority
        else Notification.Priority.NORMAL
    )
    ntype = (
        Notification.NotificationType.TICKET_INFO_REQUEST
        if high_priority
        else Notification.NotificationType.TICKET_COMMENT
    )
    title = (
        f'Información requerida — ticket {code}'
        if high_priority
        else f'Nuevo mensaje en ticket {code}'
    )
    crear_notificacion(
        recipient=ticket.tenant,
        notification_type=ntype,
        title=title,
        body=f'{author_name}: {comment.body[:500]}',
        priority=priority,
        ticket=ticket,
        ticket_comment=comment,
    )
