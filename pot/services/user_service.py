from django.db import transaction
from django.utils import timezone

from pot.models import CustomUser, Inventory, Property, PropertyHistory, Ticket, UserAudit, UserPropertyAssociation
from pot.services.auth_service import generar_password_temporal
from pot.services.email_service import (
    enviar_credenciales_temporales,
    enviar_notificacion_propiedad_asociada,
    enviar_notificacion_rol_cambio,
)
from pot.services.property_service import registrar_evento_propiedad


class UserServiceError(Exception):
    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def _validar_inmuebles_disponibles(properties):
    ocupados = []
    for prop in properties:
        if UserPropertyAssociation.objects.filter(property=prop, dissociated_at__isnull=True).exists():
            ocupados.append(prop.code)
    if ocupados:
        raise UserServiceError(
            'property_already_rented',
            'Uno o más inmuebles ya tienen arrendatario activo.',
            {'property_codes': ocupados},
        )


def _asociar_inmuebles(user, properties, created_by, request=None, *, notify=False):
    for prop in properties:
        UserPropertyAssociation.objects.create(user=user, property=prop, created_by=created_by)
        prop.status = Property.Status.RENTED
        prop.save(update_fields=['status', 'updated_at'])
        registrar_evento_propiedad(
            prop,
            PropertyHistory.EventType.TENANT_ASSOCIATED,
            f'Asociado {user.email}',
            created_by=created_by,
            related_user=user,
        )
        if notify:
            enviar_notificacion_propiedad_asociada(user, prop, request)


def usuario_tiene_tickets_abiertos(user):
    return Ticket.objects.filter(tenant=user, status=Ticket.Status.OPEN).exists()


def usuario_tiene_inventarios_pendientes(user):
    return Inventory.objects.filter(
        tenant=user,
        status__in=[
            Inventory.Status.PENDING_SIGNATURE,
            Inventory.Status.IN_PROGRESS,
            Inventory.Status.OBSERVATIONS_PENDING,
        ],
    ).exists()


def crear_arrendatario(created_by, *, email, property_ids, request=None, send_credentials=True, **profile_fields):
    properties = list(Property.objects.filter(pk__in=property_ids))
    if not properties:
        raise UserServiceError(
            'properties_required',
            'Debe asociar al menos un inmueble al arrendatario.',
        )
    if len(properties) != len(set(property_ids)):
        raise UserServiceError('invalid_properties', 'Uno o más inmuebles no existen.')

    if CustomUser.objects.filter(email__iexact=email).exists():
        raise UserServiceError('email_exists', 'Este correo ya está registrado.')

    document_number = profile_fields.get('document_number')
    if document_number and CustomUser.objects.filter(document_number=document_number).exists():
        raise UserServiceError('document_exists', 'Este número de documento ya está registrado.')

    _validar_inmuebles_disponibles(properties)
    temp_password = generar_password_temporal()

    with transaction.atomic():
        user = CustomUser.objects.create_user(
            email=email,
            password=temp_password,
            role=CustomUser.Role.TENANT,
            password_changed=False,
            **profile_fields,
        )
        _asociar_inmuebles(user, properties, created_by, request)
        UserAudit.objects.create(
            user=user,
            action='CREATED',
            details={'email': user.email, 'role': user.role, 'property_ids': property_ids},
            changed_by=created_by,
        )

    if send_credentials:
        enviar_credenciales_temporales(user, temp_password, request)
    return user, temp_password


def actualizar_usuario(target, updated_by, **fields):
    allowed = {'first_name', 'last_name', 'phone', 'document_type', 'document_number'}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return target

    if 'document_number' in updates and updates['document_number']:
        exists = CustomUser.objects.filter(document_number=updates['document_number']).exclude(pk=target.pk).exists()
        if exists:
            raise UserServiceError('document_exists', 'Este número de documento ya está registrado.')

    if 'email' in fields:
        raise UserServiceError('email_immutable', 'El correo no puede modificarse por API.')

    for key, value in updates.items():
        setattr(target, key, value)
    target.save(update_fields=[*updates.keys(), 'updated_at'])
    UserAudit.objects.create(
        user=target,
        action='UPDATED',
        details=updates,
        changed_by=updated_by,
    )
    return target


def cambiar_rol_usuario(target, new_role, changed_by, *, confirm=False, request=None):
    if new_role == target.role:
        return target, None

    warnings = []
    if not confirm and usuario_tiene_tickets_abiertos(target):
        warnings.append('open_tickets')

    if warnings:
        return None, {
            'requires_confirm': True,
            'warnings': warnings,
            'message': 'El usuario tiene tickets abiertos. Confirme el cambio de rol.',
        }

    old_role = target.role
    target.role = new_role
    target.save(update_fields=['role', 'updated_at'])
    UserAudit.objects.create(
        user=target,
        action='ROLE_CHANGED',
        details={'from': old_role, 'to': new_role},
        changed_by=changed_by,
    )
    enviar_notificacion_rol_cambio(target, target.get_role_display(), changed_by)
    return target, None


def asociar_inmueble_arrendatario(tenant, property_obj, created_by, request=None, *, notify=True):
    if tenant.role != CustomUser.Role.TENANT:
        raise UserServiceError('not_tenant', 'Solo se pueden asociar inmuebles a arrendatarios.')

    if UserPropertyAssociation.objects.filter(property=property_obj, dissociated_at__isnull=True).exists():
        raise UserServiceError(
            'property_already_rented',
            'El inmueble ya tiene un arrendatario activo.',
            {'property_code': property_obj.code},
        )

    UserPropertyAssociation.objects.create(user=tenant, property=property_obj, created_by=created_by)
    property_obj.status = Property.Status.RENTED
    property_obj.save(update_fields=['status', 'updated_at'])
    registrar_evento_propiedad(
        property_obj,
        PropertyHistory.EventType.TENANT_ASSOCIATED,
        f'Asociado {tenant.email}',
        created_by=created_by,
        related_user=tenant,
    )
    if notify:
        enviar_notificacion_propiedad_asociada(tenant, property_obj, request)
    UserAudit.objects.create(
        user=tenant,
        action='PROPERTY_ASSOCIATED',
        details={'property_id': property_obj.pk, 'code': property_obj.code},
        changed_by=created_by,
    )
    return tenant


def desasociar_inmueble_arrendatario(tenant, property_obj, changed_by):
    assoc = UserPropertyAssociation.objects.filter(
        user=tenant,
        property=property_obj,
        dissociated_at__isnull=True,
    ).first()
    if not assoc:
        raise UserServiceError('association_not_found', 'No existe una asociación activa con ese inmueble.')

    assoc.dissociated_at = timezone.now()
    assoc.save(update_fields=['dissociated_at'])
    property_obj.status = Property.Status.AVAILABLE
    property_obj.save(update_fields=['status', 'updated_at'])
    registrar_evento_propiedad(
        property_obj,
        PropertyHistory.EventType.TENANT_DISSOCIATED,
        f'Desasociado {tenant.email}',
        created_by=changed_by,
        related_user=tenant,
    )
    UserAudit.objects.create(
        user=tenant,
        action='PROPERTY_DISSOCIATED',
        details={'property_id': property_obj.pk, 'code': property_obj.code},
        changed_by=changed_by,
    )
    return tenant


def desactivar_usuario(target, changed_by, *, confirm=False):
    if not target.is_active:
        raise UserServiceError('already_inactive', 'El usuario ya está desactivado.')

    warnings = []
    if not confirm:
        if usuario_tiene_tickets_abiertos(target):
            warnings.append('open_tickets')
        if usuario_tiene_inventarios_pendientes(target):
            warnings.append('pending_inventories')

    if warnings:
        return None, {
            'requires_confirm': True,
            'warnings': warnings,
            'message': 'El usuario tiene tickets o inventarios pendientes. Confirme la desactivación.',
        }

    target.is_active = False
    target.save(update_fields=['is_active', 'updated_at'])
    now = timezone.now()
    for assoc in UserPropertyAssociation.objects.filter(user=target, dissociated_at__isnull=True):
        assoc.dissociated_at = now
        assoc.save(update_fields=['dissociated_at'])
        prop = assoc.property
        prop.status = Property.Status.AVAILABLE
        prop.save(update_fields=['status', 'updated_at'])
        registrar_evento_propiedad(
            prop,
            PropertyHistory.EventType.TENANT_DISSOCIATED,
            f'Desasociado {target.email} (usuario desactivado)',
            created_by=changed_by,
            related_user=target,
        )

    UserAudit.objects.create(user=target, action='DEACTIVATED', details={}, changed_by=changed_by)
    return target, None


def estadisticas_usuarios():
    qs = CustomUser.objects.all()
    by_role = {role: qs.filter(role=role).count() for role, _ in CustomUser.Role.choices}
    return {
        'total': qs.count(),
        'active': qs.filter(is_active=True).count(),
        'inactive': qs.filter(is_active=False).count(),
        'by_role': by_role,
        'tenants_with_properties': CustomUser.objects.filter(
            role=CustomUser.Role.TENANT,
            property_associations__dissociated_at__isnull=True,
        )
        .distinct()
        .count(),
    }
