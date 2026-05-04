import secrets

from django.utils import timezone

from pot.models import InventorySignature
from pot.services.email_service import enviar_firma_completada_admins, enviar_firma_completada_tenant
from pot.services.inventory_service import registrar_evento_firma_en_propiedad


def generar_token_firma():
    return secrets.token_urlsafe(32)


def registrar_firma_inventario(inventory_obj, tenant_obj, request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip_address = x_forwarded_for.split(',')[0].strip()
    else:
        ip_address = request.META.get('REMOTE_ADDR') or '0.0.0.0'
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    token = generar_token_firma()
    InventorySignature.objects.create(
        inventory=inventory_obj,
        signed_by=tenant_obj,
        signature_token=token,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    inventory_obj.status = inventory_obj.Status.ACCEPTED
    inventory_obj.signed_at = timezone.now()
    inventory_obj.signed_by = tenant_obj
    inventory_obj.signature_token = token
    inventory_obj.save(update_fields=['status', 'signed_at', 'signed_by', 'signature_token', 'updated_at'])
    return token


def notificar_firma_completada(inventory_obj):
    enviar_firma_completada_tenant(inventory_obj)
    enviar_firma_completada_admins(inventory_obj)


def completar_flujo_firma(inventory_obj, tenant_obj, request):
    registrar_firma_inventario(inventory_obj, tenant_obj, request)
    registrar_evento_firma_en_propiedad(inventory_obj)
    notificar_firma_completada(inventory_obj)
