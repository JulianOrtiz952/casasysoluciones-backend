from django.db.models import Count

from pot.models import Property, PropertyHistory, PropertyImage, UserPropertyAssociation


class PropertyServiceError(Exception):
    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


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


def validar_direccion_unica(address, *, exclude_pk=None):
    address = (address or '').strip()
    if not address:
        raise PropertyServiceError('address_required', 'La dirección es obligatoria.')
    qs = Property.objects.filter(address__iexact=address)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise PropertyServiceError('address_exists', 'Ya existe un inmueble con esta dirección.')


def crear_propiedad(created_by, **data):
    address = data.pop('address', '')
    if not address and not data.get('google_maps_link'):
        raise PropertyServiceError('address_required', 'La dirección o el enlace de Google Maps es obligatorio.')
    if not address:
        address = 'Ver enlace de Google Maps adjunto'
    validar_direccion_unica(address)
    cover_image = data.pop('cover_image', None)
    gallery_images = data.pop('images', [])

    prop = Property(
        code=generar_codigo_propiedad(),
        address=address.strip(),
        status=Property.Status.AVAILABLE,
        created_by=created_by,
        **data,
    )
    if cover_image is not None:
        prop.cover_image = cover_image
    prop.save()

    # Save to PropertyImage model
    if cover_image is not None:
        PropertyImage.objects.create(property=prop, image=cover_image, is_cover=True)

    for img_file in gallery_images:
        if cover_image is not None and getattr(img_file, 'name', None) == getattr(cover_image, 'name', None):
            continue
        is_first_no_cover = not prop.images.filter(is_cover=True).exists()
        new_pi = PropertyImage.objects.create(property=prop, image=img_file, is_cover=is_first_no_cover)
        if is_first_no_cover and not prop.cover_image:
            prop.cover_image = new_pi.image
            prop.save()

    registrar_evento_propiedad(
        prop,
        PropertyHistory.EventType.CREATED,
        f'Inmueble creado {prop.code}',
        created_by=created_by,
        details={'address': prop.address, 'type': prop.type},
    )
    return prop


def actualizar_propiedad(prop, updated_by, **data):
    old_status = prop.status
    if 'address' in data:
        validar_direccion_unica(data['address'], exclude_pk=prop.pk)
        data['address'] = data['address'].strip()

    cover_image = data.pop('cover_image', None)
    new_images = data.pop('images', [])
    deleted_image_ids = data.pop('deleted_image_ids', [])
    set_cover_image_id = data.pop('set_cover_image_id', None)

    # 1. Handle deleted images
    if deleted_image_ids:
        PropertyImage.objects.filter(property=prop, id__in=deleted_image_ids).delete()

    # 2. Handle set cover image from existing
    if set_cover_image_id:
        target_img = PropertyImage.objects.filter(property=prop, id=set_cover_image_id).first()
        if target_img:
            PropertyImage.objects.filter(property=prop, is_cover=True).update(is_cover=False)
            target_img.is_cover = True
            target_img.save()
            prop.cover_image = target_img.image

    # 3. Handle new cover image upload
    if cover_image is not None:
        prop.cover_image = cover_image
        PropertyImage.objects.filter(property=prop, is_cover=True).update(is_cover=False)
        PropertyImage.objects.create(property=prop, image=cover_image, is_cover=True)

    # 4. Handle new gallery images upload
    for img_file in new_images:
        if cover_image is not None and getattr(img_file, 'name', None) == getattr(cover_image, 'name', None):
            continue
        is_first_no_cover = not prop.images.filter(is_cover=True).exists()
        new_pi = PropertyImage.objects.create(property=prop, image=img_file, is_cover=is_first_no_cover)
        if is_first_no_cover and not prop.cover_image:
            prop.cover_image = new_pi.image

    for field, value in data.items():
        setattr(prop, field, value)
    prop.save()

    if 'status' in data and old_status != prop.status:
        registrar_evento_propiedad(
            prop,
            PropertyHistory.EventType.STATUS_CHANGE,
            f'Estado {old_status} → {prop.status}',
            created_by=updated_by,
            details={'old': old_status, 'new': prop.status},
        )
    return prop


def agregar_imagenes(prop, images):
    for img_file in images:
        is_first_no_cover = not prop.images.filter(is_cover=True).exists()
        new_pi = PropertyImage.objects.create(property=prop, image=img_file, is_cover=is_first_no_cover)
        if is_first_no_cover and not prop.cover_image:
            prop.cover_image = new_pi.image
            prop.save()


def eliminar_imagen(prop, image_id):
    img = PropertyImage.objects.filter(property=prop, id=image_id).first()
    if not img:
        raise PropertyServiceError('image_not_found', 'Imagen no encontrada.')
    was_cover = img.is_cover
    img.delete()
    if was_cover:
        next_img = PropertyImage.objects.filter(property=prop).first()
        if next_img:
            next_img.is_cover = True
            next_img.save()
            prop.cover_image = next_img.image
        else:
            prop.cover_image = None
        prop.save()


def establecer_portada(prop, image_id):
    img = PropertyImage.objects.filter(property=prop, id=image_id).first()
    if not img:
        raise PropertyServiceError('image_not_found', 'Imagen no encontrada.')
    PropertyImage.objects.filter(property=prop, is_cover=True).update(is_cover=False)
    img.is_cover = True
    img.save()
    prop.cover_image = img.image
    prop.save()


def estadisticas_propiedades():
    by_status = {
        row['status']: row['count']
        for row in Property.objects.values('status').annotate(count=Count('id'))
    }
    by_type = {
        row['type']: row['count']
        for row in Property.objects.values('type').annotate(count=Count('id'))
    }
    return {
        'total': Property.objects.count(),
        'available': by_status.get(Property.Status.AVAILABLE, 0),
        'rented': by_status.get(Property.Status.RENTED, 0),
        'maintenance': by_status.get(Property.Status.MAINTENANCE, 0),
        'by_status': by_status,
        'by_type': by_type,
    }
