from django.db import transaction
from django.utils import timezone

from pot.models import LeaseContract, Ticket, UserPropertyAssociation
from pot.services.property_service import registrar_evento_propiedad
from pot.services.user_service import UserServiceError, desactivar_usuario, desasociar_inmueble_arrendatario


class ContractServiceError(Exception):
    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def _fecha_inicio_contrato(property_obj, tenant):
    assoc = (
        UserPropertyAssociation.objects.filter(
            user=tenant,
            property=property_obj,
            dissociated_at__isnull=True,
        )
        .order_by('associated_at')
        .first()
    )
    if assoc:
        return assoc.associated_at.date()
    return timezone.localdate()


def obtener_o_crear_contrato_activo(property_obj, tenant, *, final_inventory=None):
    contract = LeaseContract.objects.filter(
        property=property_obj,
        tenant=tenant,
        status=LeaseContract.Status.ACTIVE,
    ).first()
    if contract:
        if final_inventory and not contract.final_inventory_id:
            contract.final_inventory = final_inventory
            contract.save(update_fields=['final_inventory', 'updated_at'])
        return contract

    return LeaseContract.objects.create(
        property=property_obj,
        tenant=tenant,
        start_date=_fecha_inicio_contrato(property_obj, tenant),
        status=LeaseContract.Status.ACTIVE,
        final_inventory=final_inventory,
    )


def tickets_del_contrato(contract):
    qs = Ticket.objects.filter(
        property=contract.property,
        tenant=contract.tenant,
    ).exclude(status=Ticket.Status.DRAFT)
    if contract.start_date:
        qs = qs.filter(created_at__date__gte=contract.start_date)
    if contract.end_date:
        qs = qs.filter(created_at__date__lte=contract.end_date)
    return qs.order_by('-created_at')


@transaction.atomic
def cerrar_contrato(staff, contract_id, *, end_date=None, deactivate_tenant=False, notes=''):
    contract = LeaseContract.objects.select_related('property', 'tenant').filter(pk=contract_id).first()
    if not contract:
        raise ContractServiceError('contract_not_found', 'Contrato no encontrado.')
    if contract.status != LeaseContract.Status.ACTIVE:
        raise ContractServiceError('contract_not_active', 'El contrato no está activo.')

    close_date = end_date or timezone.localdate()
    if close_date < contract.start_date:
        raise ContractServiceError(
            'invalid_end_date',
            'La fecha de cierre no puede ser anterior al inicio del contrato.',
        )

    open_tickets = Ticket.objects.filter(
        property=contract.property,
        tenant=contract.tenant,
        status__in=[
            Ticket.Status.OPEN,
            Ticket.Status.ACCEPTED,
            Ticket.Status.IN_PROGRESS,
        ],
    ).exists()
    if open_tickets:
        raise ContractServiceError(
            'open_tickets',
            'No se puede cerrar el contrato mientras existan tickets abiertos para este inmueble y arrendatario.',
        )

    contract.status = LeaseContract.Status.CLOSED
    contract.end_date = close_date
    contract.closed_at = timezone.now()
    contract.closed_by = staff
    contract.notes = (notes or '').strip()
    contract.save(
        update_fields=['status', 'end_date', 'closed_at', 'closed_by', 'notes', 'updated_at'],
    )

    tenant = contract.tenant
    property_obj = contract.property
    try:
        desasociar_inmueble_arrendatario(tenant, property_obj, staff)
    except UserServiceError as exc:
        if exc.code != 'association_not_found':
            raise ContractServiceError(exc.code, exc.message, exc.details) from exc

    if deactivate_tenant:
        has_other = UserPropertyAssociation.objects.filter(
            user=tenant,
            dissociated_at__isnull=True,
        ).exists()
        if not has_other and tenant.is_active:
            desactivar_usuario(tenant, staff, confirm=True)

    from pot.models import PropertyHistory

    registrar_evento_propiedad(
        property_obj,
        PropertyHistory.EventType.TENANT_DISSOCIATED,
        f'Contrato de arriendo cerrado — {tenant.email}',
        created_by=staff,
        related_user=tenant,
        details={
            'contract_id': contract.pk,
            'end_date': close_date.isoformat(),
            'deactivate_tenant': deactivate_tenant,
        },
    )
    return contract
