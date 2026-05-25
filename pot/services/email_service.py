from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def _send_html(to_email, subject, template_name, context):
    body_text = context.get('body_text', subject)
    html = render_to_string(template_name, context)
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@localhost')
    msg = EmailMultiAlternatives(subject, body_text, from_email, [to_email])
    msg.attach_alternative(html, 'text/html')
    msg.send(fail_silently=getattr(settings, 'EMAIL_FAIL_SILENTLY', False))


def enviar_credenciales_temporales(user, temp_password, request=None):
    login_url = _abs_url(request, '/login/')
    _send_html(
        user.email,
        'Credenciales de acceso - POT',
        'email/credenciales.html',
        {
            'nombre': user.get_full_name() or user.email,
            'email': user.email,
            'password': temp_password,
            'login_url': login_url,
        },
    )


def enviar_reset_password(user, token, request=None):
    reset_link = _abs_url(request, f'/reset-password/{token}/')
    _send_html(
        user.email,
        'Recuperar contraseña - POT',
        'email/reset_password.html',
        {
            'nombre': user.get_full_name() or user.email,
            'reset_link': reset_link,
            'expiracion': '24 horas',
        },
    )


def enviar_notificacion_rol_cambio(user, nuevo_rol_display, cambiado_por):
    _send_html(
        user.email,
        f'Tu rol ha sido actualizado - POT',
        'email/rol_cambio.html',
        {
            'nombre': user.get_full_name() or user.email,
            'nuevo_rol': nuevo_rol_display,
            'admin': cambiado_por.get_full_name() if cambiado_por else '',
        },
    )


def enviar_notificacion_propiedad_asociada(user, property_obj, request=None):
    panel_url = _abs_url(request, '/dashboard/tenant/')
    _send_html(
        user.email,
        'Nuevo inmueble asociado - POT',
        'email/propiedad_asociada.html',
        {
            'nombre': user.get_full_name() or user.email,
            'inmueble': property_obj.address,
            'tipo': property_obj.get_type_display(),
            'panel_url': panel_url,
        },
    )


def enviar_inventario_pendiente_firma(inventory_obj, request=None):
    url = _abs_url(request, f'/inventories/{inventory_obj.id}/sign/')
    _send_html(
        inventory_obj.tenant.email,
        'Inventario pendiente de firma - POT',
        'email/inventory_pending_sign.html',
        {
            'tenant_name': inventory_obj.tenant.get_full_name() or inventory_obj.tenant.email,
            'property': inventory_obj.property.address,
            'url': url,
        },
    )


def enviar_firma_completada_tenant(inventory_obj):
    _send_html(
        inventory_obj.tenant.email,
        'Inventario firmado - POT',
        'email/inventory_signed_confirmation.html',
        {
            'tenant_name': inventory_obj.tenant.get_full_name() or inventory_obj.tenant.email,
            'property': inventory_obj.property.address,
            'signed_date': inventory_obj.signed_at.strftime('%d/%m/%Y %H:%M') if inventory_obj.signed_at else '',
            'property_code': inventory_obj.property.code,
        },
    )


def enviar_firma_completada_admins(inventory_obj):
    from pot.models import CustomUser

    emails = list(
        CustomUser.objects.filter(role=CustomUser.Role.ADMIN, is_active=True).values_list('email', flat=True)
    )
    if not emails:
        return
    ctx = {
        'tenant_name': inventory_obj.tenant.get_full_name() or inventory_obj.tenant.email,
        'property': inventory_obj.property.address,
        'property_code': inventory_obj.property.code,
        'signed_date': inventory_obj.signed_at.strftime('%d/%m/%Y %H:%M') if inventory_obj.signed_at else '',
    }
    for admin_email in emails:
        _send_html(admin_email, f'Inventario firmado - {inventory_obj.property.code}', 'email/inventory_signed_admin.html', ctx)


def enviar_notificacion_ticket_apertura(ticket, request=None):
    from pot.models import CustomUser

    recipients = CustomUser.objects.filter(
        role__in=(CustomUser.Role.ADMIN, CustomUser.Role.ASSISTANT),
        is_active=True,
    ).values_list('email', flat=True)
    emails = list(recipients)
    if not emails:
        return
    tenant_name = ''
    if ticket.tenant:
        tenant_name = ticket.tenant.get_full_name() or ticket.tenant.email
    ctx = {
        'public_code': ticket.public_code or str(ticket.pk),
        'property_code': ticket.property.code,
        'property_address': ticket.property.address,
        'damage_type': ticket.get_damage_type_display(),
        'priority': ticket.get_priority_display(),
        'description': ticket.description[:500],
        'tenant_name': tenant_name,
        'panel_url': _abs_url(request, '/dashboard/'),
    }
    subject = f'Nuevo ticket {ctx["public_code"]} - {ctx["property_code"]}'
    for email in emails:
        _send_html(email, subject, 'email/ticket_opened_staff.html', ctx)


def enviar_recordatorio_confirmacion_ticket(ticket, request=None):
    if not ticket.tenant or not ticket.tenant.is_active:
        return
    deadline = ''
    if ticket.confirmation_deadline_at:
        deadline = ticket.confirmation_deadline_at.strftime('%d/%m/%Y %H:%M')
    ctx = {
        'public_code': ticket.public_code or str(ticket.pk),
        'property_code': ticket.property.code,
        'property_address': ticket.property.address,
        'confirmation_deadline': deadline,
        'panel_url': _abs_url(request, '/dashboard/tenant/'),
    }
    subject = f'Confirme la reparación del ticket {ctx["public_code"]}'
    _send_html(
        ticket.tenant.email,
        subject,
        'email/ticket_confirmation_reminder.html',
        ctx,
    )


def enviar_solicitud_info_ticket(ticket, message, request=None):
    """RF-25: email selectivo al solicitar información adicional."""
    if not ticket.tenant or not ticket.tenant.is_active:
        return
    ctx = {
        'tenant_name': ticket.tenant.get_full_name() or ticket.tenant.email,
        'public_code': ticket.public_code or str(ticket.pk),
        'property_code': ticket.property.code,
        'property_address': ticket.property.address,
        'message': message[:2000],
        'panel_url': _abs_url(request, '/dashboard/tenant/'),
    }
    subject = f'Información requerida — ticket {ctx["public_code"]}'
    _send_html(
        ticket.tenant.email,
        subject,
        'email/ticket_info_request.html',
        ctx,
    )


def enviar_notificacion_ticket_rechazado(ticket, request=None):
    if not ticket.tenant or not ticket.tenant.is_active:
        return
    ctx = {
        'public_code': ticket.public_code or str(ticket.pk),
        'property_code': ticket.property.code,
        'property_address': ticket.property.address,
        'rejection_reason': ticket.rejection_reason,
        'panel_url': _abs_url(request, '/dashboard/'),
    }
    subject = f'Ticket {ctx["public_code"]} rechazado'
    _send_html(ticket.tenant.email, subject, 'email/ticket_rejected_tenant.html', ctx)


def enviar_observaciones_inventario_admin(inventory_obj, observation_text):
    from pot.models import CustomUser

    emails = list(
        CustomUser.objects.filter(role=CustomUser.Role.ADMIN, is_active=True).values_list('email', flat=True)
    )
    if not emails:
        return
    ctx = {
        'property_code': inventory_obj.property.code,
        'tenant_email': inventory_obj.tenant.email,
        'observation_text': observation_text,
    }
    for admin_email in emails:
        _send_html(
            admin_email,
            f'Observaciones inventario - {inventory_obj.property.code}',
            'email/inventory_observations_admin.html',
            ctx,
        )


def _abs_url(request, path):
    if request:
        return request.build_absolute_uri(path)
    base = getattr(settings, 'POT_PUBLIC_BASE_URL', '').rstrip('/')
    if base:
        return f'{base}{path}'
    return path
