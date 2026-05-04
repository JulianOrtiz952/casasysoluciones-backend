from pot.models import Property, PropertyHistory, UserPropertyAssociation


def generar_codigo_propiedad():
    last = Property.objects.order_by('-id').first()
    n = (last.id + 1) if last else 1
    return f'PRO-{n:05d}'


def registrar_evento_propiedad(
    property_obj,
    event_type,
    description,
    created_by=None,
    related_user=None,
    details=None,
):
    PropertyHistory.objects.create(
        property=property_obj,
        event_type=event_type,
        description=description,
        created_by=created_by,
        related_user=related_user,
        details=details or {},
    )


def obtener_historial_filtrado(property_obj, fecha_desde=None, fecha_hasta=None, tipo_evento=None, tenant_id=None):
    qs = property_obj.history.all()
    if fecha_desde:
        qs = qs.filter(created_at__date__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(created_at__date__lte=fecha_hasta)
    if tipo_evento:
        qs = qs.filter(event_type=tipo_evento)
    if tenant_id:
        qs = qs.filter(related_user_id=tenant_id)
    return qs.order_by('-created_at')


def obtener_arrendatario_actual(property_obj):
    assoc = UserPropertyAssociation.objects.filter(property=property_obj, dissociated_at__isnull=True).first()
    return assoc.user if assoc else None
